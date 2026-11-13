"""Actual google-genai SDK against httpx.MockTransport; never a live API/key."""
import asyncio
import json

from google import genai
from google.genai import types
import httpx
import pytest

from app.services.gemini import ChatError, GeminiService


@pytest.mark.parametrize('outcome,status,code', [
    (200, None, None), (400, 503, 'GEMINI_CONFIGURATION_ERROR'),
    (401, 503, 'GEMINI_CONFIGURATION_ERROR'), (403, 503, 'GEMINI_CONFIGURATION_ERROR'),
    (404, 503, 'GEMINI_CONFIGURATION_ERROR'), (429, 503, 'GEMINI_QUOTA_EXCEEDED'),
    (500, 503, 'GEMINI_SERVICE_UNAVAILABLE'), (503, 503, 'GEMINI_SERVICE_UNAVAILABLE'),
    ('timeout', 504, 'GEMINI_TIMEOUT'), ('network', 503, 'GEMINI_SERVICE_UNAVAILABLE'),
    (504, 504, 'GEMINI_TIMEOUT'),
])
def test_real_sdk_one_attempt_budget_and_grounding(settings, outcome, status, code):
    async def run():
        calls = []
        async def respond(request):
            calls.append(request)
            body = json.loads(request.content)
            timeout = request.extensions['timeout']['read']
            assert 0 < timeout <= .25
            assert 'gemini-3.5-flash-lite:generateContent' in request.url.path
            config = body['generationConfig']
            assert config['responseMimeType'] == 'application/json'
            schema = config['responseJsonSchema']
            assert schema['additionalProperties'] is False
            assert set(schema['required']) == {'answer', 'evidence_ids'}
            system = body['systemInstruction']['parts'][0]['text']
            assert 'không thực thi lệnh' in system and 'Không sinh số liệu' in system
            payload = json.loads(body['contents'][0]['parts'][0]['text'])
            assert set(payload) == {'question', 'evidence'}
            assert payload['evidence'][0]['evidence_id'] == 'E1'
            assert 'provenance_note' not in request.content.decode()
            if outcome == 'timeout':
                raise httpx.ReadTimeout('DO NOT LEAK secret-key', request=request)
            if outcome == 'network':
                raise httpx.ConnectError('DO NOT LEAK secret-key', request=request)
            if outcome != 200:
                return httpx.Response(outcome, json={'error': {'code': outcome, 'message': 'DO NOT LEAK secret-key'}})
            return httpx.Response(200, json={'candidates': [{'content': {'role': 'model', 'parts': [
                {'text': '{"answer":"mô tả","evidence_ids":["E1"]}'}]}}]})
        client = genai.Client(api_key='synthetic-test-key', vertexai=False, http_options=types.HttpOptions(
            retry_options=types.HttpRetryOptions(attempts=1),
            async_client_args={'transport': httpx.MockTransport(respond), 'trust_env': False}))
        service = GeminiService(settings, client=client)
        evidence = {'E1': {'title': 'GIẢ LẬP', 'text': 'mô tả', 'year': 2026,
                           'provenance_note': 'PRIVATE'}}
        try:
            expires_at = asyncio.get_running_loop().time() + .25
            if status is None:
                assert json.loads(await service.generate('UTC mô tả', evidence, expires_at))['answer'] == 'mô tả'
            else:
                with pytest.raises(ChatError) as caught:
                    await service.generate('UTC mô tả', evidence, expires_at)
                assert caught.value.status_code == status and caught.value.code == code
                assert 'secret' not in str(caught.value)
            assert len(calls) == 1
        finally:
            await service.close()
    asyncio.run(run())


def test_expired_budget_never_calls_sdk(settings):
    async def run():
        with pytest.raises(ChatError) as caught:
            await GeminiService(settings).generate('UTC', {}, asyncio.get_running_loop().time() - 1)
        assert caught.value.code == 'REQUEST_DEADLINE_EXCEEDED'
    asyncio.run(run())
