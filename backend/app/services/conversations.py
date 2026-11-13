"""Owner-only history and a short in-process guard for the single-worker backend."""
from contextlib import contextmanager
from threading import Lock
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, func, select

from app.db.base import utc_now
from app.models.conversation import Conversation, Message
from app.schemas.chat import Turn
from app.schemas.conversation import ConversationResponse, MessageResponse
from app.services.gemini import ChatError


def conversation_response(row):
    return ConversationResponse(id=row.id, title=row.title,
                                created_at=row.created_at, updated_at=row.updated_at)


class ConversationService:
    def __init__(self, database, retrieval):
        self.database, self.retrieval = database, retrieval
        self._mutex, self._active = Lock(), set()

    @staticmethod
    def owned(db, conversation_id, user_id):
        # Filter before loading the conversation, including for ADMIN.
        row = db.scalar(select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user_id))
        if row is None:
            raise HTTPException(404)
        return row

    @contextmanager
    def active(self, conversation_id, user_id):
        with self.database.session() as db:
            self.owned(db, conversation_id, user_id)
        with self._mutex:
            if conversation_id in self._active:
                raise ChatError(409, 'CONVERSATION_BUSY')
            self._active.add(conversation_id)
        try:
            yield
        finally:
            with self._mutex:
                self._active.remove(conversation_id)

    def create(self, user_id, title):
        with self.database.session() as db:
            row = Conversation(user_id=user_id, title=title)
            db.add(row)
            db.commit()
            return conversation_response(row)

    def list(self, user_id, page, page_size):
        with self.database.session() as db:
            condition = Conversation.user_id == user_id
            total = db.scalar(select(func.count()).select_from(Conversation).where(condition))
            rows = db.scalars(select(Conversation).where(condition)
                .order_by(Conversation.updated_at.desc(), Conversation.id)
                .offset((page - 1) * page_size).limit(page_size))
            return dict(items=[conversation_response(row) for row in rows], total=total,
                        page=page, page_size=page_size)

    def open(self, conversation_id, user_id):
        with self.database.session() as db:
            return conversation_response(self.owned(db, conversation_id, user_id))

    def rename(self, conversation_id, user_id, title):
        with self.active(conversation_id, user_id), self.database.session() as db:
            row = self.owned(db, conversation_id, user_id)
            row.title, row.updated_at = title, utc_now()
            db.commit()
            return conversation_response(row)

    def delete(self, conversation_id, user_id):
        with self.active(conversation_id, user_id), self.database.session() as db:
            self.owned(db, conversation_id, user_id)
            db.execute(delete(Conversation).where(Conversation.id == conversation_id,
                                                 Conversation.user_id == user_id))
            db.commit()

    def messages(self, conversation_id, user_id, page, page_size):
        with self.retrieval.publish_lock, self.database.session() as db:
            self.owned(db, conversation_id, user_id)
            condition = Message.conversation_id == conversation_id
            total = db.scalar(select(func.count()).select_from(Message).where(condition))
            rows = db.scalars(select(Message).where(condition).order_by(Message.seq)
                .offset((page - 1) * page_size).limit(page_size))
            items = []
            for row in rows:
                citations = [snapshot | {'available': self.retrieval.available_in_session(db, snapshot)}
                             for snapshot in row.citations_json]
                items.append(MessageResponse(id=row.id, seq=row.seq, sender=row.sender,
                    content=row.content, reply_status=row.reply_status,
                    citations=citations, created_at=row.created_at))
            return dict(items=items, total=total, page=page, page_size=page_size)

    def turns(self, conversation_id, user_id):
        with self.database.session() as db:
            self.owned(db, conversation_id, user_id)
            rows = db.scalars(select(Message).where(Message.conversation_id == conversation_id)
                              .order_by(Message.seq.desc()).limit(10))
            turns, size = [], 0
            for row in rows:
                # Assistant output may exceed one turn's input limit. Keep the full
                # stored message; only its contextual excerpt is bounded here.
                text = row.content[:4000]
                if size + len(text) > 16000:
                    break
                turns.append(Turn(sender=row.sender, text=text))
                size += len(text)
            # Only text context, never old citations or saved evidence.
            return list(reversed(turns))

    def add_pair(self, db, conversation_id, user_id, message, reply):
        """Stage only. The live async chat handler alone may check the deadline and commit."""
        row = self.owned(db, conversation_id, user_id)
        now, turn_id = utc_now(), str(uuid4())
        user = Message(conversation_id=row.id, seq=row.next_seq, turn_id=turn_id,
                       sender='user', content=message, reply_status=None,
                       citations_json=[], created_at=now)
        snapshots = [c.model_dump(mode='json', exclude={'available'}) for c in reply.citations]
        assistant = Message(conversation_id=row.id, seq=row.next_seq + 1, turn_id=turn_id,
                            sender='assistant', content=reply.text, reply_status=reply.status,
                            citations_json=snapshots, created_at=now)
        row.next_seq += 2
        row.updated_at = now
        db.add_all([user, assistant])
        db.flush()
        return user.id, assistant.id
