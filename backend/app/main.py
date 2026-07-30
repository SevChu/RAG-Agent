from fastapi import FastAPI

from app.core.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    debug=settings.debug,
)


@app.get("/api/health", tags=["system"])
async def health_check() -> dict[str, str]:
    return {"status": "ok", "environment": settings.app_env}
