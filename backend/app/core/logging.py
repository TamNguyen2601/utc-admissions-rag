"""Request metadata only. Never format raw exceptions, URLs or request bodies."""

import json
import logging
import time
from contextvars import ContextVar
from uuid import UUID, uuid4

from starlette.datastructures import MutableHeaders

request_id_context: ContextVar[str] = ContextVar("request_id", default="")
logger = logging.getLogger("utc_admissions")


class SafeMetadataFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        try:
            request_id = str(UUID(getattr(record, "request_id", "")))
        except (ValueError, TypeError, AttributeError):
            request_id = ""
        method = getattr(record, "method", "")
        if method not in {"GET", "HEAD", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"}:
            method = "OTHER"
        status = getattr(record, "status", 500)
        status = status if type(status) is int and 100 <= status <= 599 else 500
        duration = getattr(record, "duration_ms", 0)
        duration = round(duration, 3) if type(duration) in {float, int} else 0
        return json.dumps({
            "event": "request_completed", "request_id": request_id,
            "method": method, "status": status, "duration_ms": duration,
        })


def configure_logging() -> None:
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(SafeMetadataFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    # Uvicorn's default access log includes raw URL/query, including Guest input.
    logging.getLogger("uvicorn.access").disabled = True


class RequestMetadataMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid4())  # Do not trust or reflect client-provided IDs.
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_context.set(request_id)
        start = time.perf_counter()
        status = 500

        async def send_metadata(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_metadata)
        finally:
            logger.info("request_completed", extra={
                "request_id": request_id, "method": scope["method"],
                "status": status, "duration_ms": (time.perf_counter() - start) * 1000,
            })
            request_id_context.reset(token)
