"""What every dash module shares: where the state lives, the caches, the clock, and the few facts only the launcher can supply.

The dash imports `taskloop.contracts` and nothing else of the main package. A fact that lives in engine code (the slot beads, the
waiting line, a repo's config) comes in as a callable on `Ports`, made by the launcher; a test passes fakes."""

import glob
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from taskloop.contracts.ask import Ask
from taskloop.contracts.locks import Ticket
from taskloop.contracts.paths import ConfigDir
from taskloop_dash.cache import FileCache, TtlCache
from taskloop_dash.tails import Tails

Bead = dict[str, Any]
RETAIN = 7 * 86400  # finished tasks and runs stay visible this long
LIVE_SECONDS = 90  # a transcript written within this is still running
STALE_RUN = 20 * 60  # a run with no close, no engine lock to ask and no log write for this long has stopped


def _no_beads(repo: str) -> list[Bead]:
    return []


def _no_tickets(repo: str) -> list[Ticket]:
    return []


def _default_cfg(repo: str) -> dict[str, Any]:
    return {"pick_label": "auto", "skip_labels": []}


def _no_bd(repo: str | None, *args: str, timeout: int = 30) -> Any:
    raise OSError(2, "bd is not installed")


def _no_reflections(hours: int) -> dict[str, Any]:
    return {}


def _ask_text(ask: Ask) -> str:
    return ask.decision


def _no_versions() -> list[str]:
    return []


def _newest_route() -> str:
    """The newest delegate route.py in the plugin cache: what a dash with no launcher can know (the launcher injects the pin and
    the installed entry)."""
    routes = glob.glob(str(Path.home() / ".claude/plugins/cache/*/iorlas-delegate/*/skills/delegate/route.py"))

    def version_of(p: str) -> list[int]:
        return [int(x) if x.isdigit() else 0 for x in p.split("/iorlas-delegate/")[1].split("/", maxsplit=1)[0].split(".")]
    return max(routes, key=version_of) if routes else ""


@dataclass
class Ports:
    """Read-only facts the launcher injects. The defaults say nothing, so a dash with no launcher still serves its own files."""

    slot_beads: Callable[[str], list[Bead]] = _no_beads  # this machine's slot beads of a repo
    waiting_line: Callable[[str], list[Ticket]] = _no_tickets  # the live slot tickets, first in line first
    load_cfg: Callable[[str], dict[str, Any]] = _default_cfg  # the repo's engine config: pick_label, skip_labels
    bd: Callable[..., Any] = _no_bd  # bd in a repo through the engine's adapter: bd(repo, *args, timeout=) -> (returncode, stdout, stderr)
    reflections: Callable[[int], dict[str, Any]] = _no_reflections  # the run reflections of the last N hours
    ask_text: Callable[[Ask], str] = _ask_text  # the card text of an ask, rendered from its fields (domain/asks/text.py)
    installed_versions: Callable[[], list[str]] = _no_versions  # task-loop versions in the plugin cache
    delegate_route: Callable[[], str] = _newest_route  # the delegate route.py to ask for status ("" none): pin, installed, newest


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
