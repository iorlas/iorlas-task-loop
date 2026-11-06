"""What a verb may need besides its arguments (tl.py builds it once per process)."""
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from taskloop.contracts.env import Env
from taskloop.contracts.gitport import Git
from taskloop.contracts.identity import Identity
from taskloop.contracts.procport import Spawner


@dataclass(frozen=True)
class Ctx:
    """What a verb may need besides its arguments: the install this run executes from, the clock, the argv a loop re-execs itself with."""
    here: Path
    now: Callable[[], float]
    argv: list[str]
    env: Env  # the process environment, taken once here; everything below is handed this copy
    spawner: Spawner  # the one way a verb starts a process, built on `env`
    git: Git  # the one way a verb runs git, built on `env`
    who: Identity  # the session and bd actor this process acts as, built once from `env`
