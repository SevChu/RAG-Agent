# ruff: noqa: E402
# Test-only, local synthetic database. Never point at the configured application database.
import asyncio
import json
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = (ROOT / "tmp" / os.environ.get("AGENTIC_TRAINING_UI_DIR", "week08-training-ui")).resolve()
assert BASE.is_relative_to((ROOT / "tmp").resolve()), (
    "Fixture directory must remain under repository tmp"
)
edition = sys.argv[1]
assert edition in ("research", "product")
RUN = BASE / edition
RUN.mkdir(parents=True, exist_ok=True)
DB = RUN / "app.sqlite"
assert not DB.exists(), "Use a fresh fixture directory; existing databases are never overwritten"
assert not (RUN / "stop").exists(), "Use a fresh fixture directory"
os.chdir(ROOT / "backend")
sys.path.insert(0, str(ROOT / "backend"))
os.environ.update(
    {
        "DATABASE_URL": f"sqlite+aiosqlite:///{DB.as_posix()}",
        "AGENTIC_EDITION": edition,
        "APP_ENV": "week08-day04-isolated",
        "DEBUG": "false",
        "AUTO_INDEX_DOCUMENTS": "false",
        "EXTERNAL_SEARCH_ENABLED": "false",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "TRAINING_WORKER_ENABLED": "true" if edition == "research" else "false",
        "TRAINING_FAKE_STEP_SECONDS": "0.4",
        "CORS_ORIGINS": "http://127.0.0.1:15174,http://127.0.0.1:15175",
        "LLM_API_KEY": "offline-synthetic-placeholder",
        "LLM_MODEL": "model-a",
        "LLM_AVAILABLE_MODELS": "model-a",
    }
)
for key in ("QWEN_API_KEY", "KIMI_API_KEY", "GLM_API_KEY"):
    os.environ[key] = ""
for key, subdir in {
    "TRAINING_DATA_DIR": "training",
    "UPLOAD_DIR": "uploads",
    "QDRANT_PATH": "qdrant",
    "PADDLE_OCR_BASE_DIR": "models/ocr",
    "EMBEDDING_MODEL_PATH": "models/embedding",
    "RERANKER_MODEL_PATH": "models/reranker",
}.items():
    os.environ[key] = str(RUN / subdir)
from app.core.config import Settings

Settings.model_config["env_file"] = None
from alembic import command
from alembic.config import Config

command.upgrade(Config("alembic.ini"), "head")
# Permit loopback for Windows asyncio and the local preview, block remote providers.
original_connect = socket.socket.connect
original_resolve = socket.getaddrinfo


def connect(self, address):
    if not isinstance(address, tuple) or address[0] not in ("127.0.0.1", "::1"):
        raise RuntimeError("External network blocked for isolated UI acceptance")
    return original_connect(self, address)


def resolve(host, *args, **kwargs):
    if host not in ("localhost", "127.0.0.1", "::1", None):
        raise RuntimeError("External DNS blocked")
    return original_resolve(host, *args, **kwargs)


socket.socket.connect = connect
socket.getaddrinfo = resolve
from httpx import ASGITransport, AsyncClient

from app.db.session import engine
from app.main import app


async def seed():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://local") as client:
        if not (await client.get("/api/agent-profiles")).json()["data"]:
            for name in (
                "合成科研助手",
                "用于验证长名称展示与移动端布局的独立合成研究智能体",
            ):
                response = await client.post(
                    "/api/agent-profiles",
                    json={
                        "name": name,
                        "config": {
                            "model": {"provider": "deepseek", "model": "model-a"},
                            "system_prompt": "仅用于本地界面验收，不调用模型。",
                            "tools": {"web_search": False},
                        },
                    },
                )
                assert response.status_code == 201
    await engine.dispose()


asyncio.run(seed())
if edition == "research":
    import app.training.worker as worker
    from app.training.trainer import FakeTrainer

    class FailOnceTrainer(FakeTrainer):
        used = False

        async def run(self, snapshot, progress):
            # Trusted preview-only fixture. No fault parameter added to production API.
            if snapshot.request.parameters.seed == 13 and not type(self).used:
                type(self).used = True
                await progress(0)
                await progress(1)
                raise RuntimeError("synthetic UI acceptance failure")
            return await super().run(snapshot, progress)

    worker.FakeTrainer = FailOnceTrainer
(RUN / "preview-info.json").write_text(
    json.dumps(
        {
            "pid": os.getpid(),
            "edition": edition,
            "database": str(DB),
            "synthetic_only": True,
            "port": 18084 if edition == "research" else 18085,
        }
    ),
    encoding="utf-8",
)
import uvicorn


async def serve():
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=18084 if edition == "research" else 18085,
            access_log=False,
        )
    )

    async def watch_stop():
        while not server.should_exit:
            if (RUN / "stop").exists():
                server.should_exit = True
                return
            await asyncio.sleep(0.25)

    monitor = asyncio.create_task(watch_stop())
    try:
        await server.serve()
    finally:
        monitor.cancel()
        await asyncio.gather(monitor, return_exceptions=True)


asyncio.run(serve())
