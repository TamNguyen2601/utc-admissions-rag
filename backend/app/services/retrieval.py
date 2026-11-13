"""NumPy cosine over current SQLite vectors; no stale in-memory vector cache."""
from fastapi import HTTPException
import numpy as np
from sqlalchemy import select

from app.models.knowledge import DataSource, Document, DocumentChunk, DocumentOrigin
from app.services.embedding import read_vector
from app.services.sources import require_usable, validate_source_url

CONTEXT_FIELDS = ('year', 'campus', 'major_code', 'method')


def usable_origins(db, document_id):
    rows = db.execute(select(DocumentOrigin, DataSource).join(DataSource)
        .where(DocumentOrigin.document_id == document_id, DocumentOrigin.active.is_(True),
               DataSource.enabled.is_(True), DataSource.permission_status == 'allowed')
        .order_by(DocumentOrigin.retrieved_at, DocumentOrigin.id)).all()
    result = []
    for origin, source in rows:
        try:
            require_usable(source)
            if origin.canonical_url.startswith('https:'):
                validate_source_url(source, origin.canonical_url)
            elif not (origin.origin_kind == 'upload' and origin.canonical_url == f'urn:upload:{origin.id}'):
                continue
        except HTTPException:
            continue
        result.append((origin, source))
    return result


class RetrievalService:
    def __init__(self, database, encoder, profile, publish_lock, min_similarity=.75):
        if not np.isfinite(min_similarity) or not -1 <= min_similarity <= 1:
            raise ValueError('INVALID_THRESHOLD')
        if encoder is not None and any(profile.get(k) != v for k, v in encoder.profile.items()):
            raise ValueError('ENCODER_PROFILE_MISMATCH')
        self.database, self.encoder, self.profile = database, encoder, dict(profile)
        self.publish_lock, self.min_similarity = publish_lock, min_similarity

    def _current(self, db, doc):
        return (doc is not None and doc.enabled and doc.state == 'ready'
                and doc.index_profile == self.profile and bool(doc.content_hash))

    @staticmethod
    def _hit(doc, chunk, origins, score):
        origin, source = origins[0]
        return dict(document_id=doc.id, chunk_id=chunk.id, content_hash=doc.content_hash,
                    title=doc.title, url=origin.canonical_url, source_name=source.name,
                    year=chunk.year, campus=chunk.campus, major_code=chunk.major_code,
                    method=chunk.method, page=chunk.page, section=chunk.section,
                    text=chunk.text, extraction_kind=chunk.extraction_kind,
                    numeric_eligible=chunk.numeric_eligible, similarity=score, available=True)

    def search(self, query, context=None):
        context = context or {}
        if set(context) - set(CONTEXT_FIELDS):
            raise ValueError('INVALID_CONTEXT')
        # Query encoding can be slow; never hold publish_lock or a DB transaction.
        vector = self.encoder.query(query)
        with self.publish_lock, self.database.session() as db:
            statement = select(DocumentChunk, Document).join(Document).where(
                Document.enabled.is_(True), Document.state == 'ready')
            for key, value in context.items():
                if value is not None:
                    statement = statement.where(getattr(DocumentChunk, key) == value,
                                                getattr(Document, key) == value)
            candidates, vectors, origins_by_doc = [], [], {}
            for chunk, doc in db.execute(statement.order_by(DocumentChunk.id)):
                if not self._current(db, doc):
                    continue
                if doc.id not in origins_by_doc:
                    origins_by_doc[doc.id] = usable_origins(db, doc.id)
                if not origins_by_doc[doc.id]:
                    continue
                try:
                    embedding = read_vector(chunk.embedding)
                except ValueError:
                    continue
                candidates.append((chunk, doc))
                vectors.append(embedding)
            if not vectors:
                return []
            # All vectors are finite unit float32. Dot product is cosine.
            scores = np.clip(np.stack(vectors) @ vector, -1, 1)
            order = np.argsort(-scores, kind='stable')
            hits = []
            for index in order:
                if float(scores[index]) < self.min_similarity:
                    break
                chunk, doc = candidates[index]
                hits.append(self._hit(doc, chunk, origins_by_doc[doc.id], float(scores[index])))
                if len(hits) == 5:
                    break
            return hits

    def available(self, citation):
        """Recheck a snapshot before reuse; caller must recheck again before final use."""
        with self.publish_lock, self.database.session() as db:
            return self.available_in_session(db, citation)

    def available_in_session(self, db, citation):
        """Caller holds publish_lock: allows atomic final validation without recursive Lock."""
        doc = db.get(Document, citation.get('document_id'))
        chunk = db.get(DocumentChunk, citation.get('chunk_id'))
        if (not self._current(db, doc) or chunk is None or chunk.document_id != doc.id
                or citation.get('content_hash') != doc.content_hash):
            return False
        try:
            read_vector(chunk.embedding)
        except ValueError:
            return False
        origins = usable_origins(db, doc.id)
        return bool(origins) and (not citation.get('url') or any(
            origin.canonical_url == citation['url']
            and source.name == citation.get('source_name', source.name) for origin, source in origins))

    def has_knowledge(self):
        """Usable corpus presence, independent of this question's score/context filters."""
        with self.publish_lock, self.database.session() as db:
            documents = db.scalars(select(Document).where(Document.enabled.is_(True), Document.state == 'ready'))
            for doc in documents:
                if not self._current(db, doc) or not usable_origins(db, doc.id):
                    continue
                for chunk in db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == doc.id)):
                    try:
                        read_vector(chunk.embedding)
                        return True
                    except ValueError:
                        continue
            return False

    def source(self, identity, page=None):
        with self.publish_lock, self.database.session() as db:
            doc = db.get(Document, identity)
            if doc is None:
                raise HTTPException(404)
            origins = usable_origins(db, identity)
            if not self._current(db, doc) or not origins:
                raise HTTPException(410)
            chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == identity)
                                .order_by(DocumentChunk.ordinal)).all()
            if not chunks:
                raise HTTPException(410)
            try:
                for chunk in chunks:
                    read_vector(chunk.embedding)
            except ValueError:
                raise HTTPException(410) from None
            return dict(id=doc.id, title=doc.title,
                origins=[dict(url=origin.canonical_url, source_name=source.name) for origin, source in origins],
                excerpts=[dict(chunk_id=c.id, page=c.page, section=c.section, text=c.text)
                          for c in chunks if page is None or c.page == page], available=True)
