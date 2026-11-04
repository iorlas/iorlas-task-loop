"""Finite run and land budgets, beside the durable pause/backoff policy."""
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class LivenessCaps:
    stale_retries: int = 3
    land_iterations: int = 20
    lock_wait_s: float = 300
    run_s: float = 1200
    judge_s: float = 300


LIVENESS: Final = LivenessCaps()
