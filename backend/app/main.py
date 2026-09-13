from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.errors import register_exception_handlers
from app.api.router import api_router
from app.core.config import get_settings
from app.core.distribution import RESEARCH_AVAILABLE
from app.indexing import get_indexing_manager

settings = get_settings()
indexing_manager = get_indexing_manager()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if settings.auto_index_documents:
        await indexing_manager.recover_incomplete()
    training_worker = None
    if (
        RESEARCH_AVAILABLE
        and settings.agentic_edition == "research"
        and settings.training_worker_enabled
    ):
        from app.db.session import SessionFactory
        from app.training.worker import TrainingWorker

        training_worker = TrainingWorker(settings, SessionFactory)
        training_worker.start()
    try:
        yield
    finally:
        if training_worker is not None:
            await training_worker.close()
        await indexing_manager.close()


app = FastAPI(
    title=settings.app_name,
    version="1.4.0-beta.1",
    debug=settings.debug,
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
if RESEARCH_AVAILABLE:
    from app.training.upload_limit import TrainingRequestLimit

    app.add_middleware(TrainingRequestLimit)

register_exception_handlers(app)
app.include_router(api_router)


@app.get("/api/health", tags=["system"])
async def health_check() -> dict[str, str]:
    return {"status": "ok", "environment": settings.app_env}
