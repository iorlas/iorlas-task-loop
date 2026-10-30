"""The seams the engine reaches the world through: delegate, bd, git, and the workflow's checks.

A port is a Protocol plus the typed requests and results that cross it. Adapters implement it against the real thing
(`route.py`, `bd`, an exec); fakes implement it in memory, so a test needs no process, no files and no bash."""
import threading  # noqa: TID251  only the type of a stop flag (Spawner.stream); contracts starts no thread
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import IO, Any, Literal, NamedTuple, Protocol, final

import msgspec

from taskloop.contracts.argv import text_of
from taskloop.contracts.ask import Ask, AskAction
from taskloop.contracts.bead import BdError, Bead, Comment
from taskloop.contracts.delegate import DelegateResult, LiveEvent, RunRequest
from taskloop.contracts.gitfacts import ConfigEntry, GrepHit, LogRow, Pick, RebaseOutcome, Ref, StatusRow, TreeEntry
from taskloop.contracts.ids import BeadId
from taskloop.contracts.slots import Checkout
from taskloop.contracts.wire import Rec

EventSink = Callable[[LiveEvent], None]


class Clock(Protocol):
    """Time, as a capability: SystemClock (adapters/clock.py) in production, FakeClock in tests."""

    def now(self) -> float: ...
    def monotonic(self) -> float: ...


class Sh(Protocol):
    """The engine's one way to run a command (an argv, no shell): (exit code, the last lines of its output).
    The whole output goes to `save`."""

    def __call__(self, cmd: Sequence[str], timeout: float = ..., check: bool = ..., save: Path | None = ...,
                 env: Mapping[str, str] | None = ..., pin: bool = ..., what: str = ..., cwd: Path | None = ...) -> tuple[int, str]: ...


class AnswerAsk(Protocol):
    """The owner's answer to an ask: the one intake `tl answer` uses (typed record, bead opened, receipt comment). The dashboard calls
    it with the ask's repo and bead; -> (the ask, "" or why: answered, withdrawn, closed, consumed, superseded, gone)."""

    def __call__(self, repo: str, bead: BeadId, action: AskAction, text: str, amend: bool) -> tuple[Ask | None, str]: ...


class Delegate(Protocol):
    def speaks(self) -> int:
        """The contract number delegate answers with (`route.py contract --json`); the caller gates on 3."""
        ...

    def run(self, req: RunRequest, brief: str, schema: dict[str, Any], on_event: EventSink | None = None) -> DelegateResult:
        """One AI step. `brief` and `schema` travel as values (an adapter that needs files makes them; `req.brief_path` and
        `req.schema_path` are ignored here). Never raises for a worker's failure: that is a result with `stop` set.
        `on_event` gets the worker's live events, in order, before `run` returns."""
        ...


@final
class NewBead(Rec):
    title: str
    issue_type: str = "task"
    priority: int | None = None
    description: str = ""
    acceptance_criteria: str = ""
    labels: list[str] = msgspec.field(default_factory=list)
    parent: str = ""
    deps: list[str] = msgspec.field(default_factory=list)
    no_inherit_labels: bool = False


@final
class BeadPatch(Rec):
    """What `update` changes; a field left at its default is not touched. assignee "" clears it."""

    status: str = ""
    if_assignee: str = ""  # apply only while this actor still holds the bead (bd checks it atomically)
    assignee: str | None = None
    description: str | None = None
    notes: str | None = None
    metadata: dict[str, Any] | None = None  # the whole metadata object replaced (set_metadata changes single keys)
    set_metadata: dict[str, str] = msgspec.field(default_factory=dict)
    unset_metadata: list[str] = msgspec.field(default_factory=list)


@final
class BeadQuery(Rec):
    status: str = ""
    label: str = ""
    include_closed: bool = False


class BdFailure(Exception):
    """bd refused or failed. `error.kind`: lint (missing sections), not_found, not_claimable, other."""

    def __init__(self, error: BdError) -> None:
        super().__init__(f"{error.kind}: {error.text}")
        self.error = error


