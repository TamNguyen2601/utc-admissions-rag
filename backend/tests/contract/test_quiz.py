"""Closed REST schemas and all public recommendation states; actual SQLite rubric."""
from copy import deepcopy
from uuid import uuid4

import pytest

from tests.quiz_support import quiz_client, job_client, admin_client, BASE, request_body, CASES  # noqa: F401


def test_missing_schema_and_input_structure_precedence(job_client):
    client = job_client
    quiz = client.get(BASE + '/quiz').json()
    assert set(quiz) == {'status', 'rubric_version', 'questions', 'scoring_description', 'missing_fields', 'message'}
    assert quiz['status'] == 'data_missing' and quiz['questions'] == []
    assert quiz['rubric_version'] is None and quiz['scoring_description'] is None
    assert quiz['missing_fields'] and quiz['message']
    body = dict(rubric_version='stale', answers=[dict(question_id=str(uuid4()), value=3) for _ in range(10)])
    result = client.post(BASE + '/recommendations', json=body).json()
    assert result['status'] == 'data_missing' and result['rubric_version'] is None
    assert result['items'] == [] and result['missing_fields'] and result['message']
    assert set(result) == {'status', 'rubric_version', 'items', 'missing_fields', 'message', 'disclaimer'}
    body['answers'][0]['value'] = True
    assert client.post(BASE + '/recommendations', json=body).status_code == 422


def test_ready_quiz_and_catalogue_schema(quiz_client):
    client = quiz_client
    quiz = client.get(BASE + '/quiz').json()
    assert set(quiz) == {'status', 'rubric_version', 'questions', 'scoring_description', 'missing_fields', 'message'}
    assert quiz['status'] == 'ready' and len(quiz['questions']) == 10
    assert quiz['missing_fields'] == [] and quiz['message'] is None and len(quiz['rubric_version']) == 64
    for q in quiz['questions']:
        assert set(q) == {'id', 'position', 'text', 'options', 'scoring'}
        assert [o['value'] for o in q['options']] == [1, 2, 3, 4, 5]
        assert [o['label'] for o in q['options']] == ['Rất không đồng ý', 'Không đồng ý', 'Trung lập', 'Đồng ý', 'Rất đồng ý']
        assert len(q['scoring']) == 3 and len({s['major_id'] for s in q['scoring']}) == 3
        assert all(set(s) == {'major_id', 'direction', 'reason'} for s in q['scoring'])
    assert {s['direction'] for q in quiz['questions'] for s in q['scoring']} == {'positive', 'negative', 'none'}
    catalog = client.get(BASE + '/catalog/majors', params={'page_size': 1}).json()
    assert set(catalog) == {'items', 'total', 'page', 'page_size'} and catalog['total'] == 3
    major = catalog['items'][0]
    assert set(major) == {'id', 'code', 'name', 'campus', 'description', 'career_groups', 'sources'}
    assert set(major['sources'][0]) == {'document_id', 'title', 'url', 'source_name', 'page'}
    assert client.get(BASE + '/catalog/majors', params={'campus': 'absent'}).json()['items'] == []


@pytest.mark.parametrize('case,values,scores,status,order', CASES)
def test_m1_api(quiz_client, case, values, scores, status, order):
    response = quiz_client.post(BASE + '/recommendations', json=request_body(quiz_client, values))
    assert response.status_code == 200, response.text
    result = response.json()
    assert set(result) == {'status', 'rubric_version', 'items', 'missing_fields', 'message', 'disclaimer'}
    assert result['status'] == status
    assert [i['major']['code'] for i in result['items']] == order
    assert result['disclaimer'] == 'Kết quả chỉ mang tính tham khảo, không bảo đảm trúng tuyển.'
    assert result['missing_fields'] == [] and result['rubric_version']
    if status == 'ready':
        assert result['message'] is None
        for item in result['items']:
            assert set(item) == {'major', 'fit_score', 'reasons'}
            assert item['fit_score'] == scores[ord(item['major']['code']) - 65]
            assert 1 <= len(item['reasons']) <= 2 and item['major']['sources']
    else:
        assert result['items'] == [] and '3' in result['message']


@pytest.mark.parametrize('bad', ['missing', 'duplicate', 'unknown', 'bool', 'float', 'string', 'low', 'high',
                                 'extra', 'score', 'answer_extra', 'bad_uuid', 'empty_version'])
def test_invalid_answers_422(quiz_client, bad):
    body = request_body(quiz_client)
    if bad == 'missing': body['answers'].pop()
    elif bad == 'duplicate': body['answers'][1] = deepcopy(body['answers'][0])
    elif bad == 'unknown': body['answers'][0]['question_id'] = str(uuid4())
    elif bad == 'extra': body['campus'] = 'HN'
    elif bad == 'score': body['admission_score'] = 28
    elif bad == 'answer_extra': body['answers'][0]['weight'] = 3
    elif bad == 'bad_uuid': body['answers'][0]['question_id'] = 'bad'
    elif bad == 'empty_version': body['rubric_version'] = ''
    else: body['answers'][0]['value'] = {'bool': True, 'float': 3.0, 'string': '3', 'low': 0, 'high': 6}[bad]
    response = quiz_client.post(BASE + '/recommendations', json=body)
    assert response.status_code == 422, response.text
    assert response.json()['error']['code'] == 'INVALID_QUIZ_ANSWERS'


def test_stale_rubric_409_and_auth_on_public_routes(quiz_client):
    body = request_body(quiz_client)
    body['rubric_version'] = 'stale'
    response = quiz_client.post(BASE + '/recommendations', json=body)
    assert response.status_code == 409 and response.json()['error']['code'] == 'RUBRIC_CHANGED'
    for route in ['/quiz', '/catalog/majors', '/recommendations']:
        response = (quiz_client.post(BASE + route, json=body, headers={'Authorization': 'Bearer bad'})
                    if route == '/recommendations' else quiz_client.get(BASE + route, headers={'Authorization': 'Bearer bad'}))
        assert response.status_code == 401


@pytest.mark.parametrize('params', [{'page': 0}, {'page_size': 101}, {'page_size': 0}])
def test_catalogue_pagination_validation(quiz_client, params):
    assert quiz_client.get(BASE + '/catalog/majors', params=params).status_code == 422
