"""T037: real SQLite/auth/ingestion/retrieval/history; synthetic encoder and Gemini.

Offline fixtures only. No live Gemini or official UTC data is used.
"""
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, select

from app.db.base import utc_now
from app.models.conversation import Conversation, Message
from app.models.identity import AuthSession, User
from app.models.knowledge import DataSource
from app.services.embedding import EmbeddingService
from app.services.gemini import ChatError
from tests.chat_support import chat_client, add_document, TEXT, QUESTION, CONTEXT  # noqa: F401
from tests.history_support import BASE, accounts, create, send, messages  # noqa: F401
from tests.knowledge_support import Model


def stored(client, conversation_id):
    with client.app.state.database.session() as db:
        conversation = db.get(Conversation, conversation_id)
        rows = db.scalars(select(Message).where(Message.conversation_id == conversation_id)
                          .order_by(Message.seq)).all()
        return conversation.next_seq, conversation.updated_at, [
            (m.id, m.seq, m.turn_id, m.sender, m.content, m.reply_status, m.citations_json) for m in rows]


@pytest.mark.parametrize('status,code', [
    (503, 'GEMINI_QUOTA_EXCEEDED'), (503, 'GEMINI_CONFIGURATION_ERROR'),
    (503, 'GEMINI_SERVICE_UNAVAILABLE'), (504, 'GEMINI_TIMEOUT'),
])
def test_service_failures_preserve_complete_history(chat_client, accounts, status, code, caplog):
    client, auth = chat_client, accounts['alice']
    add_document(client)
    conversation_id = create(client, auth)
    assert send(client, auth, conversation_id).status_code == 200
    before = stored(client, conversation_id)
    gemini = client.app.state.chat.gemini.generate
    gemini.side_effect = ChatError(status, code)
    response = send(client, auth, conversation_id, QUESTION, context=CONTEXT)
    assert response.status_code == status and response.json()['error']['code'] == code
    assert response.json()['error']['details'] is None
    assert stored(client, conversation_id) == before
    gemini.assert_awaited_once()
    assert QUESTION not in caplog.text
    # Failed request releases the conversation, so a new successful pair uses seq 3/4.
    assert send(client, auth, conversation_id).status_code == 200
    assert [m['seq'] for m in messages(client, auth, conversation_id)['items']] == [1, 2, 3, 4]


def test_unconfigured_real_adapter_does_not_persist(chat_client, accounts):
    client, state = chat_client, chat_client.app.state
    add_document(client)
    conversation_id = create(client, accounts['alice'])
    state.chat.gemini = state.gemini  # Real adapter, no key; no network call.
    response = send(client, accounts['alice'], conversation_id, QUESTION, context=CONTEXT)
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'GEMINI_CONFIGURATION_ERROR'
    assert stored(client, conversation_id)[0] == 1 and stored(client, conversation_id)[2] == []


@pytest.mark.parametrize('raw', ['not JSON', '{"answer":"FAKE","evidence_ids":["unknown"]}',
    '{"answer":"7480201 điểm","evidence_ids":["E1"]}'])
def test_invalid_model_output_saves_insufficient_evidence_pair(chat_client, accounts, raw):
    client, auth = chat_client, accounts['alice']
    add_document(client)
    conversation_id = create(client, auth)
    client.app.state.chat.gemini.generate.return_value = raw
    response = send(client, auth, conversation_id, QUESTION, context=CONTEXT)
    assert response.status_code == 200
    assert response.json()['reply']['status'] == 'insufficient_evidence'
    history = messages(client, auth, conversation_id)['items']
    assert len(history) == 2 and history[1]['reply_status'] == 'insufficient_evidence'
    assert history[1]['citations'] == []


