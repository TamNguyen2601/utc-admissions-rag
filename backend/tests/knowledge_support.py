"""SYNTHETIC encoder/tokenizer; real chunk/index/retrieval and SQLite services."""
import re
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from app.services.embedding import EmbeddingService, Indexer
from tests.ingestion_support import ingestion, ingest


class Tokenizer:
    def __call__(self, text, add_special_tokens=True, return_offsets_mapping=False, **kwargs):
        offsets = [(m.start(), m.end()) for m in re.finditer(r'\S+', text)]
        result = {"input_ids": list(range(len(offsets) + (2 if add_special_tokens else 0)))}
        if return_offsets_mapping:
            result['offset_mapping'] = offsets
        return result


class Model:
    tokenizer = Tokenizer()
    device = SimpleNamespace(type='cpu')

    def __init__(self):
        self.encode = Mock(side_effect=self._encode)

    def _encode(self, texts, **kwargs):
        vectors = np.zeros((len(texts), 384), dtype=np.float32)
        for i, text in enumerate(texts):
            vectors[i, 0] = 1
            vectors[i, 1] = text.count('engineering')
            vectors[i, 2] = text.count('medicine')
        return vectors


def real_indexer(ingestion, settings):
    source, service, coordinator = ingestion
    encoder = EmbeddingService(settings, model=Model())
    service.indexer = Indexer(service.database, encoder)
    return source, service, coordinator
