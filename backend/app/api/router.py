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

api_router = APIRouter(prefix="/api")
api_router.include_router(courses.router)
api_router.include_router(conversations.router)
api_router.include_router(documents.router)
api_router.include_router(retrieval.router)
api_router.include_router(qa.router)
api_router.include_router(token_usage.router)

api_router.include_router(agent_profiles.router)