def test_business_missing_clarification_and_conflict_keep_their_status(chat_client, accounts):
    client, auth = chat_client, accounts['alice']
    conversation_id = create(client, auth)
    for question, status in [(QUESTION, 'data_missing'),
                             ('UTC điểm chuẩn?', 'needs_clarification'),
                             ('Thời tiết thế nào?', 'out_of_scope')]:
        response = send(client, auth, conversation_id, question)
        assert response.status_code == 200 and response.json()['reply']['status'] == status
        assert messages(client, auth, conversation_id)['items'][-1]['reply_status'] == status
    text = 'GIẢ LẬP — KHÔNG PHẢI THÔNG TIN UTC.\nĐiểm chuẩn: 25 điểm'
    add_document(client, text=text)
    add_document(client, text=text.replace('25 điểm', '26 điểm'),
                 url='https://tuyensinh.utc.edu.vn/conflict')
    response = send(client, auth, conversation_id, 'UTC điểm chuẩn?', context=CONTEXT)
    assert response.json()['reply']['status'] == 'conflicting_sources'
    saved = messages(client, auth, conversation_id)['items'][-1]
    assert saved['reply_status'] == 'conflicting_sources' and len(saved['citations']) == 2


def test_outer_timeout_then_late_cpu_cannot_save(chat_client, accounts, monkeypatch):
    client, auth, state = chat_client, accounts['alice'], chat_client.app.state
    add_document(client)
    conversation_id = create(client, auth)
    before = stored(client, conversation_id)
    state.settings.chat_deadline_seconds = .06
    entered, release, finished = Event(), Event(), Event()
    original = state.chat._retrieve

    def slow(*args):
        entered.set()
        try:
            assert release.wait(5)
            return original(*args)
        finally:
            finished.set()

    monkeypatch.setattr(state.chat, '_retrieve', slow)
    try:
        response = send(client, auth, conversation_id, QUESTION, context=CONTEXT)
        assert entered.is_set() and response.status_code == 504
        assert response.json()['error']['code'] == 'REQUEST_DEADLINE_EXCEEDED'
        assert stored(client, conversation_id) == before
        # While the timed-out CPU still runs, a different request can finalize a valid pair.
        state.settings.chat_deadline_seconds = 60
        assert send(client, auth, conversation_id).status_code == 200
        after = stored(client, conversation_id)
    finally:
        release.set()
        assert finished.wait(5)
    assert stored(client, conversation_id) == after
    state.chat.gemini.generate.assert_not_called()


def test_late_gemini_cannot_save_even_if_it_suppresses_cancellation(chat_client, accounts):
    client, auth, state = chat_client, accounts['alice'], chat_client.app.state
    add_document(client)
    conversation_id = create(client, auth)
    before = stored(client, conversation_id)
    state.settings.chat_deadline_seconds = .08

    async def late(*args):
        try:
            await asyncio.sleep(.2)
        except asyncio.CancelledError:
            pass
        return '{"answer":"KẾT QUẢ MUỘN","evidence_ids":["E1"]}'

    state.chat.gemini.generate.side_effect = late
    response = send(client, auth, conversation_id, QUESTION, context=CONTEXT)
    assert response.status_code == 504 and 'KẾT QUẢ MUỘN' not in response.text
    assert stored(client, conversation_id) == before


def test_wait_for_publish_lock_is_inside_account_deadline(chat_client, accounts):
    client, auth, state = chat_client, accounts['alice'], chat_client.app.state
    add_document(client)
    conversation_id = create(client, auth)
    before = stored(client, conversation_id)
    state.settings.chat_deadline_seconds = .08

    async def generate(*args):
        state.knowledge_lock.acquire()
        return '{"answer":"Mô tả chương trình","evidence_ids":["E1"]}'

    state.chat.gemini.generate.side_effect = generate
    try:
        response = send(client, auth, conversation_id, QUESTION, context=CONTEXT)
        assert response.status_code == 504
    finally:
        state.knowledge_lock.release()
    assert stored(client, conversation_id) == before


@pytest.mark.parametrize('change', ['logout', 'expired', 'inactive'])
def test_recheck_identity_after_gemini_wait(chat_client, accounts, change):
    client, auth, state = chat_client, accounts['alice'], chat_client.app.state
    add_document(client)
    conversation_id = create(client, auth)
    before = stored(client, conversation_id)

    async def generate(*args):
        if change == 'logout':
            response = await asyncio.to_thread(client.post, '/api/v1/auth/logout', headers=auth)
            assert response.status_code == 204
        else:
            with state.database.session() as db:
                user_id = db.get(Conversation, conversation_id).user_id
                if change == 'inactive':
                    db.get(User, user_id).active = False
                else:
                    session = db.scalar(select(AuthSession).where(AuthSession.user_id == user_id))
                    session.expires_at = utc_now() - timedelta(seconds=1)
                db.commit()
        return '{"answer":"Mô tả chương trình","evidence_ids":["E1"]}'

    state.chat.gemini.generate.side_effect = generate
    response = send(client, auth, conversation_id, QUESTION, context=CONTEXT)
    assert response.status_code == 401 and response.headers['www-authenticate'] == 'Bearer'
    assert stored(client, conversation_id) == before


