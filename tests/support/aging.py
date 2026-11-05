"""Make a run older: its budget clock restarts with `secs` more elapsed, the waited share kept."""

from typing import Any


def age(eng: Any, secs: float) -> None:
    eng.budget.restore(eng.budget.clock.wall() + secs, eng.waited)
