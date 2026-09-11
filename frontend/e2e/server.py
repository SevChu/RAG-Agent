# ruff: noqa: E402
# Install isolated settings before importing application modules.
import asyncio
import os
import sys
from pathlib import Path

repository = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repository / "backend"))
from app.core.config import Settings

Settings.model_config["env_file"] = None
edition = os.environ.get("AGENTIC_UI_TEST_EDITION", "product")
if edition not in {"product", "research"}:
    raise ValueError("invalid test edition")
port = 18004 if edition == "product" else 18005
base = repository / "tmp" / f"week07-editions-{edition}-ui"
base.mkdir(parents=True, exist_ok=True)
os.environ.update(
    {
        "APP_ENV": "week07-ui-test",
        "AGENTIC_EDITION": edition,
        "DATABASE_URL": f"sqlite+aiosqlite:///{base.as_posix()}/ui.db",
        "UPLOAD_DIR": str(base / "uploads"),
        "QDRANT_PATH": str(base / "qdrant"),
        "LLM_API_KEY": "fixture-never-send",
        "LLM_AVAILABLE_MODELS": "fixture-a,fixture-b",
        "LLM_MODEL": "fixture-a",
        "QWEN_MODELS": "fixture-unconfigured",
        "QWEN_API_KEY": "",
        "KIMI_MODELS": "",
        "GLM_MODELS": "",
        "AUTO_INDEX_DOCUMENTS": "false",
        "CORS_ORIGINS": "http://127.0.0.1:41734,http://127.0.0.1:41735",
        "EXTERNAL_SEARCH_ENABLED": "false",
    }
)
from app.db.base import Base
from app.db.session import engine
from app.external_search import get_external_search_gateway
from app.generation import ChatCompletion, get_chat_completion_gateway
from app.indexing import get_indexing_manager
from app.main import app
from app.retrieval import RerankedRetrievalResult


class EmptyIndex:
    async def answer_search(self, **kwargs):
        return RerankedRetrievalResult(
            query=kwargs["query"],
            hits=(),
            dense_candidate_count=0,
            rejected_evidence_count=0,
            embedding_device=None,
            reranker_device=None,
        )

    async def exam_search(self, **kwargs):
        return await self.answer_search(**kwargs)


app.dependency_overrides[get_indexing_manager] = lambda: EmptyIndex()


class FakeGateway:
    async def complete_text(self, *, system_prompt, user_prompt, model):
        return ChatCompletion(content="模拟模型回复：" + model, model=model)

    async def complete(self, **kwargs):
        raise AssertionError("UI test must not invoke course models without evidence")


class NoSearch:
    async def search(self, **kwargs):
        raise AssertionError("UI test must not invoke external search")


app.dependency_overrides[get_chat_completion_gateway] = lambda: FakeGateway()
app.dependency_overrides[get_external_search_gateway] = lambda: NoSearch()


async def init():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


asyncio.run(init())
import uvicorn

uvicorn.run(app, host="127.0.0.1", port=port)
