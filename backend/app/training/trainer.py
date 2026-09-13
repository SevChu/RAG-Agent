"""Deterministic, offline trainer contract. No weights or training-stack imports."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import psutil  # type: ignore[import-untyped]

from app.training.run_schemas import ResourceEstimate, RunCreate, RunSnapshot
from app.training.validation import canonical

Progress = Callable[[int], Awaitable[bool]]


class Trainer(Protocol):
    async def run(self, snapshot: RunSnapshot, progress: Progress) -> dict[str, Any] | None: ...
    def estimate(self, request: RunCreate) -> ResourceEstimate: ...


class FakeTrainer:
    def __init__(self, step_seconds: float = 0.2, *, fail_at: int | None = None) -> None:
        # Fault injection exists only in trusted test code, never the HTTP contract.
        self.step_seconds = step_seconds
        self.fail_at = fail_at

    def estimate(self, request: RunCreate) -> ResourceEstimate:
        return ResourceEstimate(
            simulation_steps=request.simulation_steps,
            checkpoint_interval_seconds=self.step_seconds,
            nominal_simulation_seconds=request.simulation_steps * self.step_seconds,
            available_memory_bytes=psutil.virtual_memory().available,
        )

    async def run(self, snapshot: RunSnapshot, progress: Progress) -> dict[str, Any] | None:
        if not await progress(0):
            return None
        for step in range(1, snapshot.request.simulation_steps + 1):
            await asyncio.sleep(self.step_seconds)
            if not await progress(step):
                return None
            if self.fail_at == step:
                raise RuntimeError("synthetic trainer failure")
        return {
            "artifact_kind": "simulated",
            "deployable": False,
            "evaluation_status": "not_evaluated",
            "trainer": "fake-v1",
            "simulation_checksum": simulation_checksum(snapshot),
        }


def simulation_checksum(snapshot: RunSnapshot) -> str:
    # No wall-clock time or run ID enters the deterministic simulation checksum.
    identity = {
        "seed": snapshot.request.parameters.seed,
        "parameters": snapshot.request.parameters.model_dump(mode="json"),
        "content_sha256": snapshot.content_sha256,
        "base_model": snapshot.request.base_model,
        "steps": snapshot.request.simulation_steps,
    }
    return hashlib.sha256(canonical(identity)).hexdigest()