class DoltPush(NamedTuple):
    """The outcome of a Dolt sync: code 0 synced; 1 error or a rejected push; 2 merge conflict; 3 retries exhausted; 4 stuck."""
    code: int
    text: str


class Beads(Protocol):
    """bd as the code uses it. Reads of an unknown bead answer None or []; `show` of a bead when bd itself fails (down, locked)
    raises BdFailure, so "no such bead" is never confused with "could not ask". A refused write raises BdFailure,
    except `claim`/`unclaim`, which answer whether the bead changed hands."""

    def show(self, bead: BeadId) -> Bead | None: ...
    def comments(self, bead: BeadId) -> list[Comment]: ...
    def find(self, query: BeadQuery) -> list[Bead]: ...
    def ready(self, label: str = "") -> list[Bead]: ...
    def create(self, new: NewBead) -> BeadId:
        """-> the new bead's id."""
        ...
    def update(self, bead: BeadId, patch: BeadPatch) -> None: ...
    def claim(self, bead: BeadId) -> bool: ...
    def unclaim(self, bead: BeadId, force: bool = False) -> bool: ...
    def heartbeat(self, bead: BeadId) -> None: ...
    def close(self, bead: BeadId, reason: str, if_assignee: str = "") -> None:
        """Close the bead. `if_assignee`: only while that actor still holds it (bd close has no such guard, so a same-value assignee
        update fences first, then bd close records the reason); a mismatch raises BdFailure and changes nothing."""
        ...
    def add_comment(self, bead: BeadId, text: str) -> None: ...
    def add_label(self, bead: BeadId, label: str) -> None: ...
    def remove_label(self, bead: BeadId, label: str) -> None: ...
    def reclaim(self, older_than: str, assignees: list[str]) -> None:
        """Free the claims whose lease ran out (of these assignees, else of all)."""
        ...
    def provenance(self, bead: BeadId, kind: str, source: str, ref: str = "", ref_kind: str = "", at: str = "",
                   payload: str = "") -> None: ...
    def dolt_push(self) -> DoltPush:
        """Sync bd's Dolt data with its remote (pull, then push). -> DoltPush; never raises for bd's refusal."""
        ...
    def at(self, cwd: str) -> Beads:
        """The same store asked about the tracker in `cwd`."""
        ...


class SlotGit(Protocol):
    """What a slot's life asks of git (reset, checkout, commit, worktrees). Every method takes the worktree it acts in and raises a
    SlotGitError subclass."""

    def fetch(self, d: str) -> None: ...
    def rebasing(self, d: str) -> bool: ...
    def rebase_abort(self, d: str) -> None: ...
    def dirty(self, d: str) -> bool: ...
    def branch(self, d: str) -> str:
        """The branch checked out in `d`, empty when HEAD is detached."""
        ...

    def commit_all(self, d: str, branch: str, message: str) -> None:
        """Commit every change on `branch`, created at HEAD when HEAD is detached."""
        ...

    def has_branch(self, d: str, branch: str) -> bool: ...
    def checkout(self, d: str, branch: str) -> None: ...
    def checkout_new(self, d: str, branch: str, start: str) -> None: ...
    def checkout_detached(self, d: str, ref: str) -> None: ...
    def clean(self, d: str, keep: list[str]) -> None: ...

    def checkouts(self, d: str) -> list[Checkout]: ...
    def remove_worktree(self, repo: str, path: str) -> bool: ...
    def add_worktree(self, repo: str, path: str, ref: str) -> None: ...
    def init_bare(self, d: str, branch: str) -> None:
        """A bare repository at the path `d` whose default branch is `branch`."""
        ...

    def clone(self, src: str, dst: str) -> None: ...
    def push(self, d: str, remote: str, refspec: str) -> None: ...


