"""T035: owner filters, DB constraints, turn pairing and transaction rollback."""
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models.conversation import Conversation, Message
from app.models.identity import Role, User
from app.schemas.chat import Context, Reply
from app.services.conversations import ConversationService


@pytest.fixture
def history(database):
    database.initialize()
    with database.session() as db:
        alice = User(email_normalized='alice@example.test', password_hash='FIXTURE HASH')
        admin = User(email_normalized='admin@example.test', password_hash='FIXTURE HASH', role=Role.ADMIN)
        db.add_all([alice, admin])
        db.commit()
    return ConversationService(database, None), alice.id, admin.id


def social(text='Xin chào'):
    return Reply(status='social', text=text, context=Context(), request_id=str(uuid4()))


def test_owner_filter_sequence_pair_and_delete_cascade(history):
    service, alice, admin = history
    conversation_id = str(service.create(alice, 'Hội thoại mới').id)
    with pytest.raises(HTTPException) as error:
        service.open(conversation_id, admin)
    assert error.value.status_code == 404
    for _ in range(2):
        with service.database.session() as db:
            service.add_pair(db, conversation_id, alice, 'Xin chào', social())
            db.commit()
    with service.database.session() as db:
        rows = db.scalars(select(Message).order_by(Message.seq)).all()
        assert [r.seq for r in rows] == [1, 2, 3, 4]
        assert rows[0].turn_id == rows[1].turn_id != rows[2].turn_id == rows[3].turn_id
        assert db.get(Conversation, conversation_id).next_seq == 5
    assert service.rename(conversation_id, alice, 'Tên mới').title == 'Tên mới'
    service.delete(conversation_id, alice)
    with service.database.session() as db:
        assert db.scalar(select(func.count()).select_from(Message)) == 0


def test_uncommitted_pair_and_sequence_are_rolled_back(history):
    service, alice, _ = history
    conversation_id = str(service.create(alice, 'Rollback').id)
    with service.database.session() as db:
        service.add_pair(db, conversation_id, alice, 'Xin chào', social())
        # Leaving the context without the handler's explicit commit must persist nothing.
    with service.database.session() as db:
        assert db.get(Conversation, conversation_id).next_seq == 1
        assert db.scalar(select(func.count()).select_from(Message)) == 0


@pytest.mark.parametrize('change', [
    {'seq': 0}, {'sender': 'system'}, {'sender': 'assistant', 'reply_status': None},
    {'reply_status': 'answered'}, {'sender': 'assistant', 'reply_status': 'error'},
    {'conversation_id': str(uuid4())},
])
def test_message_database_constraints(history, change):
    service, alice, _ = history
    conversation_id = str(service.create(alice, 'Constraints').id)
    with service.database.session() as db, pytest.raises(IntegrityError):
        db.add(Message(**(dict(conversation_id=conversation_id, seq=1, turn_id=str(uuid4()),
                              sender='user', content='GIẢ LẬP', reply_status=None) | change)))
        db.commit()


@pytest.mark.parametrize('duplicate', ['seq', 'turn_id'])
def test_sequence_and_turn_sender_are_unique(history, duplicate):
    service, alice, _ = history
    conversation_id = str(service.create(alice, 'Unique').id)
    turn_id = str(uuid4())
    with service.database.session() as db:
        db.add(Message(conversation_id=conversation_id, seq=1, turn_id=turn_id,
                       sender='user', content='GIẢ LẬP'))
        db.commit()
    with service.database.session() as db, pytest.raises(IntegrityError):
        db.add(Message(conversation_id=conversation_id, seq=1 if duplicate == 'seq' else 3,
                       turn_id=turn_id if duplicate == 'turn_id' else str(uuid4()),
                       sender='user', content='GIẢ LẬP'))
        db.commit()


def test_long_answer_is_saved_in_full_but_context_is_bounded(history):
    service, alice, _ = history
    conversation_id = str(service.create(alice, 'Long answer').id)
    with service.database.session() as db:
        service.add_pair(db, conversation_id, alice, 'Xin chào', social('x' * 18000))
        db.commit()
    turns = service.turns(conversation_id, alice)
    assert len(turns) == 2 and len(turns[-1].text) == 4000
    with service.database.session() as db:
        assert len(db.scalar(select(Message).where(Message.sender == 'assistant')).content) == 18000
