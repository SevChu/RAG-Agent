from fastapi import APIRouter

from app.api.routes import (
    agent_profiles,
    conversations,
    courses,
    documents,
    qa,
    retrieval,
    token_usage,
)
from app.core.distribution import RESEARCH_AVAILABLE

api_router = APIRouter(prefix="/api")
api_router.include_router(courses.router)
api_router.include_router(conversations.router)
api_router.include_router(documents.router)
api_router.include_router(retrieval.router)
api_router.include_router(qa.router)
api_router.include_router(token_usage.router)

api_router.include_router(agent_profiles.router)

# Product archives retain the schema but do not import or contain training management.

if RESEARCH_AVAILABLE:
    from app.training.adapter_routes import router as adapter_router
    from app.training.routes import router as training_dataset_router
    from app.training.run_routes import router as training_run_router

    api_router.include_router(adapter_router)
    api_router.include_router(training_dataset_router)
    api_router.include_router(training_run_router)