class Git(SlotGit, Protocol):
    """git, the one port every git call goes through (RealGit on the binary; a logic test runs it over tests/support/gitsim,
    and one contract suite, tests/ports/git_contract.py, holds both to the same answers). Reads return typed rows, not text to re-parse."""

    def clean(self, d: str, keep: list[str], ignored: bool = False) -> None:
        """Delete the untracked files (and the ignored ones with `ignored`) except those matching a `keep` pattern."""
        ...

    def remove_worktree_why(self, repo: str, path: str) -> str:
        """Remove one worktree without force; empty when it is gone, else the line of git's words that says why it stayed."""
        ...

    # -- reads that return rows (each raises a SlotGitError when git cannot answer) ------------------------------------------------
    def for_each_ref(self, d: str, *prefixes: str) -> list[Ref]:
        """Every ref under the prefixes (refs/heads/task/ ...), by full refname, with its oid."""
        ...

    def ls_remote(self, d: str, remote: str, *patterns: str) -> list[Ref]:
        """The refs `remote` shows for the patterns (refs/heads/task/*); raises when the remote does not answer."""
        ...

    def cherry(self, d: str, upstream: str, head: str) -> list[Pick]:
        """The commits of `head` not on `upstream`, each marked when its patch is already there."""
        ...

    def merged(self, d: str, into: str) -> list[Ref]:
        """The local branches (short names) whose tip is an ancestor of `into`."""
        ...

    def merge_base(self, d: str, a: str, b: str) -> str:
        """The best common ancestor of a and b, empty when they share none."""
        ...

    def is_ancestor(self, d: str, a: str, b: str) -> bool: ...
    def rev_parse(self, d: str, rev: str) -> str:
        """The oid `rev` names, empty when it names nothing."""
        ...

    def log(self, d: str, include: list[str], exclude: list[str] | None = None, limit: int = 0, grep: str = "") -> list[LogRow]:
        """The commits reachable from `include` and not from `exclude`, newest first; `grep`: only subjects that contain it."""
        ...

    def ls_tree(self, d: str, rev: str, *paths: str, recursive: bool = False) -> list[TreeEntry]: ...
    def status(self, d: str) -> list[StatusRow]: ...
    def check_ignore(self, d: str, paths: list[str], excludes: str = "") -> list[str]:
        """Those of `paths` the ignore rules (and the excludes file, when given) cover, without asking the index."""
        ...

    def git_dir(self, d: str) -> str:
        """The absolute git dir of the worktree `d` (its own admin folder), empty when `d` is no checkout."""
        ...

    def has_commit(self, d: str, oid: str) -> bool: ...
    def show(self, d: str, rev: str, path: str) -> str:
        """The text of the file `path` as it is at `rev`; raises when there is no such file there."""
        ...

    def ls_files(self, d: str, scope: Literal["tracked", "unignored", "ignored"] = "tracked", *spec: str) -> list[str]:
        """The tracked files; with `unignored` those and the untracked files the ignore rules do not cover; with `ignored` the untracked
        ones they cover, optionally only those under the pathspecs `spec`."""
        ...

    def grep(self, d: str, pattern: str, fixed: bool = False, word: bool = False) -> list[GrepHit]:
        """The lines of the tracked text files that match (a regex, or the literal text with `fixed`; `word`: whole words only)."""
        ...

    def config_get(self, d: str, key: str) -> str:
        """The value of one setting, empty when it is unset."""
        ...

    def config_entries(self, d: str, pattern: str) -> list[ConfigEntry]:
        """Every setting whose key matches the regex, each with the file it was set in."""
        ...

    def common_dir(self, d: str) -> str:
        """The absolute git dir the worktrees of `d`'s repo share, empty when `d` is in no repo."""
        ...

    def toplevel(self, d: str) -> str:
        """The root folder of the work tree `d` is in, empty when there is none."""
        ...

    def tree_of(self, d: str) -> str:
        """The tree id the work tree would commit now, untracked files included, without touching its index; raises when git cannot say."""
        ...

    def worktree_state(self, d: str) -> bytes | None:
        """git's own account of what differs from HEAD (branch line, changed and untracked paths), raw; None when git cannot say."""
        ...

    def diff(self, d: str, a: str, b: str, exclude: list[str] | None = None, stat: bool = False) -> str:
        """The patch (or with `stat` the summary) from tree a to tree b, leaving out the literal paths in `exclude`."""
        ...

    def add_worktree_force(self, repo: str, path: str, ref: str) -> None:
        """Like add_worktree, again if the path is registered but missing."""
        ...

    def remove_worktree_force(self, repo: str, path: str) -> None:
        """Remove a worktree whatever it holds; a failure is not an error."""
        ...

    def prune_worktrees(self, repo: str) -> None: ...

    # -- writes ----------------------------------------------------------------------------------------------------------------
    def rebase(self, d: str, onto: str, update_refs: bool = True) -> RebaseOutcome: ...
    def reset(self, d: str, rev: str, mode: Literal["soft", "mixed", "hard"] = "mixed") -> None: ...
    def tag(self, d: str, name: str, rev: str = "HEAD") -> None: ...
    def checkout_force(self, d: str, branch: str, start: str) -> None:
        """Point `branch` at `start` and check it out, throwing away local changes (checkout -f -B)."""
        ...

    def fetch_ref(self, d: str, source: str, ref: str) -> None:
        """Fetch one `ref` of another repository (a path or url) into FETCH_HEAD; raises when it has no such ref."""
        ...

    def remote_url(self, d: str, remote: str) -> str:
        """The url of the remote, empty when there is none."""
        ...

    def merge_ff(self, d: str, rev: str) -> None:
        """Fast-forward the checked-out branch to `rev`; raises when it would need a merge."""
        ...

    def commit_tracked(self, d: str, message: str) -> None:
        """Commit the changes of the tracked files (commit -a); untracked files stay out."""
        ...

    def stage(self, d: str, *paths: str) -> None: ...
    def commit_staged(self, d: str, message: str) -> None:
        """Commit what is staged, hooks included."""
        ...

    def pull_rebase(self, d: str, remote: str, branch: str) -> None: ...
    def delete_branch_at(self, d: str, branch: str, oid: str) -> None:
        """Delete a local branch only while it is at `oid`; raises RefRace-or-other SlotGitError when it moved."""
        ...

    def delete_remote_at(self, d: str, remote: str, ref: str, oid: str) -> None:
        """Delete the remote's `ref` only while it is at `oid` (force-with-lease)."""
        ...


