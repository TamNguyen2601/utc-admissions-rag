"""SQLite + real catalogue/quiz services and APIs; labelled synthetic source only."""
from copy import deepcopy
import json
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select, update
from sqlalchemy.exc import IntegrityError

from app.models.knowledge import DataSource, Document, DocumentOrigin
from app.models.quiz import Major, QuizQuestion
from app.services.recommendation import RecommendationService
from tests.quiz_support import (quiz_client, job_client, admin_client, catalogue, request_body, BASE)  # noqa: F401


def snapshot(client):
    return client.get(BASE + '/quiz').json(), client.get(BASE + '/catalog/majors').json()


@pytest.mark.parametrize('bad', ['few_majors', 'few_questions', 'duplicate_major_id', 'duplicate_code_campus',
    'duplicate_position', 'duplicate_question', 'missing_mapping', 'extra_mapping', 'direction', 'reason',
    'zero_denominator', 'all_none_question', 'source_hash', 'source_missing', 'page', 'major_unproven', 'extra',
    'duplicate_group', 'direction_extra', 'position_bool', 'duplicate_scoring_alias'])
def test_invalid_import_preserves_entire_catalogue(quiz_client, bad):
    client = quiz_client
    before = snapshot(client)
    data = deepcopy(client.catalogue)
    major_id = data['majors'][0]['id']
    if bad == 'few_majors': data['majors'].pop()
    elif bad == 'few_questions': data['questions'].pop()
    elif bad == 'duplicate_major_id': data['majors'][1]['id'] = major_id
    elif bad == 'duplicate_code_campus': data['majors'][1]['code'] = data['majors'][0]['code']
    elif bad == 'duplicate_position': data['questions'][1]['position'] = 1
    elif bad == 'duplicate_question': data['questions'][1]['id'] = data['questions'][0]['id']
    elif bad == 'missing_mapping': data['questions'][0]['scoring'].pop(major_id)
    elif bad == 'extra_mapping': data['questions'][0]['scoring'][str(uuid4())] = dict(direction='none', reason='test')
    elif bad == 'direction': data['questions'][0]['scoring'][major_id]['direction'] = 'reverse'
    elif bad == 'reason': data['questions'][0]['scoring'][major_id]['reason'] = '  '
    elif bad == 'zero_denominator':
        for q in data['questions']: q['scoring'][major_id]['direction'] = 'none'
    elif bad == 'all_none_question':
        for r in data['questions'][0]['scoring'].values(): r['direction'] = 'none'
    elif bad == 'source_hash': data['majors'][0]['source_content_hash'] = '0'*64
    elif bad == 'source_missing': data['majors'][0]['source_document_id'] = str(uuid4())
    elif bad == 'page': data['majors'][0]['source_page'] = 0
    elif bad == 'major_unproven': data['majors'][0]['name'] = 'Invented major absent from document'
    elif bad == 'extra': data['admission_score'] = 20
    elif bad == 'duplicate_group': data['majors'][0]['career_groups'] *= 2
    elif bad == 'direction_extra': data['questions'][0]['scoring'][major_id]['weight'] = 2
    elif bad == 'position_bool': data['questions'][0]['position'] = True
    elif bad == 'duplicate_scoring_alias':
        data['questions'][0]['scoring']['{' + major_id + '}'] = dict(direction='negative', reason='Alias duplicate')
    with pytest.raises(ValueError):
        client.app.state.recommendation.import_catalog(data)
    assert snapshot(client) == before


