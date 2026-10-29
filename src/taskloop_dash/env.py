"""What every dash module shares: where the state lives, the caches, the clock, and the few facts only the launcher can supply.

The dash imports `taskloop.contracts` and nothing else of the main package. A fact that lives in engine code (the slot beads, the
waiting line, a repo's config) comes in as a callable on `Ports`, made by the launcher; a test passes fakes."""

import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from taskloop.contracts.ask import Ask, AskAction
from taskloop.contracts.dash import Result
from taskloop.contracts.locks import Ticket
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import AnswerAsk, Beads
from taskloop_dash.cache import FileCache, TtlCache
from taskloop_dash.tails import Tails

Bead = dict[str, Any]
LIVE_SECONDS = 90  # a transcript written within this is still running


def _no_beads(repo: str) -> list[Bead]:
    return []


def _no_tickets(repo: str) -> list[Ticket]:
    return []


def _default_cfg(repo: str) -> dict[str, Any]:
    return {"pick_label": "auto", "skip_labels": []}


def _no_store(repo: str) -> Beads:
    raise OSError(2, "bd is not installed")


def _no_reflections(hours: int) -> dict[str, Any]:
    return {}


def _ask_text(ask: Ask) -> str:
    return ask.decision


def _no_answer(repo: str, bead: str, action: AskAction, text: str, amend: bool) -> tuple[Ask | None, str]:
    raise OSError(2, "bd is not installed")


def _no_look(repo: str, item: str, verdict: str, note: str, look_bead: str) -> Result:
    return Result(ok=False, message="bd is not installed")


def _no_cause(repo: str, bead: str, scope: str, cause: str) -> Result:
    return Result(ok=False, message="bd is not installed")


def _no_ack(repo: str, bead: str, scope: str, on: bool) -> Result:
    return Result(ok=False, message="bd is not installed")


def _no_run_verb(repo: str, bead: str, run: str) -> Result:
    return Result(ok=False, message="bd is not installed")


def _no_note(repo: str, bead: str, run: str, text: str) -> Result:
    return Result(ok=False, message="bd is not installed")


def _no_stick(repo: str, ask: str, outcome: str, text: str) -> Result:
    return Result(ok=False, message="bd is not installed")


def _no_prune(repo: str, adr: str) -> Result:
    return Result(ok=False, message="bd is not installed")


def _no_ask_back(repo: str, bead: str, ask: str, text: str) -> Result:
    return Result(ok=False, message="bd is not installed")


def _no_versions() -> list[str]:
    return []


@dataclass
class Ports:
    """Read-only facts the launcher injects. The defaults say nothing, so a dash with no launcher still serves its own files."""

    slot_beads: Callable[[str], list[Bead]] = _no_beads  # this machine's slot beads of a repo
    waiting_line: Callable[[str], list[Ticket]] = _no_tickets  # the live slot tickets, first in line first
    load_cfg: Callable[[str], dict[str, Any]] = _default_cfg  # the repo's engine config: pick_label, skip_labels
    store: Callable[[str], Beads] = _no_store  # the typed bd port for a repo (the engine's BdStore); the only way the dash reaches bd
    answer: AnswerAsk = _no_answer  # file the owner's answer to an ask: the intake `tl answer` uses, receipt comment included
    look: Callable[[str, str, str, str, str], Result] = _no_look  # (repo, look item id, good|redo|undo, note, look bead or ""): Intake.look
    cause: Callable[[str, str, str, str], Result] = _no_cause  # (repo, bead, run or ask id, cause): Intake.cause
    ack: Callable[[str, str, str, bool], Result] = _no_ack  # (repo, bead, run id, seen): Intake.ack
    park: Callable[[str, str, str], Result] = _no_run_verb  # (repo, bead, newest run id): app/run/requests.OwnerVerbs.park
    stop: Callable[[str, str, str], Result] = _no_run_verb  # (repo, bead, newest run id): OwnerVerbs.stop
    note: Callable[[str, str, str, str], Result] = _no_note  # (repo, bead, newest run id, text): OwnerVerbs.note
    stick: Callable[[str, str, str, str], Result] = _no_stick  # (repo, ask id, outcome, text): Intake.stick
    prune: Callable[[str, str], Result] = _no_prune  # (repo, ADR id): Intake.prune
    ask_back: Callable[[str, str, str, str], Result] = _no_ask_back  # (repo, bead, ask id, text): Intake.ask_back
    reflections: Callable[[int], dict[str, Any]] = _no_reflections  # the run reflections of the last N hours
    ask_text: Callable[[Ask], str] = _ask_text  # the card text of an ask, rendered from its fields (domain/asks/text.py)
    installed_versions: Callable[[], list[str]] = _no_versions  # task-loop versions in the plugin cache


class Env:
    def __init__(self, config: Path | str | None = None, home: Path | str | None = None, ports: Ports | None = None,
                 clock: Callable[[], float] = time.time, version: str = "", tails: Tails | None = None) -> None:
        self.config = ConfigDir(config)
        self.home = Path(home) if home else Path.home()
        self.ports = ports or Ports()
        self.clock = clock
        self.version = version
        self.tails = tails or Tails()
        self.ttl = TtlCache(clock)
        self.files = FileCache()
        self.started = clock()
        self.last_seen = clock()
        self.projects = self.home / ".claude" / "projects"
        self.codex_sessions = self.home / ".codex" / "sessions"
        self.agent_runs = Path(os.environ.get("XDG_CONFIG_HOME") or self.home / ".config") / "agent-runs"

    def touch(self) -> None:
        """A page asked for something: the idle watch counts from now."""
        self.last_seen = self.clock()
