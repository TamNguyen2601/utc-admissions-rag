from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

from app.core.logging import request_id_context
from app.services.auth import InvalidCredentials
from app.services.coordinator import RunInProgress
from app.services.embedding import QueryTooLong
from app.services.gemini import ChatError
from app.services.recommendation import QuizError

ERRORS = {
    400: ("BAD_REQUEST", "Yêu cầu không hợp lệ."),
    401: ("UNAUTHORIZED", "Bạn cần đăng nhập."),
    403: ("FORBIDDEN", "Bạn không có quyền truy cập."),
    404: ("NOT_FOUND", "Không tìm thấy tài nguyên."),
    405: ("METHOD_NOT_ALLOWED", "Phương thức không được hỗ trợ."),
    409: ("CONFLICT", "Yêu cầu xung đột với trạng thái hiện tại."),
    410: ("RESOURCE_UNAVAILABLE", "Tài nguyên không còn khả dụng."),
    413: ("PAYLOAD_TOO_LARGE", "Dữ liệu vượt giới hạn cho phép."),
    415: ("UNSUPPORTED_MEDIA_TYPE", "Định dạng không được hỗ trợ."),
    422: ("VALIDATION_ERROR", "Dữ liệu đầu vào không hợp lệ."),
    500: ("INTERNAL_SERVER_ERROR", "Đã xảy ra lỗi hệ thống."),
    503: ("SERVICE_UNAVAILABLE", "Dịch vụ chưa sẵn sàng."),
    504: ("GATEWAY_TIMEOUT", "Yêu cầu đã hết thời gian chờ."),
}


def error_response(status: int, *, code: str | None = None, headers=None) -> JSONResponse:
    default_code, message = ERRORS.get(status, ("HTTP_ERROR", "Yêu cầu không thể thực hiện."))
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code or default_code, "message": message, "details": None},
                 "request_id": request_id_context.get()},
        headers=headers,
    )


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException):
        # HTTPException.detail can contain user data or raw upstream exceptions.
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        if exc.status_code == 405 and exc.headers and "Allow" in exc.headers:
            headers = {"Allow": exc.headers["Allow"]}
        code = "INVALID_CREDENTIALS" if isinstance(exc, InvalidCredentials) else None
        if isinstance(exc, RunInProgress):
            code = "RUN_IN_PROGRESS"
        if isinstance(exc, QueryTooLong):
            code = "QUERY_TOO_LONG"
        if isinstance(exc, ChatError):
            code = exc.code
        if isinstance(exc, QuizError):
            code = exc.code
        return error_response(exc.status_code, code=code, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, _exc: RequestValidationError):
        # Do not reflect Pydantic input/body/ctx/msg to the public response.
        code = 'INVALID_QUIZ_ANSWERS' if (_request.method == 'POST'
            and _request.url.path == '/api/v1/recommendations') else None
        return error_response(422, code=code)


class ExceptionBoundaryMiddleware:
    """Handle unexpected errors inside CORS, before any raw traceback reaches Uvicorn."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def track_start(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, track_start)
        except Exception:
            if not started:
                await error_response(500)(scope, receive, send)
            # No streaming endpoints in this contract. Never expose raw exceptions.


class EnvelopeCORSMiddleware(CORSMiddleware):
    def preflight_response(self, request_headers):
        response = super().preflight_response(request_headers)
        if response.status_code == 400:
            headers = {name: value for name, value in response.headers.items()
                       if name.lower() not in {"content-length", "content-type"}}
            return error_response(400, code="CORS_REJECTED", headers=headers)
        return response