def test_busy_is_per_conversation_and_owner_checked_first(chat_client, accounts):
    client, auth, state = chat_client, accounts['alice'], chat_client.app.state
    add_document(client)
    conversation_id, other = create(client, auth), create(client, auth)
    entered, release = Event(), Event()

    async def held(*args):
        entered.set()
        while not release.is_set():
            await asyncio.sleep(.005)
        return '{"answer":"Mô tả chương trình","evidence_ids":["E1"]}'

    state.chat.gemini.generate.side_effect = held
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(send, client, auth, conversation_id, QUESTION, context=CONTEXT)
        try:
            assert entered.wait(5)
            response = send(client, auth, conversation_id)
            assert response.status_code == 409 and response.json()['error']['code'] == 'CONVERSATION_BUSY'
            for headers in (accounts['bob'], accounts['admin']):
                assert send(client, headers, conversation_id).status_code == 404
            assert send(client, auth, other).status_code == 200
            for method, payload in (('PATCH', {'title': 'busy'}), ('DELETE', None)):
                response = client.request(method, f'{BASE}/{conversation_id}', headers=auth,
                                          **({'json': payload} if payload else {}))
                assert response.status_code == 409
            assert messages(client, auth, conversation_id)['total'] == 0
        finally:
            release.set()
        assert pending.result(timeout=5).status_code == 200
    assert messages(client, auth, conversation_id)['total'] == 2
    assert send(client, auth, conversation_id).status_code == 200


@pytest.mark.parametrize('kind', ['disable', 'delete', 'update', 'permission'])
def test_source_change_during_generation_saves_truthful_status(chat_client, accounts, kind):
    client, auth, state = chat_client, accounts['alice'], chat_client.app.state
    document_id = add_document(client)
    conversation_id = create(client, auth)

    async def generate(*args):
        if kind == 'disable':
            state.documents.set_enabled(document_id, False)
        elif kind == 'delete':
            state.documents.delete(document_id)
        elif kind == 'update':
            add_document(client, text=TEXT + '\nNội dung mới.')
        else:
            with state.knowledge_lock, state.database.session() as db:
                source = db.get(DataSource, state.test_source_id)
                source.enabled, source.permission_status = False, 'denied'
                db.commit()
        return '{"answer":"CÂU TRẢ LỜI CŨ","evidence_ids":["E1"]}'

    state.chat.gemini.generate.side_effect = generate
    response = send(client, auth, conversation_id, QUESTION, context=CONTEXT)
    assert response.status_code == 200 and response.json()['reply']['status'] == 'insufficient_evidence'
    history = messages(client, auth, conversation_id)['items']
    assert len(history) == 2 and history[1]['reply_status'] == 'insufficient_evidence'
    assert history[1]['citations'] == [] and 'CÂU TRẢ LỜI CŨ' not in history[1]['content']


