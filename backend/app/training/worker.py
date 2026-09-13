from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.exceptions import ConflictError
from app.training.run_schemas import RunSnapshot
from app.training.run_store import RunStore
from app.training.trainer import FakeTrainer, Trainer

logger = logging.getLogger(__name__)


class TrainingWorker:
    def __init__(
        self,
        settings: Settings,
        sessions: async_sessionmaker[AsyncSession],
        trainer: Trainer | None = None,
    ) -> None:
        self.settings = settings
        self.sessions = sessions
        self.trainer = trainer or FakeTrainer(settings.training_fake_step_seconds)
        self.task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self.task is None:
            self.task = asyncio.create_task(self._loop(), name="fake-training-worker")

    async def close(self) -> None:
        if self.task is not None:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except Exception:
                # No exception text, prompt, source path, or credentials enter runtime logs.
                logger.warning("TRAINING_WORKER_TICK_FAILED")
            await asyncio.sleep(self.settings.training_poll_interval_seconds)

    async def run_once(self) -> bool:
        async with self.sessions() as session:
            claimed = await RunStore(session, self.settings).claim()
        if claimed is None:
            return False
        await self._execute(*claimed)
        return True

    async def _execute(self, run_id: UUID, token: str, snapshot: RunSnapshot) -> None:
        lost = asyncio.Event()

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(self.settings.training_lease_seconds / 3)
                try:
                    async with self.sessions() as session:
                        ok = await RunStore(session, self.settings).renew(token)
                    if not ok:
                        lost.set()
                        return
                except ConflictError:
                    # Ownership is checked again on every progress/final update.
                    continue

        async def progress(step: int) -> bool:
            if lost.is_set():
                return False
            async with self.sessions() as session:
                return await RunStore(session, self.settings).progress(run_id, token, step)

        heartbeat_task = asyncio.create_task(heartbeat(), name="fake-training-heartbeat")
        try:
            result = await self.trainer.run(snapshot, progress)
            async with self.sessions() as session:
                await RunStore(session, self.settings).finish(run_id, token, result)
        except asyncio.CancelledError:
            async with self.sessions() as session:
                await RunStore(session, self.settings).finish(run_id, token, None, interrupted=True)
            raise
        except Exception:
            async with self.sessions() as session:
                await RunStore(session, self.settings).finish(run_id, token, None, failed=True)
        finally:
            heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat_task
