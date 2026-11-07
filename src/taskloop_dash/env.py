"""What every dash module shares: where the state lives, the caches, the clock, and the few facts only the launcher can supply.

The dash imports `taskloop.contracts` and nothing else of the main package. A fact that lives in engine code (slot capacity, bd, the
owner's writes) comes in as a callable on `Ports`, made by the launcher; a test passes fakes."""

import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from taskloop.contracts.ask import Ask, AskAction
from taskloop.contracts.beadsport import Beads
from taskloop.contracts.dash import Result
from taskloop.contracts.dashhealth import Score
from taskloop.contracts.ids import BeadId
from taskloop.contracts.locks import LockRecord
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import AnswerAsk
from taskloop.contracts.slottable import SlotSource
from taskloop_dash.cache import FileCache, TtlCache
from taskloop_dash.readers import dbruns
from taskloop_dash.tails import Tails

Bead = dict[str, Any]
def _no_store(repo: str) -> Beads:
    raise OSError(2, "bd is not installed")


def _no_answer(repo: str, bead: BeadId, action: AskAction, text: str, amend: bool) -> tuple[Ask | None, str]:
    raise OSError(2, "bd is not installed")


def _no_look(repo: str, item: str, verdict: str, note: str, look_bead: str) -> Result:
    return Result(ok=False, message="bd is not installed")


def _no_cause(repo: str, bead: BeadId, scope: str, cause: str) -> Result:
    return Result(ok=False, message="bd is not installed")


def _no_ack(repo: str, bead: BeadId, scope: str, on: bool) -> Result:
    return Result(ok=False, message="bd is not installed")


def _no_run_verb(repo: str, bead: BeadId, run: str) -> Result:
    return Result(ok=False, message="bd is not installed")


def _no_note(repo: str, bead: BeadId, run: str, text: str) -> Result:
    return Result(ok=False, message="bd is not installed")


def _no_stick(repo: str, ask: str, outcome: str, text: str) -> Result:
    return Result(ok=False, message="bd is not installed")


def _no_prune(repo: str, adr: str) -> Result:
    return Result(ok=False, message="bd is not installed")


def _no_ask_back(repo: str, bead: BeadId, ask: str, text: str) -> Result:
    return Result(ok=False, message="bd is not installed")


def _no_error(repo: str) -> str:
    return ""


def _no_stamp(repo: str) -> object | None:
    return None


def _no_slots(repo: str) -> SlotSource:
    return SlotSource(host="")


def _no_dirs(root: str) -> frozenset[str] | None:
    return None


def _no_score(repo: str, since: float, until: float) -> Score | None:
    return None


def _no_resources(cfg: ConfigDir) -> list[tuple[str, LockRecord]]:
    return []


@dataclass
class Ports:
    """Read-only facts the launcher injects. The defaults say nothing, so a dash with no launcher still serves its own files."""

    slot_dirs: Callable[[str], frozenset[str] | None] = _no_dirs  # names of the slot folders in a folder; a listing, never a process
    slot_source: Callable[[str], SlotSource] = _no_slots  # the slot count as the loops read it (origin/main), the host and the slot folders
    resource_holders: Callable[[ConfigDir], list[tuple[str, LockRecord]]] = _no_resources
    scorecard: Callable[[str, float, float], Score | None] = _no_score  # (repo, since, until): the numbers of `tl report`
    profile_error: Callable[[str], str] = _no_error  # the repo's red row when its .task-loop.json does not load, else ""
    profile_stamp: Callable[[str], object | None] = _no_stamp  # process-free signature of the files deciding profile_error
    store: Callable[[str], Beads] = _no_store  # the typed bd port for a repo (the engine's BdStore); the only way the dash reaches bd
    answer: AnswerAsk = _no_answer  # file the owner's answer to an ask: the intake `tl answer` uses, receipt comment included
    look: Callable[[str, str, str, str, str], Result] = _no_look  # (repo, look item id, good|redo|undo, note, look bead or ""): Intake.look
    cause: Callable[[str, BeadId, str, str], Result] = _no_cause  # (repo, bead, run or ask id, cause): Intake.cause
    ack: Callable[[str, BeadId, str, bool], Result] = _no_ack  # (repo, bead, run id, seen): Intake.ack
    park: Callable[[str, BeadId, str], Result] = _no_run_verb  # (repo, bead, observed run id): app/run/requests.OwnerVerbs.park
    stop: Callable[[str, BeadId, str], Result] = _no_run_verb  # (repo, bead, observed run id): OwnerVerbs.stop
    note: Callable[[str, BeadId, str, str], Result] = _no_note  # (repo, bead, observed run id, text): OwnerVerbs.note
    stick: Callable[[str, str, str, str], Result] = _no_stick  # (repo, ask id, outcome, text): Intake.stick
    prune: Callable[[str, str], Result] = _no_prune  # (repo, ADR id): Intake.prune
    ask_back: Callable[[str, BeadId, str, str], Result] = _no_ask_back  # (repo, bead, ask id, text): Intake.ask_back


class Env:
    def __init__(self, config: Path | str, home: Path | str | None = None, ports: Ports | None = None,
                 clock: Callable[[], float] = time.time, version: str = "", tails: Tails | None = None, host: str = "") -> None:
        self.config = ConfigDir(config)
        self.home = Path(home) if home else Path.home()
        self.ports = ports or Ports()
        self.clock = clock
        self.version = version
        self.host = host
        self.tails = tails or Tails()
        self.ttl = TtlCache(clock)
        self.files = FileCache()
        self.kept_runs: dbruns.Kept = {}
        self.started = clock()
        self.last_seen = clock()
        self.projects = self.home / ".claude" / "projects"

    def touch(self) -> None:
        """A page asked for something: the idle watch counts from now."""
        self.last_seen = self.clock()
