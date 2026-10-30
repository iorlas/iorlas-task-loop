"""What the loop is handed: the repo, its bd, its slots and the few effects it may cause. The composition root
(app/launch/loop.py) builds one from the real tl and engine; a test builds one on fakes. Nothing here reads the
process environment, starts a process or touches git."""
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from taskloop.app.slots.env import SlotEnv
from taskloop.contracts import paths
from taskloop.contracts.bead import Bead
from taskloop.contracts.config import RepoProfile
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import Beads


class Child(Protocol):
    """A run-task process the loop started."""

    pid: int

    def wait(self, timeout: float | None = None) -> int: ...


class Hold(Protocol):
    """The signals that arrived while the child was being spawned: replayed first inside the try that stops the child."""

    def replay(self) -> None: ...


class Probe(Protocol):
    def up(self) -> bool | None:
        """True, False, or None when the probe could not run."""
        ...


@dataclass(frozen=True)
class Storm:
    """A live storm record: nothing is claimed until it expires."""

    fingerprint: str
    banner: str


@dataclass(frozen=True)
class ReloadNote:
    """The note an engine leaves just before it execs into a newer install."""

    run: str
    to: str
    frm: str
    from_dir: str
    t: float


@dataclass
class LoopEnv:
    repo: str
    repo_key: str
    cfgdir: paths.ConfigDir
    store: Beads
    slot_env: Callable[[], SlotEnv]
    profile: Callable[[], RepoProfile]  # read from the base branch's commit (working tree when it does not resolve), every call
    fetch: Callable[[], None]
    lint: Callable[[Bead], str]  # why a bead is not self-contained, "" when it is
    running: Callable[[], dict[BeadId, str]]  # {bead: where} of the runs going now
    area_lock: Callable[[], AbstractContextManager[Any]]
    wt_lock: Callable[[str], AbstractContextManager[Any]]
    start_worktree: Callable[[str], str]
    claim: Callable[[BeadId, str, str], tuple[bool, str]]  # (bead, worktree, slot) -> (won, why not)
    loop_lock: Callable[[str, str, str | None, str], None]  # (worktree, slot, slot bead, bead)
    drop_engine_lock: Callable[[str], None]
    spawn: Callable[[list[str], Any, dict[str, str]], tuple[Child, Hold]]  # (argv, log file, extra env) -> the child (own process group)
    stop_now: Callable[[Child], None]  # ends the child and its tree without waiting (its close step still runs)
    stop_tree: Callable[[Child], None]  # the same, waiting for it
    run_task_argv: Callable[[BeadId, str, str, str, Path | None], list[str]]  # (bead, worktree, slot, outcome file, code dir)
    landed_on_base: Callable[[str, BeadId], bool]
    reload_note: Callable[[BeadId], ReloadNote | None]  # taken once: read and dropped
    chores: Callable[[], None]  # stale asks, the daily reflection
    ask_lines: Callable[[], list[str]]  # `tl status`: the beads parked on a dropped ask
    storm: Callable[[], Storm | None]
    has_delegate: Callable[[], bool]
    probe: Callable[[], Probe | None]  # None: no delegate to ask about the network
    roles: Callable[[], dict[str, bool | None] | None]  # role -> usable (None: unknown); None when no delegate is installed
    event: Callable[..., Any]
    pid_alive: Callable[[int], bool]
    behind: Callable[[str], int]  # how many installed releases are newer than a version
    version: str  # this install
    session_actor: str  # the session's actor, without this loop's suffix: names the slots-off worktree
    code_dir: str
    actor: Callable[[], str]
    exec_into: Callable[[Path, list[str], str], None]  # (install dir, argv, handover JSON): replace this process; returns only on failure
    take_handover: Callable[[], str]  # the state JSON an older install of this loop handed over ("" on a fresh start)
    say: Callable[[str], None] = print
    now: Callable[[], float] = time.time
    sleep: Callable[[float], None] = time.sleep
    pid: int = 0
    extra: dict[str, str] = field(default_factory=dict)
    prune: Callable[[Callable[[str], None]], Any] = lambda say: None  # `tl prune` at the loop's start; it says what it did through `say`
    free_bytes: Callable[[], int] = lambda: 1 << 62  # free space on the config dir's disk
