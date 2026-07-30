from fastapi import APIRouter

from app.api.routes import courses, documents

api_router = APIRouter(prefix="/api")
api_router.include_router(courses.router)
api_router.include_router(documents.router)
