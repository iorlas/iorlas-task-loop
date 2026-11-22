"""The experiment spec and the typed vocabulary of one run: loaded once at the edge, never re-read from text."""

import json
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

SLOT_PATH_LIMIT = 64  # bytes: the factory refuses a longer slot path


class Outcome(StrEnum):
    PASS = "pass"  # the last attempt is waiting to be landed (`land: manual`: never landed)
    HELD = "held"  # the factory held the task (plan hold, repeats exhausted, needs owner)
    INCOMPLETE = "incomplete"  # the rounds ended idle with the task neither passed nor held
    CAP_WALL = "cap:wall"  # the wall cap stopped the rounds' whole process tree
    INFRA = "infra"  # setup or the rounds process failed before a verdict


class Arm(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    workflow: str = "default"
    efforts: dict[str, str] = Field(default_factory=dict)  # step name -> effort, written as `[agents.<step>] effort`


class Task(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str  # the tracker id, identical in every arm (ledger L1)
    title: str
    text_file: Path  # the task text, relative to the spec file


class Spec(BaseModel):
    """Everything frozen before the first run. Paths are absolute or relative to the spec file."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    source: Path  # a repository that has `base` committed; only cloned
    base: str  # the frozen commit every arm starts from
    engine: Path  # a checkout with an installed `.venv`: the one `tl` every arm runs
    work: Path  # one folder per experiment; one subfolder per run
    tasks: tuple[Task, ...]
    arms: dict[str, Arm]
    repo_name: str = "aa"  # names the bare origin and the slot folder; short, slot paths are limited to 64 bytes
    label: str = "aa-real"
    backlog: str = "aa"
    seed: int
    in_flight: int = 2
    wall_minutes: int = 45  # stops one run's whole process tree
    attempt_minutes: int = 40  # `tl rounds start --minutes`
    round_seconds: int = 15


def load_spec(path: Path) -> Spec:
    spec = Spec.model_validate(json.loads(path.read_text()))
    base = path.resolve().parent
    return spec.model_copy(
        update={
            "source": _under(base, spec.source),
            "engine": _under(base, spec.engine),
            "work": _under(base, spec.work),
            "tasks": tuple(task.model_copy(update={"text_file": _under(base, task.text_file)}) for task in spec.tasks),
        }
    )


def _under(base: Path, path: Path) -> Path:
    return path if path.is_absolute() else base / path


class Run(BaseModel):
    """One planned run: a task in one arm, inside a block of the randomized design."""

    model_config = ConfigDict(frozen=True)
    name: str
    task: str
    arm: str
    block: int
    position: int  # 0-based order inside the block


class RunResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run: Run
    outcome: Outcome
    detail: str = ""
    started: float = 0.0
    ended: float = 0.0
    in_flight_planned: int = 1
    load_start: list[str] = Field(default_factory=list)  # 1, 5, 15 minute load averages
    load_end: list[str] = Field(default_factory=list)
    arm_base: str = ""
    export: list[dict[str, object]] = Field(default_factory=list)  # `tl attempt export --json`, one row per agent attempt
    diffstat: str = ""
    patch: str = ""  # the path of the saved diff of the run's `task/<id>` branch against `arm_base`