@final
class CheckSpec(Rec):
    argv: list[str]
    cwd: str
    timeout_s: float = 3600.0
    env: dict[str, str] = msgspec.field(default_factory=dict)

    @property
    def cmd(self) -> str:
        return text_of(self.argv)


@final
class CheckResult(Rec):
    exit: int
    out: str = ""
    secs: float = 0.0
    timed_out: bool = False

    @property
    def passed(self) -> bool:
        return self.exit == 0 and not self.timed_out


class TreeProbe(Protocol):
    """What the plan-check lint may ask of the tree and the machine a check will run on."""

    def has_command(self, word: str) -> bool:
        """True when the word resolves to an executable on the tree's PATH (shutil.which)."""
        ...
    def recipes(self) -> set[str] | None:
        """The recipe and alias names of the tree's justfile, None when there is no just or no justfile."""
        ...
    def exists(self, path: str) -> bool:
        """The path (relative to the tree, or absolute) exists."""
        ...
    def is_dir(self, path: str) -> bool: ...


class Checks(Protocol):
    def run(self, spec: CheckSpec) -> CheckResult:
        """Run one command (an argv, no shell). Exit 124 and `timed_out` when the time ran out."""
        ...


class WaitTimeout(Exception):
    """`Child.wait(timeout)` ran out; the child lives on."""


