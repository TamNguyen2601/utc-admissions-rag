"""Single async owner of a chat request; CPU workers only return evidence data."""
import asyncio

from fastapi import HTTPException

from app.db.base import utc_now
from app.models.identity import AuthSession, User
from app.schemas.chat import Reply
from app.services.evidence import citations, gate, validate_output
from app.services.gemini import ChatError
from app.services.scope import classify


MESSAGES = {
    'social': 'Xin chào! Cảm ơn bạn đã trò chuyện. Tôi có thể hỗ trợ tuyển sinh UTC và nghề nghiệp liên quan. Hẹn gặp lại bạn!',
    'out_of_scope': 'Tôi chỉ hỗ trợ tuyển sinh UTC và nghề nghiệp liên quan đến ngành đào tạo UTC. Bạn có thể hỏi về những chủ đề này.',
    'needs_clarification': 'Bạn vui lòng làm rõ chủ thể UTC, năm, cơ sở, ngành hoặc phương thức liên quan để tôi tra đúng tài liệu.',
    'data_missing': 'Cơ sở tri thức local chưa có dữ liệu hợp lệ để trả lời câu hỏi này.',
    'insufficient_evidence': 'Chưa có đủ chứng cứ hợp lệ để trả lời. Bạn vui lòng bổ sung ngữ cảnh hoặc tài liệu có nguồn rõ ràng.',
    'conflicting_sources': 'Các nguồn cùng ngữ cảnh có số liệu mâu thuẫn. Chưa thể khẳng định số liệu nào đúng; bạn cần kiểm tra lại các nguồn.',
}


class ChatService:
    def __init__(self, retrieval, gemini, settings, *, catalogue_resolver=None):
        self.retrieval, self.gemini, self.settings = retrieval, gemini, settings
        self.catalogue_resolver = catalogue_resolver

    @staticmethod
    def check_deadline(expires_at):
        if asyncio.get_running_loop().time() >= expires_at:
            raise ChatError(504, 'REQUEST_DEADLINE_EXCEEDED')

    def _retrieve(self, query, context):
        # A thread owns its own Sessions. It cannot finalize, send or persist messages.
        hits = self.retrieval.search(query, context.model_dump())
        hits = [hit for hit in hits if self.retrieval.available(hit)]
        return hits, self.retrieval.has_knowledge()

    async def _finalize(self, reply, selected, identity, expires_at):
        # Never block the event loop on a held threading.Lock or leave a late lock worker.
        lock = self.retrieval.publish_lock
        while not lock.acquire(blocking=False):
            await asyncio.sleep(.005)
        try:
            self.check_deadline(expires_at)
            with self.retrieval.database.session() as db:
                if identity is not None:
                    session = db.get(AuthSession, identity.session.id)
                    user = db.get(User, identity.user.id)
                    if (session is None or user is None or not user.active
                            or session.user_id != user.id or session.revoked_at is not None
                            or session.expires_at <= utc_now()):
                        raise HTTPException(401)
                if any(not self.retrieval.available_in_session(db, hit) for hit in selected):
                    reply = reply.model_copy(update={'status': 'insufficient_evidence',
                        'text': MESSAGES['insufficient_evidence'], 'citations': []})
                # T035+ will add account history here. Guest never writes to DB.
                self.check_deadline(expires_at)
                return reply
        finally:
            lock.release()

    async def reply(self, payload, request_id, identity=None):
        expires_at = asyncio.get_running_loop().time() + self.settings.chat_deadline_seconds
        try:
            async with asyncio.timeout_at(expires_at):
                scope = classify(payload, self.catalogue_resolver)
                status, selected, missing, text = scope.status, [], scope.missing_fields, ''
                if scope.status == 'retrieve':
                    hits, present = await asyncio.to_thread(self._retrieve, scope.query, scope.context)
                    self.check_deadline(expires_at)
                    decision = gate(scope.query, scope.context, hits, has_knowledge=present)
                    status, selected, missing, text = decision.status, decision.hits, decision.missing_fields, decision.text
                    if status == 'generate':
                        evidence = {f'E{i}': hit for i, hit in enumerate(selected, 1)}
                        raw = await self.gemini.generate(scope.query, evidence, expires_at)
                        self.check_deadline(expires_at)
                        output = validate_output(raw, evidence)
                        if output is None:
                            status, selected = 'insufficient_evidence', []
                        else:
                            status, text = 'answered', output.answer
                            selected = [evidence[key] for key in output.evidence_ids]
                if status not in {'answered', 'conflicting_sources'}:
                    selected = []
                text = text or MESSAGES[status]
                if scope.mixed and status == 'answered':
                    text += '\nTôi chỉ trả lời phần liên quan UTC; phần ngoài phạm vi chưa được hỗ trợ.'
                reply = Reply(status=status, text=text, citations=citations(selected), context=scope.context,
                              missing_fields=missing, request_id=request_id)
                return await self._finalize(reply, selected, identity, expires_at)
        except TimeoutError:
            raise ChatError(504, 'REQUEST_DEADLINE_EXCEEDED') from None
