import numpy as np
import pytest
from fastapi import HTTPException

from app.services.chunking import chunk_pages
from app.services.embedding import EmbeddingService, vector_blob, read_vector
from tests.knowledge_support import Model, Tokenizer


def test_chunk_boundaries_overlap_and_metadata():
    text = ' '.join(f't{i}' for i in range(800))
    pages = [dict(page=2, text=text, section=None, extraction_kind='ocr', numeric_eligible=False),
             dict(page=3, text='Header: engineering | score: 42', section='Conditions')]
    chunks = chunk_pages(pages, Tokenizer())
    assert [len(c['text'].split()) for c in chunks[:3]] == [320, 320, 256]
    assert chunks[0]['text'].split()[-48:] == chunks[1]['text'].split()[:48]
    assert chunks[2]['page'] == 2 and not chunks[2]['numeric_eligible']
    assert chunks[3]['page'] == 3 and chunks[3]['section'] == 'Conditions'
    assert 'Header:' in chunks[3]['text']
    assert all(len(Tokenizer()('passage: ' + c['text'])['input_ids']) <= 512 for c in chunks)


def test_prefix_budget_norm_dimension_roundtrip(settings):
    model = Model()
    encoder = EmbeddingService(settings, model=model)
    vectors = encoder.passages(['engineering', 'medicine'])
    assert model.encode.call_args.args[0] == ['passage: engineering', 'passage: medicine']
    encoder.query('engineering')
    assert model.encode.call_args.args[0] == ['query: engineering']
    assert vectors.dtype == np.dtype('<f4') and vectors.shape == (2, 384)
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1)
    assert np.array_equal(read_vector(vector_blob(vectors[0])), vectors[0])
    encoder.query(' '.join(['x'] * 509))
    before = model.encode.call_count
    with pytest.raises(HTTPException) as error:
        encoder.query(' '.join(['x'] * 510))
    assert error.value.status_code == 422 and model.encode.call_count == before


@pytest.mark.parametrize('value', [np.zeros(384), np.ones(383), np.full(384, np.nan), np.full(384, np.inf)])
def test_invalid_vectors(value):
    with pytest.raises(ValueError): vector_blob(value)
    with pytest.raises(ValueError): read_vector(b'bad')


@pytest.mark.parametrize('value', [np.zeros((1, 384)), np.ones((1, 383)),
                                 np.full((1, 384), np.nan), np.full((1, 384), np.inf)])
def test_bad_encoder_outputs_are_rejected(settings, value):
    model = Model(); model.encode.side_effect = None; model.encode.return_value = value
    with pytest.raises(ValueError): EmbeddingService(settings, model=model).query('engineering')


def test_singleton_and_concurrent_encoding_are_serialized(settings):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Lock
    import time
    assert EmbeddingService.local(settings) is EmbeddingService.local(settings)
    model = Model()
    encoder = EmbeddingService(settings, model=model)
    counter = dict(active=0, max_active=0)
    counter_lock = Lock()
    def work(texts, **kwargs):
        with counter_lock:
            counter['active'] += 1
            counter['max_active'] = max(counter['max_active'], counter['active'])
        try:
            time.sleep(.01)
            return model._encode(texts, **kwargs)
        finally:
            with counter_lock: counter['active'] -= 1
    model.encode.side_effect = work
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(encoder.query, ['engineering'] * 8))
    assert len(results) == 8 and counter['max_active'] == 1


def test_unsafe_table_row_and_section_budget_rejected():
    for pages in [[dict(text=('Header: value | ' * 200), page=1)],
                  [dict(text='body', page=1, section='heading ' * 300)]]:
        with pytest.raises(ValueError): chunk_pages(pages, Tokenizer())


def test_table_headers_keep_their_preceding_conditions():
    chunks = chunk_pages([dict(page=3, section='SYNTHETIC', text=(
        'Applies to A only\nProgram: A | Score: 25\nProgram: A2 | Score: 26\n'
        'Applies to B only\nProgram: B | Score: 30'))], Tokenizer())
    assert len(chunks) == 3
    assert all('Applies to A only' in c['text'] and 'Applies to B' not in c['text'] for c in chunks[:2])
    assert 'Applies to B only' in chunks[2]['text'] and 'Applies to A' not in chunks[2]['text']


def test_query_too_long_rest_envelope(application, settings):
    from fastapi.testclient import TestClient
    encoder = EmbeddingService(settings, model=Model())
    @application.get('/synthetic-query-budget')
    def query():
        encoder.query('x ' * 510)
    with TestClient(application) as client:
        response = client.get('/synthetic-query-budget')
        assert response.status_code == 422
        assert response.json()['error']['code'] == 'QUERY_TOO_LONG'
