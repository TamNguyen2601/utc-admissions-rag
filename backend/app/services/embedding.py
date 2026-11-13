"""Pinned, cache-only E5 CPU embedding. No embedding API or implicit download."""
from threading import Lock

from fastapi import HTTPException
import numpy as np
from sqlalchemy import select

from app.models.knowledge import DocumentChunk
from app.services.chunking import CHUNK_SIZE, OVERLAP, MAX_TOKENS, chunk_pages, token_count


class QueryTooLong(HTTPException):
    def __init__(self):
        super().__init__(422)


def read_vector(blob):
    if not isinstance(blob, bytes) or len(blob) != 1536:
        raise ValueError('INVALID_VECTOR')
    vector = np.frombuffer(blob, dtype='<f4')
    if not np.isfinite(vector).all() or not np.isclose(np.linalg.norm(vector), 1, atol=1e-5):
        raise ValueError('INVALID_VECTOR')
    return vector


def vector_blob(vector):
    vector = np.asarray(vector, dtype='<f4')
    if vector.shape != (384,):
        raise ValueError('INVALID_DIMENSION')
    blob = vector.tobytes()
    read_vector(blob)
    return blob


class EmbeddingService:
    _instances = {}
    _instances_lock = Lock()

    @classmethod
    def local(cls, settings):
        key = (settings.embedding_model, settings.embedding_revision, str(settings.model_cache_dir))
        with cls._instances_lock:
            if key not in cls._instances:
                cls._instances[key] = cls(settings)
            return cls._instances[key]

    def __init__(self, settings, *, model=None):
        self._model = model
        self._model_name, self._revision = settings.embedding_model, settings.embedding_revision
        self._cache_dir = settings.model_cache_dir
        self._load_lock, self._encode_lock = Lock(), Lock()

    @property
    def ready(self):
        return self._model is not None

    @property
    def model(self):
        with self._load_lock:
            if self._model is None:
                from huggingface_hub import snapshot_download
                from sentence_transformers import SentenceTransformer
                snapshot = snapshot_download(self._model_name,
                    revision=self._revision, cache_dir=self._cache_dir,
                    local_files_only=True, allow_patterns=['*.json', '*.safetensors', '*.model'],
                    ignore_patterns=['onnx/*', 'openvino/*'])
                model = SentenceTransformer(snapshot, device='cpu', local_files_only=True,
                                            trust_remote_code=False)
                if model.device.type != 'cpu' or model.get_embedding_dimension() != 384:
                    raise ValueError('INVALID_MODEL')
                model.max_seq_length = MAX_TOKENS
                self._model = model
            return self._model

    @property
    def tokenizer(self):
        return self.model.tokenizer

    @property
    def profile(self):
        return dict(model=self._model_name, revision=self._revision,
                    dim=384, normalization='L2', dtype='<f4', device='cpu',
                    passage_prefix='passage:', query_prefix='query:',
                    chunk_size=CHUNK_SIZE, overlap=OVERLAP, max_tokens=MAX_TOKENS,
                    chunking_version='page-section-offsets-1')

    def _encode(self, values, prefix):
        texts = [prefix + ' ' + value for value in values]
        with self._encode_lock:
            # Fast tokenizers alter their padding/truncation state internally;
            # serialize budget checks and tokenization with model.encode too.
            if any(token_count(self.tokenizer, text) > MAX_TOKENS for text in texts):
                if prefix == 'query:':
                    raise QueryTooLong()
                raise ValueError('PASSAGE_TOO_LONG')
            vectors = np.asarray(self.model.encode(texts, device='cpu', batch_size=16,
                normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False), dtype='<f4')
        if vectors.shape != (len(texts), 384) or not np.isfinite(vectors).all():
            raise ValueError('INVALID_VECTOR')
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        if np.any(norms <= 0):
            raise ValueError('INVALID_VECTOR')
        vectors = np.asarray(vectors / norms, dtype='<f4')
        for vector in vectors:
            vector_blob(vector)
        return vectors

    def passages(self, texts):
        return self._encode(texts, 'passage:')

    def query(self, text):
        return self._encode([text], 'query:')[0]

    def chunks(self, pages):
        with self._encode_lock:
            return chunk_pages(pages, self.tokenizer)


class Indexer:
    def __init__(self, database, encoder):
        self.database, self.encoder = database, encoder

    @property
    def profile(self):
        return self.encoder.profile

    def index(self, text, metadata):
        # Real extraction always supplies pages; fallback is for plain input only.
        pages = metadata.get('pages') or [dict(text=text, page=None)]
        chunks = self.encoder.chunks(pages)
        vectors = self.encoder.passages([chunk['text'] for chunk in chunks])
        for chunk, vector in zip(chunks, vectors, strict=True):
            chunk.update(embedding=vector_blob(vector), embedding_dim=384,
                **{key: metadata.get(key) for key in ('year', 'campus', 'major_code', 'method')})
        return chunks

    def usable(self, document):
        if not document.index_profile or any(document.index_profile.get(k) != v for k, v in self.profile.items()):
            return False
        with self.database.session() as db:
            chunks = db.scalars(select(DocumentChunk).where(DocumentChunk.document_id == document.id)).all()
            try:
                for chunk in chunks:
                    read_vector(chunk.embedding)
            except ValueError:
                return False
            return bool(chunks)
