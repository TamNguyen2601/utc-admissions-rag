from contextlib import asynccontextmanager
from threading import Lock

from fastapi import FastAPI

from app.api.router import router
from app.api.routes.health import probe_ocr
from app.core.config import Settings, get_settings
from app.core.errors import EnvelopeCORSMiddleware, ExceptionBoundaryMiddleware, register_error_handlers
from app.core.logging import RequestMetadataMiddleware, configure_logging
from app.db.session import Database
from app.services.coordinator import Coordinator
from app.services.documents import DocumentService
from app.services.extraction import Extractor
from app.services.embedding import EmbeddingService, Indexer
from app.services.retrieval import RetrievalService
from app.services.gemini import GeminiService
from app.services.chat import ChatService


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings if settings is not None else get_settings()
    configure_logging()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        database = None
        gemini = None
        try:
            try:
                database = Database(config)
                database.initialize()
            except Exception:
                raise RuntimeError("Backend initialization failed; check local configuration.") from None
            application.state.database = database
            application.state.knowledge_lock = Lock()
            application.state.coordinator = Coordinator(database)
            application.state.encoder = EmbeddingService.local(config)
            application.state.documents = DocumentService(database, config.upload_dir,
                application.state.knowledge_lock, Indexer(database, application.state.encoder), extractor=Extractor(config))
            application.state.retrieval = RetrievalService(database, application.state.encoder,
                application.state.documents._profile(), application.state.knowledge_lock,
                config.retrieval_min_similarity)
            gemini = GeminiService(config)
            application.state.gemini = gemini
            application.state.chat = ChatService(application.state.retrieval, gemini, config)
            application.state.ocr_available = probe_ocr(config)
            yield
        finally:
            if gemini is not None:
                await gemini.close()
            if database is not None:
                database.dispose()

    application = FastAPI(title="UTC Admissions RAG Chatbot", lifespan=lifespan, debug=False)
    application.state.settings = config
    application.include_router(router)
    register_error_handlers(application)
    # Order: request metadata -> CORS -> safe error boundary -> routes.
    application.add_middleware(ExceptionBoundaryMiddleware)
    application.add_middleware(
        EnvelopeCORSMiddleware,
        allow_origins=config.cors_origins, allow_credentials=False,
        allow_methods=["GET", "HEAD", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    application.add_middleware(RequestMetadataMiddleware)
    return application


app = create_app()
