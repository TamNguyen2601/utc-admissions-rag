import os
import shutil
import subprocess

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict

from app.core.config import Settings

router = APIRouter()


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str
    embedding_ready: bool
    ocr_available: bool
    gemini_configured: bool


def probe_ocr(settings: Settings) -> bool:
    executable = shutil.which(settings.tesseract_cmd)
    if executable is None:
        return False
    environment = os.environ.copy()
    if settings.tessdata_prefix is not None:
        environment["TESSDATA_PREFIX"] = str(settings.tessdata_prefix)
    try:
        result = subprocess.run(
            [executable, "--list-langs"], capture_output=True, text=True,
            timeout=5, check=False, env=environment,
        )
        return result.returncode == 0 and {"vie", "eng"}.issubset(set(result.stdout.splitlines()))
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return False


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    return HealthResponse(
        status="ok", embedding_ready=request.app.state.encoder.ready,
        ocr_available=request.app.state.ocr_available,
        gemini_configured=request.app.state.settings.gemini_api_key is not None,
    )