class Child(Protocol):
    """A process the engine started and does not wait for in `Spawner.run`: pid, an optional stdin pipe, a wait, and its stop."""

    pid: int
    stdin: IO[bytes] | None

    def poll(self) -> int | None: ...
    def wait(self, timeout: float | None = None) -> int:
        """-> the exit code; raises WaitTimeout when `timeout` seconds pass first."""
        ...
    def stop(self, grace: float) -> None:
        """Stop the child's whole tree (SIGTERM, `grace` seconds, SIGKILL) and wait until it is gone."""
        ...
    def stop_async(self, grace: float) -> None:
        """The same on a thread of its own, so the caller's loop goes on while the tree ends."""
        ...


class Hold(Protocol):
    """The signals that arrived while a child was being spawned: replayed first inside the try that stops the child."""

    def replay(self) -> None: ...


@final
class Ran(Rec):
    """What a child printed and how it ended, when `Spawner.run` waited for it. Exit 124 and `timed_out` when `timeout_s` ran out."""
    exit: int
    out: str = ""
    err: str = ""
    timed_out: bool = False


@final
class RanBytes(Rec):
    exit: int
    out: bytes = b""
    err: bytes = b""


@final
class Streamed(Rec):
    """How `Spawner.stream` ended. `returncode` is None when a signal ended the child (then `signal` is its number). `timed_out` is why
    the engine stopped it ("wall", "stopped"), None when it ended by itself. `survivors`: pids of its tree still alive after the stop."""
    returncode: int | None
    signal: int | None
    timed_out: str | None
    secs: float
    survivors: tuple[int, ...] = ()


class Spawner(Protocol):
    """Starting a process, as a capability: the only way app/ and cli/ run a child (RealSpawner in adapters/spawner.py; the logic tests
    run the same adapter over tests/support/procsim). The child's environment is built by adapters/childenv.py: `env` is the base (the
    process's own when None), `extra` goes over it. A program that is not there raises OSError."""

    def run(self, argv: list[str], *, cwd: str | None = None, env: Mapping[str, str] | None = None, extra: Mapping[str, str] | None = None,
            timeout_s: float | None = None, capture: bool = True) -> Ran:
        """Run to the end. `capture` False: the child shares our stdout and stderr (out and err stay empty)."""
        ...

    def run_bytes(self, argv: list[str], *, cwd: str | None = None, extra: Mapping[str, str] | None = None) -> RanBytes: ...

    def stream(self, argv: list[str], *, cwd: str | None = None, env: Mapping[str, str] | None = None,
               extra: Mapping[str, str] | None = None,
               on_output: Callable[[str], None], timeout_s: float | None = None, stop: threading.Event | None = None,
               grace: float = 5.0) -> Streamed:
        """Run in a session of its own, each line of stdout and stderr to `on_output` as it comes. It ends by itself, at `timeout_s` of wall
        time or when `stop` is set; then its whole tree is stopped (SIGTERM, `grace` seconds, SIGKILL) and proven dead. Any exception
        raised while it runs (an interrupt, a raising SIGTERM handler) stops the tree first."""
        ...

    def start(self, argv: list[str], *, cwd: str | None = None, env: Mapping[str, str] | None = None,
              extra: Mapping[str, str] | None = None, stdin: Literal["null", "pipe"] = "null",
              out: IO[bytes] | Literal["null", "inherit"] = "null") -> Child:
        """A child that outlives this call, in a session of its own. `out`: a log both its streams go to, or nothing, or ours."""
        ...

    def start_held(self, argv: list[str], *, cwd: str | None = None, env: Mapping[str, str] | None = None,
                   extra: Mapping[str, str] | None = None, out: IO[bytes]) -> tuple[Child, Hold]:
        """`start` with stdin null and the log `out`, but the SIGTERM that arrived during the spawn is not replayed: the caller does it."""
        ...

    def stop_pid(self, pid: int, start: str | None = None, grace: float = 5.0) -> tuple[int, ...]:
        """Stop a process this program did not start (the dashboard server) and its tree: SIGTERM, `grace` seconds, SIGKILL. `start` is its
        start token (a pid that is another process now reads as gone). -> the pids still alive afterwards."""
        ...