@pytest.mark.parametrize('kind', ['disable', 'delete', 'update', 'permission', 'chunk', 'hash'])
def test_snapshots_survive_source_changes_and_never_become_new_evidence(chat_client, accounts, kind):
    client, auth, state = chat_client, accounts['alice'], chat_client.app.state
    document_id = add_document(client)
    conversation_id = create(client, auth)
    response = send(client, auth, conversation_id, QUESTION, context=CONTEXT)
    assert response.status_code == 200 and response.json()['reply']['status'] == 'answered'
    citation = response.json()['reply']['citations'][0]
    before = stored(client, conversation_id)
    assert before[2][0][2] == before[2][1][2]  # shared turn_id
    assert 'available' not in before[2][1][6][0]
    assert messages(client, auth, conversation_id)['items'][1]['citations'][0] == citation
    if kind == 'disable':
        state.documents.set_enabled(document_id, False)
    elif kind == 'delete':
        state.documents.delete(document_id)
    elif kind == 'update':
        add_document(client, text=TEXT + '\nNội dung thay đổi.')
    else:
        from app.models.knowledge import Document, DocumentChunk
        with state.knowledge_lock, state.database.session() as db:
            if kind == 'permission':
                source = db.get(DataSource, state.test_source_id)
                source.enabled, source.permission_status = False, 'denied'
            elif kind == 'chunk':
                db.delete(db.get(DocumentChunk, citation['chunk_id']))
            else:
                db.get(Document, document_id).content_hash = 'changed-hash'
            db.commit()
    old = messages(client, auth, conversation_id)['items'][1]
    assert old['reply_status'] == 'answered'
    assert old['citations'] == [citation | {'available': False}]
    assert stored(client, conversation_id) == before  # computed availability is never written back
    expected_source_status = 404 if kind == 'delete' else (200 if kind in {'update', 'hash'} else 410)
    assert client.get(f'/api/v1/documents/{document_id}/source').status_code == expected_source_status
    if kind in {'update', 'hash'}:
        response = send(client, auth, conversation_id, QUESTION, context=CONTEXT)
        assert response.json()['reply']['status'] == 'answered'
        evidence = state.chat.gemini.generate.call_args.args[1]
        assert all(hit['content_hash'] != citation['content_hash'] for hit in evidence.values())
        if kind == 'update':
            assert all(hit['chunk_id'] != citation['chunk_id'] for hit in evidence.values())
    else:
        state.chat.gemini.generate.reset_mock()
        response = send(client, auth, conversation_id, QUESTION, context=CONTEXT)
        assert response.json()['reply']['status'] in {'data_missing', 'insufficient_evidence'}
        assert response.json()['reply']['citations'] == []
        state.chat.gemini.generate.assert_not_called()


def test_atomic_rollback_after_flush_and_deadline_before_commit(chat_client, accounts, monkeypatch):
    client, auth, state = chat_client, accounts['alice'], chat_client.app.state
    conversation_id = create(client, auth)
    before = stored(client, conversation_id)
    original = state.conversations.add_pair

    def failure(*args):
        original(*args)
        raise RuntimeError('SENSITIVE INTERNAL FAILURE')

    monkeypatch.setattr(state.conversations, 'add_pair', failure)
    response = send(client, auth, conversation_id)
    assert response.status_code == 500 and 'SENSITIVE' not in response.text
    assert stored(client, conversation_id) == before

    def slow_flush(*args):
        result = original(*args)
        time.sleep(.08)
        return result

    monkeypatch.setattr(state.conversations, 'add_pair', slow_flush)
    state.settings.chat_deadline_seconds = .04
    assert send(client, auth, conversation_id).status_code == 504
    assert stored(client, conversation_id) == before
    monkeypatch.setattr(state.conversations, 'add_pair', original)
    state.settings.chat_deadline_seconds = 60
    assert send(client, auth, conversation_id).status_code == 200
    assert stored(client, conversation_id)[0] == 3


def test_session_expiring_during_flush_cannot_commit(chat_client, accounts, monkeypatch):
    from app.services import chat as chat_module
    client, auth, state = chat_client, accounts['alice'], chat_client.app.state
    conversation_id = create(client, auth)
    before = stored(client, conversation_id)
    original = state.conversations.add_pair

    def expire(*args):
        result = original(*args)
        monkeypatch.setattr(chat_module, 'utc_now', lambda: utc_now() + timedelta(hours=1))
        return result

    monkeypatch.setattr(state.conversations, 'add_pair', expire)
    response = send(client, auth, conversation_id)
    assert response.status_code == 401
    assert stored(client, conversation_id) == before


