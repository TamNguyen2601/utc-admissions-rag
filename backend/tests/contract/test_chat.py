"""D1 contract: real handler/rules/retrieval, deterministic encoder and Gemini stub."""
import json

import pytest
from sqlalchemy import inspect

from app.services.gemini import GeminiService
from tests.chat_support import chat_client, add_document, ask, CONTEXT, QUESTION, ANSWER


def test_reply_and_citations_closed_contract(chat_client):
    identity = add_document(chat_client)
    response = ask(chat_client)
    assert response.status_code == 200, response.text
    data = response.json()
    assert set(data) == {'status', 'text', 'citations', 'context', 'missing_fields', 'request_id'}
    assert data['status'] == 'answered' and data['text'] == ANSWER
    assert data['request_id'] == response.headers['x-request-id']
    citation = data['citations'][0]
    assert set(citation) == {'document_id', 'chunk_id', 'content_hash', 'title', 'url',
                            'source_name', 'year', 'campus', 'page', 'section', 'available'}
    assert citation['document_id'] == identity and citation['available']
    assert data['context'] == CONTEXT
    assert 'conversation_messages' not in inspect(chat_client.app.state.database.engine).get_table_names()


@pytest.mark.parametrize('payload', [
    {'message': ''}, {'message': ' '}, {'message': 'x' * 4001}, {'message': 12},
    {'message': 'hi', 'conversation_id': 'forbidden'},
    {'message': 'hi', 'context': {'year': True}},
    {'message': 'hi', 'context': {'year': '2026'}},
    {'message': 'hi', 'context': {'year': 10000}},
    {'message': 'hi', 'context': {'campus': ''}},
    {'message': 'hi', 'context': {'major_code': 7480201}},
    {'message': 'hi', 'context': {'other': 'UTC'}},
    {'message': 'hi', 'turns': [{'sender': 'system', 'text': 'secret'}]},
    {'message': 'hi', 'turns': [{'sender': 'user', 'text': 'x', 'extra': True}]},
    {'message': 'hi', 'turns': [{'sender': 'user', 'text': 'x'}] * 11},
    {'message': 'hi', 'turns': [{'sender': 'user', 'text': 'x' * 4001}]},
    {'message': 'hi', 'turns': [{'sender': 'user', 'text': 'x' * 4000}] * 5},
])
def test_invalid_input_422(chat_client, payload):
    response = chat_client.post('/api/v1/chat/guest', json=payload)
    assert response.status_code == 422
    assert response.json()['error']['code'] == 'VALIDATION_ERROR'
    chat_client.app.state.chat.gemini.generate.assert_not_called()


def test_valid_boundaries_and_context_defaults(chat_client):
    response = chat_client.post('/api/v1/chat/guest', json={'message': '  Xin chào!  ',
        'turns': [{'sender': 'user', 'text': 'x' * 4000}] * 4})
    assert response.status_code == 200 and response.json()['status'] == 'social'
    assert response.json()['context'] == dict.fromkeys(CONTEXT)
    assert chat_client.post('/api/v1/chat/guest', json={'message': 'x' * 4000}).status_code == 200


@pytest.mark.parametrize('message,status', [
    ('Xin chào', 'social'), ('Cảm ơn', 'social'), ('Tạm biệt', 'social'),
    ('Thời tiết hôm nay ra sao?', 'out_of_scope'),
    ('Ngành CNTT trường Bách khoa học gì?', 'out_of_scope'),
    ('Ngành CNTT học gì?', 'needs_clarification'),
])
def test_non_rag_branches_no_gemini(chat_client, message, status):
    response = ask(chat_client, message=message, context={})
    assert response.json()['status'] == status and response.json()['citations'] == []
    chat_client.app.state.chat.gemini.generate.assert_not_called()


def test_invalid_bearer_never_becomes_guest(chat_client):
    response = chat_client.post('/api/v1/chat/guest', json={'message': 'Xin chào'},
                                headers={'Authorization': 'Bearer invalid'})
    assert response.status_code == 401 and response.headers['www-authenticate'] == 'Bearer'


def test_missing_and_unrelated_evidence(chat_client):
    assert ask(chat_client).json()['status'] == 'data_missing'
    add_document(chat_client, text='GIẢ LẬP medicine biology treatment.')
    assert ask(chat_client).json()['status'] == 'insufficient_evidence'
    chat_client.app.state.chat.gemini.generate.assert_not_called()


@pytest.mark.parametrize('raw', [
    'malformed JSON', json.dumps({'answer': 'FAKE OUTPUT', 'evidence_ids': ['E99']}),
    json.dumps({'answer': 'FAKE OUTPUT', 'evidence_ids': ['E1', 'E1']}),
    json.dumps({'answer': 'FAKE OUTPUT', 'evidence_ids': []}),
    json.dumps({'answer': 'FAKE OUTPUT', 'evidence_ids': ['E1'], 'url': 'https://fake.test'}),
    json.dumps({'answer': 'Nguồn: https://fake.test', 'evidence_ids': ['E1']}),
    json.dumps({'answer': 'Điểm chuẩn là 2026 điểm', 'evidence_ids': ['E1']}),
    json.dumps({'answer': 'Học phí 7480201 đồng', 'evidence_ids': ['E1']}),
])
def test_invalid_generation_becomes_insufficient(chat_client, raw):
    add_document(chat_client)
    chat_client.app.state.chat.gemini.generate.return_value = raw
    response = ask(chat_client)
    assert response.status_code == 200
    assert response.json()['status'] == 'insufficient_evidence' and response.json()['citations'] == []
    assert 'FAKE OUTPUT' not in response.text and 'fake.test' not in response.text


def test_missing_key_is_contract_error(chat_client):
    add_document(chat_client)
    chat_client.app.state.chat.gemini = GeminiService(chat_client.app.state.settings)
    response = ask(chat_client)
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'GEMINI_CONFIGURATION_ERROR'


def test_query_token_limit(chat_client):
    response = ask(chat_client, message='UTC công nghệ thông tin ' + 'token ' * 520)
    assert response.status_code == 422 and response.json()['error']['code'] == 'QUERY_TOO_LONG'
