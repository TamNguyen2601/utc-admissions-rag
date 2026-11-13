"""T035–T037: history REST contract and private ownership, synthetic data only."""
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from tests.chat_support import chat_client  # noqa: F401
from tests.history_support import BASE, accounts, create, send, messages  # noqa: F401


def test_crud_pair_order_pagination_and_cascade(chat_client, accounts):
    client, auth = chat_client, accounts['alice']
    conversation_id = create(client, auth)
    url = f'{BASE}/{conversation_id}'
    conversation = client.get(url, headers=auth).json()
    assert set(conversation) == {'id', 'title', 'created_at', 'updated_at'}
    assert conversation['title'] == 'Hội thoại mới'
    assert conversation['created_at'].endswith('Z')
    for message in ('  Xin chào  ', 'Cảm ơn'):
        response = send(client, auth, conversation_id, message)
        assert response.status_code == 200, response.text
        data = response.json()
        assert set(data) == {'user_message_id', 'assistant_message_id', 'reply'}
        assert data['reply']['status'] == 'social'
    history = messages(client, auth, conversation_id)
    assert set(history) == {'items', 'total', 'page', 'page_size'}
    assert history['total'] == 4
    assert [m['seq'] for m in history['items']] == [1, 2, 3, 4]
    assert [m['sender'] for m in history['items']] == ['user', 'assistant'] * 2
    assert history['items'][0]['content'] == 'Xin chào'
    for item in history['items']:
        assert set(item) == {'id', 'seq', 'sender', 'content', 'reply_status', 'citations', 'created_at'}
        assert item['citations'] == []
        assert item['reply_status'] == ('social' if item['sender'] == 'assistant' else None)
    assert history['items'][2]['id'] == data['user_message_id']
    assert history['items'][3]['id'] == data['assistant_message_id']
    page = messages(client, auth, conversation_id, page=2, page_size=2)
    assert [m['seq'] for m in page['items']] == [3, 4]
    assert messages(client, auth, conversation_id, page=4)['items'] == []
    renamed = client.patch(url, headers=auth, json={'title': '  Đổi tên  '})
    assert renamed.status_code == 200 and renamed.json()['title'] == 'Đổi tên'
    assert renamed.json()['updated_at'] > conversation['updated_at']
    listed = client.get(BASE, headers=auth).json()
    assert listed['total'] == 1 and listed['items'][0] == renamed.json()
    deleted = client.delete(url, headers=auth)
    assert deleted.status_code == 204 and deleted.content == b''
    assert client.get(url, headers=auth).status_code == 404
    assert client.get(BASE, headers=auth).json()['total'] == 0
    from app.models.conversation import Message
    with client.app.state.database.session() as db:
        assert db.scalar(select(func.count()).select_from(Message)) == 0


@pytest.mark.parametrize('who', ['bob', 'admin'])
def test_other_user_and_admin_cannot_access_any_owner_endpoint(chat_client, accounts, who):
    client = chat_client
    conversation_id = create(client, accounts['alice'], title='PRIVATE TITLE')
    assert send(client, accounts['alice'], conversation_id, 'PRIVATE MESSAGE').status_code == 200
    auth, url = accounts[who], f'{BASE}/{conversation_id}'
    assert client.get(BASE, headers=auth).json()['total'] == 0
    for method, path, payload in (
        ('GET', url, None), ('GET', url + '/messages', None),
        ('POST', url + '/messages', {'message': 'Xin chào'}),
        ('PATCH', url, {'title': 'stolen'}), ('DELETE', url, None),
    ):
        response = client.request(method, path, headers=auth, **({'json': payload} if payload else {}))
        assert response.status_code == 404
        assert 'PRIVATE' not in response.text
    assert messages(client, accounts['alice'], conversation_id)['total'] == 2
    own = create(client, auth)
    assert send(client, auth, own).status_code == 200


@pytest.mark.parametrize('title,valid', [('', False), ('   ', False), ('x', True),
    ('x' * 100, True), ('x' * 101, False), (None, False), (123, False)])
def test_title_boundaries_create_and_rename(chat_client, accounts, title, valid):
    auth = accounts['alice']
    expected = 201 if valid else 422
    assert chat_client.post(BASE, headers=auth, json={'title': title}).status_code == expected
    conversation_id = create(chat_client, auth)
    response = chat_client.patch(f'{BASE}/{conversation_id}', headers=auth, json={'title': title})
    assert response.status_code == (200 if valid else 422)


def test_protected_endpoints_and_revoked_token(chat_client, accounts):
    client, auth = chat_client, accounts['alice']
    conversation_id = create(client, auth)
    assert client.post('/api/v1/auth/logout', headers=auth).status_code == 204
    for headers in ({}, {'Authorization': 'Bearer invalid'}, auth):
        for method, path, payload in (
            ('POST', BASE, {}), ('GET', BASE, None), ('GET', f'{BASE}/{conversation_id}', None),
            ('GET', f'{BASE}/{conversation_id}/messages', None),
            ('POST', f'{BASE}/{conversation_id}/messages', {'message': 'Xin chào'}),
            ('PATCH', f'{BASE}/{conversation_id}', {'title': 'changed'}),
            ('DELETE', f'{BASE}/{conversation_id}', None),
        ):
            response = client.request(method, path, headers=headers,
                                      **({'json': payload} if payload is not None else {}))
            assert response.status_code == 401
            assert response.headers['www-authenticate'] == 'Bearer'


def test_validation_and_unknown_ids(chat_client, accounts):
    client, auth = chat_client, accounts['alice']
    conversation_id = create(client, auth)
    url = f'{BASE}/{conversation_id}'
    for payload in ({'message': ''}, {'message': 'x' * 4001}, {'message': 'hi', 'turns': []},
                    {'message': 'hi', 'conversation_id': conversation_id}, {'message': 123}):
        assert client.post(url + '/messages', headers=auth, json=payload).status_code == 422
    assert client.post(BASE, headers=auth, json={'user_id': str(uuid4())}).status_code == 422
    assert client.patch(url, headers=auth, json={}).status_code == 422
    for query in ({'page': 0}, {'page_size': 0}, {'page_size': 101}):
        assert client.get(BASE, headers=auth, params=query).status_code == 422
        assert client.get(url + '/messages', headers=auth, params=query).status_code == 422
    unknown = f'{BASE}/{uuid4()}'
    assert client.get(unknown, headers=auth).status_code == 404
    assert client.get(unknown + '/messages', headers=auth).status_code == 404
    assert client.post(unknown + '/messages', headers=auth, json={'message': 'hi'}).status_code == 404
    assert client.patch(unknown, headers=auth, json={'title': 'hi'}).status_code == 404
    assert client.delete(unknown, headers=auth).status_code == 404
    assert messages(client, auth, conversation_id)['total'] == 0
