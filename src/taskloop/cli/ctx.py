"""What a verb may need besides its arguments (tl.py builds it once per process)."""
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tlkernel.env import Env
from tlkernel.factorydb import declare_parts
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.procport import Spawner

from taskloop.app.parts import STAGE_PARTS


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


def declare_stage_parts() -> None:
    """The first thing a task-loop process does: say which factory.db parts it carries (no open is allowed before)."""
    declare_parts(STAGE_PARTS, complete=True)
