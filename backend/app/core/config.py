"""Validated local settings; no network, model loading or filesystem writes."""

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, SettingsError
from sqlalchemy.engine import URL, make_url

BACKEND_DIR = Path(__file__).resolve().parents[2]
E5_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"


class ConfigurationError(ValueError):
    """Safe startup error, without configuration values or source exceptions."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8",
        extra="ignore", hide_input_in_errors=True, validate_default=True,
    )

    database_url: str = "sqlite:///./data/utc.db"
    jwt_secret: SecretStr = Field(repr=False)
    jwt_algorithm: Literal["HS256"] = "HS256"
    jwt_expire_minutes: int = Field(default=30, ge=30, le=30)
    jwt_issuer: str = Field(default="utc-admissions-local", min_length=1)
    jwt_audience: str = Field(default="utc-admissions-web", min_length=1)
    gemini_api_key: SecretStr | None = Field(default=None, repr=False)
    gemini_model: Literal["gemini-3.5-flash-lite"] = "gemini-3.5-flash-lite"
    embedding_model: Literal["intfloat/multilingual-e5-small"] = "intfloat/multilingual-e5-small"
    embedding_revision: str = Field(default=E5_REVISION, pattern=r"^[0-9a-f]{40}$")
    embedding_device: Literal["cpu"] = "cpu"
    data_dir: Path = Path("data")
    upload_dir: Path = Path("data/uploads")
    import_dir: Path = Path("data/import")
    model_cache_dir: Path = Path("data/models")
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    retrieval_min_similarity: float = Field(default=0.75, ge=-1, le=1, allow_inf_nan=False)
    chat_deadline_seconds: float = Field(default=60, gt=0, le=60, allow_inf_nan=False)
    tesseract_cmd: str = Field(default="tesseract", min_length=1)
    tessdata_prefix: Path | None = None
    ocr_languages: Literal["vie+eng"] = "vie+eng"
    ocr_page_timeout_seconds: int = Field(default=60, gt=0, le=60)
    ingestion_item_timeout_seconds: int = Field(default=300, gt=0, le=300)
    max_document_pages: int = Field(default=200, gt=0, le=200)

    @field_validator("jwt_secret")
    @classmethod
    def valid_secret(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if (len(raw.encode("utf-8")) < 32 or raw != raw.strip()
                or len(set(raw)) < 2
                or any(word in raw.lower() for word in
                       ("changeme", "change-me", "your-secret", "placeholder", "replace-me"))):
            raise ValueError("JWT_SECRET requires a generated secret of at least 32 bytes")
        return value

    @field_validator("gemini_api_key", mode="before")
    @classmethod
    def optional_key(cls, value):
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("database_url")
    @classmethod
    def local_database(cls, value: str) -> str:
        try:
            url = make_url(value)
            if (url.drivername != "sqlite" or url.host or url.username or url.password
                    or url.query or not url.database or url.database == ":memory:"):
                raise ValueError
            path = Path(url.database)
            if not path.is_absolute():
                path = BACKEND_DIR / path
            return str(URL.create("sqlite", database=str(path.resolve())))
        except Exception:
            raise ValueError("DATABASE_URL must reference a local SQLite file") from None

    @field_validator("data_dir", "upload_dir", "import_dir", "model_cache_dir", "tessdata_prefix")
    @classmethod
    def backend_relative_path(cls, value: Path | None) -> Path | None:
        if value is None:
            return None
        return (value if value.is_absolute() else BACKEND_DIR / value).resolve()

    @field_validator("tessdata_prefix", mode="before")
    @classmethod
    def empty_optional_path(cls, value):
        return None if value == "" else value

    @field_validator("cors_origins")
    @classmethod
    def explicit_origins(cls, values: list[str]) -> list[str]:
        for value in values:
            try:
                parts = urlsplit(value)
                valid = (parts.scheme in {"http", "https"} and parts.hostname
                         and not parts.username and not parts.password
                         and not parts.path and not parts.query and not parts.fragment
                         and "*" not in value and not any(c.isspace() for c in value))
                _ = parts.port
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("CORS_ORIGINS must contain explicit HTTP(S) origins")
        return list(dict.fromkeys(values))


def get_settings() -> Settings:
    try:
        return Settings()
    except (ValidationError, SettingsError):
        # Never chain Pydantic errors: they can contain raw env values in errors().
        raise ConfigurationError("Invalid backend configuration; check environment settings.") from None
