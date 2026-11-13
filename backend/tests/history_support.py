"""Synthetic accounts/history in temporary SQLite; no official UTC data."""
import pytest

from app.models.identity import Role, User
from tests.chat_support import chat_client  # noqa: F401

BASE = '/api/v1/conversations'


@pytest.fixture
def accounts(chat_client):
    result = {}
    for name in ('alice', 'bob', 'admin'):
        credentials = dict(email=f'{name}@example.test', password='SYNTHETIC-password')
        response = chat_client.post('/api/v1/auth/register', json=credentials)
        assert response.status_code == 201
        if name == 'admin':
            with chat_client.app.state.database.session() as db:
                db.get(User, response.json()['id']).role = Role.ADMIN
                db.commit()
        login = chat_client.post('/api/v1/auth/login', json=credentials).json()
        result[name] = {'Authorization': f"Bearer {login['access_token']}"}
    return result


def create(client, headers, **payload):
    response = client.post(BASE, headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()['id']


def send(client, headers, conversation_id, message='Xin chào', **extra):
    return client.post(f'{BASE}/{conversation_id}/messages', headers=headers,
                       json=dict(message=message, **extra))


def messages(client, headers, conversation_id, **params):
    response = client.get(f'{BASE}/{conversation_id}/messages', headers=headers, params=params)
    assert response.status_code == 200, response.text
    return response.json()