def test_guest_with_or_without_auth_does_not_store_or_log_history(chat_client, accounts, caplog):
    client, state = chat_client, chat_client.app.state
    conversation_id = create(client, accounts['alice'])
    before = stored(client, conversation_id)
    statements = []

    def record(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().split()[0].upper())

    event.listen(state.database.engine, 'before_cursor_execute', record)
    try:
        for headers in ({}, accounts['alice']):
            response = client.post('/api/v1/chat/guest', headers=headers,
                                   json={'message': 'PRIVATE-GUEST-CONTENT'})
            assert response.status_code == 200
    finally:
        event.remove(state.database.engine, 'before_cursor_execute', record)
    assert not set(statements) & {'INSERT', 'UPDATE', 'DELETE', 'REPLACE', 'CREATE'}
    assert stored(client, conversation_id) == before
    assert 'PRIVATE-GUEST-CONTENT' not in caplog.text


def test_history_is_bounded_text_context_only(chat_client, accounts, monkeypatch):
    client, auth, state = chat_client, accounts['alice'], chat_client.app.state
    add_document(client)
    conversation_id = create(client, auth)
    assert send(client, auth, conversation_id, QUESTION, context=CONTEXT).status_code == 200
    captured = []
    from app.services import chat as chat_module
    original = chat_module.classify

    def classify(payload, resolver):
        captured.append(payload.turns)
        return original(payload, resolver)

    monkeypatch.setattr(chat_module, 'classify', classify)
    assert send(client, auth, conversation_id, 'Ngành công nghệ thông tin đào tạo thế nào?').json()['reply']['status'] == 'answered'
    assert len(captured[-1]) == 2 and captured[-1][0].text == QUESTION
    assert all(set(turn.model_dump()) == {'sender', 'text'} for turn in captured[-1])
    for _ in range(6):
        assert send(client, auth, conversation_id, 'Cảm ơn ' + ' ' * 2).status_code == 200
    assert len(captured[-1]) == 10
    for _ in range(5):
        assert send(client, auth, conversation_id, 'x' * 4000).status_code == 200
    assert sum(len(t.text) for t in captured[-1]) <= 16000


def test_restart_keeps_owner_sequence_and_snapshot(application, monkeypatch):
    from app import main
    monkeypatch.setattr(main.EmbeddingService, 'local',
                        lambda settings: EmbeddingService(settings, model=Model()))
    with TestClient(application) as client:
        credentials = {'email': 'restart@example.test', 'password': 'SYNTHETIC-password'}
        assert client.post('/api/v1/auth/register', json=credentials).status_code == 201
        token = client.post('/api/v1/auth/login', json=credentials).json()['access_token']
        auth = {'Authorization': f'Bearer {token}'}
        conversation_id = create(client, auth)
        with client.app.state.database.session() as db:
            source = DataSource(name='GIẢ LẬP', kind='utc', base_url='https://tuyensinh.utc.edu.vn/',
                allowed_paths_json=['/'], enabled=True, permission_status='allowed',
                reuse_basis='FIXTURE ONLY', checked_at=utc_now(), min_interval_seconds=2)
            db.add(source)
            db.commit()
            client.app.state.test_source_id = source.id
        document_id = add_document(client)
        assert send(client, auth, conversation_id, 'UTC điểm chuẩn?').status_code == 200
        # Numeric native quote bypasses Gemini, allowing a real persistence/restart test without SDK.
        add_document(client, text='GIẢ LẬP — KHÔNG PHẢI THÔNG TIN UTC.\nĐiểm chuẩn: 25 điểm')
        response = send(client, auth, conversation_id, 'UTC điểm chuẩn?', context=CONTEXT)
        assert response.json()['reply']['status'] == 'answered'
        citation = response.json()['reply']['citations'][0]
        history = messages(client, auth, conversation_id)
        document_id = citation['document_id']
        client.app.state.documents.set_enabled(document_id, False)
        assert client.patch(f'{BASE}/{conversation_id}', headers=auth, json={'title': 'Bền qua restart'}).status_code == 200
    restarted = main.create_app(application.state.settings)
    with TestClient(restarted) as client:
        assert client.get(f'{BASE}/{conversation_id}', headers=auth).json()['title'] == 'Bền qua restart'
        restored = messages(client, auth, conversation_id)
        assert restored['total'] == history['total']
        assert [m['id'] for m in restored['items']] == [m['id'] for m in history['items']]
        assert restored['items'][-1]['citations'] == [citation | {'available': False}]
        assert send(client, auth, conversation_id).status_code == 200
        assert [m['seq'] for m in messages(client, auth, conversation_id)['items']] == list(range(1, 7))