def test_sql_failure_after_deletes_and_partial_inserts_rolls_back(quiz_client):
    client = quiz_client
    before = snapshot(client)
    data = deepcopy(client.catalogue)
    data['questions'][0]['text'] += ' changed'

    def fail_questions(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith('INSERT INTO quiz_questions'):
            raise RuntimeError('synthetic database failure after majors inserted')

    engine = client.app.state.database.engine
    event.listen(engine, 'before_cursor_execute', fail_questions)
    try:
        with pytest.raises(RuntimeError): client.app.state.recommendation.import_catalog(data)
    finally:
        event.remove(engine, 'before_cursor_execute', fail_questions)
    assert snapshot(client) == before


@pytest.mark.parametrize('change', ['direction', 'reason', 'none_reason', 'question', 'description', 'group', 'page'])
def test_rubric_hash_tracks_all_scoring_and_catalogue_content(quiz_client, change):
    client = quiz_client
    old = request_body(client)
    data = deepcopy(client.catalogue)
    mid = data['majors'][0]['id']
    if change == 'direction': data['questions'][0]['scoring'][mid]['direction'] = 'negative'
    elif change == 'reason': data['questions'][0]['scoring'][mid]['reason'] += ' changed'
    elif change == 'none_reason': data['questions'][2]['scoring'][mid]['reason'] += ' changed'
    elif change == 'question': data['questions'][0]['text'] += ' changed'
    elif change == 'description': data['majors'][0]['description'] += ' changed'
    elif change == 'group': data['majors'][0]['career_groups'][0]['reason'] += ' changed'
    else: data['majors'][0]['source_page'] = 1
    new = client.app.state.recommendation.import_catalog(data)
    assert new != old['rubric_version']
    response = client.post(BASE + '/recommendations', json=old)
    assert response.status_code == 409 and response.json()['error']['code'] == 'RUBRIC_CHANGED'


def test_identical_reimport_order_and_restart_keep_version_and_ids(quiz_client):
    client = quiz_client
    before = snapshot(client)
    data = deepcopy(client.catalogue)
    data['majors'].reverse()
    data['questions'].reverse()
    service = client.app.state.recommendation
    service.import_catalog(data)
    assert snapshot(client) == before
    from app.db.session import Database
    reopened = Database(client.app.state.settings)
    try:
        reopened.initialize()
        assert RecommendationService(reopened).quiz() == service.quiz()
    finally:
        reopened.dispose()


@pytest.mark.parametrize('bad', ['hash', 'disabled_doc', 'quarantined', 'pending', 'error', 'disabled_source', 'denied',
                                'unknown', 'origin_inactive', 'origin_missing', 'deleted', 'unofficial', 'wrong_kind'])
def test_source_unavailable_overrides_stale_version_and_filters_catalogue(quiz_client, bad):
    client = quiz_client
    body = request_body(client)
    body['rubric_version'] = 'stale'
    doc_id = client.catalogue['majors'][0]['source_document_id']
    with client.app.state.database.session() as db:
        doc = db.get(Document, doc_id)
        source = db.get(DataSource, client.catalogue_source)
        origin = db.scalar(select(DocumentOrigin).where(DocumentOrigin.document_id == doc.id))
        if bad == 'hash': doc.content_hash = '0'*64
        elif bad == 'disabled_doc': doc.enabled = False
        elif bad == 'quarantined': doc.state, doc.quality_reason = 'quarantined', 'synthetic gate'
        elif bad in {'pending', 'error'}: doc.state = bad
        elif bad == 'disabled_source': source.enabled = False
        elif bad in {'denied', 'unknown'}: source.enabled, source.permission_status = False, bad
        elif bad == 'origin_inactive': origin.active = False
        elif bad == 'origin_missing': db.delete(origin)
        elif bad == 'deleted': db.delete(doc)
        elif bad == 'wrong_kind': source.kind = 'career'
        else: origin.canonical_url = 'https://unofficial.example.test/catalog'
        db.commit()
    quiz = client.get(BASE + '/quiz').json()
    assert quiz['status'] == 'data_missing' and quiz['questions'] == [] and quiz['rubric_version'] is None
    response = client.post(BASE + '/recommendations', json=body)
    assert response.status_code == 200 and response.json()['status'] == 'data_missing'
    assert client.get(BASE + '/catalog/majors').json()['items'] == []
    with pytest.raises(ValueError): client.app.state.recommendation.import_catalog(client.catalogue)


@pytest.mark.parametrize('bad', ['mapping', 'direction', 'reason', 'zero', 'all_none_question', 'missing_question', 'inactive_major'])
def test_corrupt_database_rubric_is_missing_instead_of_partial_or_500(quiz_client, bad):
    client = quiz_client
    body = request_body(client)
    mid = client.catalogue['majors'][0]['id']
    with client.app.state.database.session() as db:
        questions = db.scalars(select(QuizQuestion).order_by(QuizQuestion.position)).all()
        if bad == 'missing_question': db.delete(questions[0])
        elif bad == 'inactive_major': db.get(Major, mid).active = False
        else:
            for q in questions:
                mapping = deepcopy(q.scoring_json)
                if bad == 'mapping': mapping.pop(mid)
                elif bad == 'direction': mapping[mid]['direction'] = 'bogus'
                elif bad == 'reason': mapping[mid]['reason'] = ''
                elif bad == 'zero': mapping[mid]['direction'] = 'none'
                else:
                    for r in mapping.values(): r['direction'] = 'none'
                # Raw SQL update deliberately bypasses application import validators.
                db.execute(update(QuizQuestion).where(QuizQuestion.id == q.id).values(scoring_json=mapping))
                if bad != 'zero': break
        db.commit()
    assert client.get(BASE + '/quiz').json()['status'] == 'data_missing'
    assert client.post(BASE + '/recommendations', json=body).json()['status'] == 'data_missing'


@pytest.mark.parametrize('positive_majors,expected', [(0, 'no_match'), (1, 'insufficient_matches'), (2, 'insufficient_matches')])
def test_zero_and_one_or_two_matches(quiz_client, positive_majors, expected):
    client = quiz_client
    data = deepcopy(client.catalogue)
    for q in data['questions']:
        for i, m in enumerate(data['majors']):
            q['scoring'][m['id']]['direction'] = 'negative' if q['position'] == 2 else 'positive'
            if i < positive_majors and q['position'] == 1:
                q['scoring'][m['id']]['direction'] = 'negative'
    client.app.state.recommendation.import_catalog(data)
    response = client.post(BASE + '/recommendations', json=request_body(client, [1, 5] + [1]*8))
    assert response.status_code == 200 and response.json()['status'] == expected
    assert response.json()['items'] == [] and response.json()['message']


@pytest.mark.parametrize('count', [3, 4, 5, 6])
def test_top_three_to_five_and_campus_tie_break(quiz_client, count):
    client = quiz_client
    first = client.catalogue['majors'][0]
    data = catalogue(first['source_document_id'], first['source_content_hash'], count)
    # Same code and name at different campuses is allowed and sorted by campus.
    data['majors'][0]['code'] = data['majors'][1]['code'] = 'A'
    data['majors'][1]['name'] = data['majors'][0]['name']
    data['majors'][0]['campus'], data['majors'][1]['campus'] = 'Z campus', 'A campus'
    client.app.state.recommendation.import_catalog(data)
    result = client.post(BASE + '/recommendations', json=request_body(client)).json()
    assert result['status'] == 'ready' and len(result['items']) == min(count, 5)
    assert [m['major']['campus'] for m in result['items'][:2]] == ['A campus', 'Z campus']
    assert all('Chưa có xu hướng nổi trội.' in item['reasons'][0] for item in result['items'])


def test_sort_uses_raw_score_before_display_rounding(quiz_client, monkeypatch):
    from fractions import Fraction
    import app.services.recommendation as module
    client = quiz_client
    higher = client.catalogue['majors'][1]['id']
    monkeypatch.setattr(module, 'score_major', lambda mid, qs, answers: (
        Fraction(50004 if mid == higher else 50003, 1000), ['Synthetic reason']))
    result = client.post(BASE + '/recommendations', json=request_body(client)).json()
    assert result['items'][0]['major']['code'] == 'B'
    assert [i['fit_score'] for i in result['items']] == [50.0]*3


def test_reasons_rank_contribution_then_position_and_include_source(quiz_client):
    client = quiz_client
    response = client.post(BASE + '/recommendations', json=request_body(client, [4, 1, 5, 5] + [3]*6)).json()
    a = next(i for i in response['items'] if i['major']['code'] == 'A')
    assert 'không đồng ý với câu nghịch' in a['reasons'][0] and 'câu 2:' in a['reasons'][0]
    assert 'câu 1:' in a['reasons'][1] and all('Nguồn:' in r for r in a['reasons'])
    c = next(i for i in response['items'] if i['major']['code'] == 'C')
    assert 'câu 3:' in c['reasons'][0] and 'câu 4:' in c['reasons'][1]


def test_two_decimal_display(quiz_client):
    client = quiz_client
    data = deepcopy(client.catalogue)
    a = data['majors'][0]['id']
    data['questions'][2]['scoring'][a]['direction'] = 'positive'
    client.app.state.recommendation.import_catalog(data)
    # A=(1+.75+0)/3. B and C remain positive, so the API returns the ranking.
    result = client.post(BASE + '/recommendations', json=request_body(client, [5, 2, 1] + [3]*7)).json()
    item = next(i for i in result['items'] if i['major']['code'] == 'A')
    assert item['fit_score'] == 58.33


def test_no_gemini_no_profile_persistence_for_guest_or_account(quiz_client, monkeypatch):
    client = quiz_client
    monkeypatch.setattr(client.app.state.gemini, 'generate', lambda *a, **k: pytest.fail('Quiz must not call Gemini'))
    def counts():
        with client.app.state.database.session() as db:
            from app.db.base import Base
            return {table.name: db.scalar(select(func.count()).select_from(table)) for table in Base.metadata.sorted_tables}
    before = counts()
    body = request_body(client)
    assert client.post(BASE + '/recommendations', json=body).json()['status'] == 'ready'
    assert counts() == before
    client.headers.pop('Authorization')
    assert client.post(BASE + '/recommendations', json=body).json()['status'] == 'ready'
    assert counts() == before
    assert len(before) == 13


def test_source_new_hash_requires_full_reimport_and_new_version(quiz_client):
    import hashlib
    client = quiz_client
    old = request_body(client)
    payload = deepcopy(client.catalogue)
    with client.app.state.database.session() as db:
        doc = db.get(Document, payload['majors'][0]['source_document_id'])
        doc.content_text += '\nSYNTHETIC updated source description.'
        doc.content_hash = hashlib.sha256(doc.content_text.encode()).hexdigest()
        new_hash = doc.content_hash
        db.commit()
    assert client.get(BASE + '/quiz').json()['status'] == 'data_missing'
    for major in payload['majors']: major['source_content_hash'] = new_hash
    version = client.app.state.recommendation.import_catalog(payload)
    assert version != old['rubric_version']
    assert client.get(BASE + '/quiz').json()['status'] == 'ready'
    assert client.post(BASE + '/recommendations', json=old).status_code == 409


@pytest.mark.parametrize('publisher,expected', [('Trường Đại học Giao thông vận tải', True),
                                            ('unidentified publisher', False)])
def test_offline_official_upload_needs_publisher_and_provenance(quiz_client, publisher, expected):
    client = quiz_client
    with client.app.state.database.session() as db:
        doc_id = client.catalogue['majors'][0]['source_document_id']
        origin = db.scalar(select(DocumentOrigin).where(DocumentOrigin.document_id == doc_id))
        origin.canonical_url = origin.original_url = 'urn:upload:' + origin.id
        origin.publisher = publisher
        db.commit()
    assert (client.get(BASE + '/quiz').json()['status'] == 'ready') is expected


def test_partial_source_loss_hides_only_affected_majors_but_invalidates_rubric(quiz_client):
    client = quiz_client
    with client.app.state.database.session() as db:
        db.get(Major, client.catalogue['majors'][0]['id']).source_content_hash = 'f'*64
        db.commit()
    catalog = client.get(BASE + '/catalog/majors').json()
    assert catalog['total'] == 2 and [m['code'] for m in catalog['items']] == ['B', 'C']
    assert client.get(BASE + '/quiz').json()['status'] == 'data_missing'


def test_cli_oversize_rejected_without_mutation(quiz_client, tmp_path, monkeypatch):
    import app.cli.import_catalog as cli
    before = snapshot(quiz_client)
    monkeypatch.setattr(cli, 'MAX_CATALOG_BYTES', 16)
    path = tmp_path / 'large.json'
    path.write_bytes(b' ' * 17)
    assert cli.main(['--file', str(path)]) == 1
    assert snapshot(quiz_client) == before


def test_model_and_database_constraints(quiz_client):
    client = quiz_client
    first = client.catalogue['majors'][0]
    row = dict(first)
    row['id'] = str(uuid4())
    row['career_groups_json'] = row.pop('career_groups')
    with client.app.state.database.session() as db:
        with pytest.raises(IntegrityError):
            db.add(Major(**row)); db.flush()
        db.rollback()
    with pytest.raises(ValueError):
        QuizQuestion(position=1, text='Synthetic', scoring_json={first['id']: dict(direction='bogus', reason='test')})
    with client.app.state.database.session() as db:
        q = client.catalogue['questions'][0]
        db.add(QuizQuestion(position=1, text=q['text'], scoring_json=q['scoring']))
        with pytest.raises(IntegrityError): db.flush()
        db.rollback()
        db.add(QuizQuestion(position=1, text=q['text'], scoring_json=q['scoring'], active=False))
        db.commit()
    assert client.get(BASE + '/quiz').json()['status'] == 'ready'


def test_cli_valid_import_and_invalid_file_atomicity(quiz_client, tmp_path, capsys):
    from app.cli.import_catalog import main
    client = quiz_client
    path = tmp_path / 'catalog.json'
    path.write_text(json.dumps(client.catalogue), encoding='utf-8')
    before = snapshot(client)
    assert main(['--file', str(path)]) == 0
    assert 'rubric_version=' in capsys.readouterr().out
    assert snapshot(client) == before
    for invalid in ['{"majors":[],"majors":[]}', '{broken', '{}', '[]']:
        path.write_text(invalid, encoding='utf-8')
        assert main(['--file', str(path)]) == 1
        assert snapshot(client) == before
    assert main(['--file', str(tmp_path / 'absent.json')]) == 1
    output = capsys.readouterr().out
    assert 'Traceback' not in output and str(tmp_path) not in output
