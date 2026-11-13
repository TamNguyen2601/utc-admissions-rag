"""T003 dependency checks only; no application/API integration is claimed.

All network responses in this file are synthetic, not UTC or Gemini data.
Run: uv run --locked pytest tests/smoke/test_setup.py -v
"""

import asyncio
import importlib
import importlib.metadata
import inspect
import json
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest
from google import genai
from google.genai import errors, types


DEPENDENCIES = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "sqlalchemy": "sqlalchemy",
    "pydantic-settings": "pydantic_settings",
    "PyJWT": "jwt",
    "pwdlib": "pwdlib",
    "argon2-cffi": "argon2",
    "python-multipart": "python_multipart",
    "sentence-transformers": "sentence_transformers",
    "torch": "torch",
    "numpy": "numpy",
    "google-genai": "google.genai",
    "requests": "requests",
    "beautifulsoup4": "bs4",
    "PyMuPDF": "pymupdf",
    "APScheduler": "apscheduler",
    "tzdata": "tzdata",
    "pytest": "pytest",
    "httpx": "httpx",
}


@pytest.mark.parametrize("distribution,module", DEPENDENCIES.items())
def test_dependency_import(distribution, module):
    importlib.import_module(module)
    print(f"{distribution}=={importlib.metadata.version(distribution)}")


def test_python_and_cpu_build():
    import torch

    assert sys.version_info[:2] == (3, 13)
    assert torch.version.cuda is None
    assert not torch.cuda.is_available()
    assert torch.ones(2, device="cpu").sum().item() == 2


def test_timezone_and_scheduler_dependency():
    from apscheduler.triggers.cron import CronTrigger

    zone = ZoneInfo("Asia/Ho_Chi_Minh")
    instant = datetime(2026, 11, 13, 10, tzinfo=timezone.utc)
    assert instant.astimezone(zone).utcoffset() == timedelta(hours=7)
    trigger = CronTrigger(hour=0, minute=0, timezone=zone)
    fire = trigger.get_next_fire_time(None, instant)
    assert fire.isoformat() == "2026-11-14T00:00:00+07:00"
    assert trigger.get_next_fire_time(fire, fire).isoformat() == (
        "2026-11-15T00:00:00+07:00"
    )


@pytest.mark.parametrize("outcome", [200, 401, 403, 429, 503, "timeout"])
def test_gemini_async_timeout_and_one_attempt(outcome):
    async def run():
        calls = []

        async def respond(request):
            calls.append(request)
            # Per-call timeout overrides the client default, in milliseconds.
            assert request.extensions["timeout"]["read"] == pytest.approx(0.25)
            assert request.url.path.endswith(
                "/models/gemini-3.5-flash-lite:generateContent"
            )
            assert json.loads(request.content)["contents"]
            if outcome == "timeout":
                raise httpx.ReadTimeout("synthetic timeout", request=request)
            if outcome != 200:
                return httpx.Response(
                    outcome,
                    json={"error": {"code": outcome, "message": "synthetic error"}},
                )
            return httpx.Response(
                200,
                json={"candidates": [{"content": {
                    "role": "model", "parts": [{"text": "synthetic response"}]
                }}]},
            )

        client = genai.Client(
            api_key="synthetic-test-key-not-a-credential",
            http_options=types.HttpOptions(
                timeout=1000,
                retry_options=types.HttpRetryOptions(attempts=1),
                async_client_args={
                    "transport": httpx.MockTransport(respond), "trust_env": False
                },
            ),
        )
        try:
            assert inspect.iscoroutinefunction(client.aio.models.generate_content)
            kwargs = dict(
                model="gemini-3.5-flash-lite",
                contents="SYNTHETIC SDK DEPENDENCY CHECK",
                config=types.GenerateContentConfig(
                    http_options=types.HttpOptions(timeout=250)
                ),
            )
            if outcome == 200:
                response = await client.aio.models.generate_content(**kwargs)
                assert response.text == "synthetic response"
            else:
                expected = httpx.ReadTimeout if outcome == "timeout" else errors.APIError
                with pytest.raises(expected) as caught:
                    await client.aio.models.generate_content(**kwargs)
                if outcome != "timeout":
                    assert caught.value.code == outcome
            assert len(calls) == 1
        finally:
            await client.aio.aclose()
            client.close()

    asyncio.run(run())


def test_gemini_real_transport_timeout_on_loopback():
    """Verify the actual SDK/httpx timeout; no external service or API key."""
    async def run():
        calls = []
        finished = asyncio.Event()

        async def stall(reader, writer):
            try:
                await reader.readuntil(b"\r\n\r\n")
                calls.append(True)
                # Never send a response; wait until the timed-out client closes.
                await reader.read()
            finally:
                writer.close()
                await writer.wait_closed()
                finished.set()

        server = await asyncio.start_server(stall, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        client = genai.Client(
            api_key="synthetic-test-key-not-a-credential",
            http_options=types.HttpOptions(
                base_url=f"http://127.0.0.1:{port}",
                timeout=1000,
                retry_options=types.HttpRetryOptions(attempts=1),
                async_client_args={"trust_env": False},
            ),
        )
        try:
            async with server:
                start = asyncio.get_running_loop().time()
                with pytest.raises(httpx.TimeoutException):
                    async with asyncio.timeout(5):
                        await client.aio.models.generate_content(
                            model="gemini-3.5-flash-lite",
                            contents="SYNTHETIC TIMEOUT CHECK",
                            config=types.GenerateContentConfig(
                                http_options=types.HttpOptions(timeout=100)
                            ),
                        )
                elapsed = asyncio.get_running_loop().time() - start
                assert 0.08 <= elapsed < 5
                assert len(calls) == 1
                print(f"SDK loopback timeout elapsed={elapsed:.3f}s; requests=1")
        finally:
            await client.aio.aclose()
            client.close()
            server.close()
            await server.wait_closed()
            await asyncio.wait_for(finished.wait(), timeout=2)

    asyncio.run(run())
