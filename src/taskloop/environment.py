"""The slot's environment before an implement agent: the repository's `setup` run by the entry, outside the sandbox, with
network, recorded in factory.db (`setup_store`), its output kept as an evidence file (S5e, design tl-8bh9.4.3.1.16.2
section 4).

In the entry process, after `prepare.base` and before the dispatch write, under the slot custody lock the entry holds
and inside the claim keep-alive; only for a step kind with `environment`. Order (a repeat skips 5-8: its slot keeps
attempt 1's environment): 1 two failed runs of this attempt refuse `environment:failed`; 2 the latest unfinished run is
reconciled (`interrupted` when its process is gone, else `environment:running` or `environment:unknown`, never
signalled); 3 preflight (platform, symlink-safe removal, the folders created); 4 the scratch emptied; 5 the profile read
from Git at B, and a `passed` run at this B and setup digest reused; 6 the reset (the slot's ignored files and nested
repositories removed, then an empty ignored listing, and the uv folders emptied); 7 each setup command in order, through
the registered start, its process group proven empty after it; 8 the slot clean afterwards; 9 the scratch emptied again;
10 the claim renewed once; 11 the deadline. Every refusal leaves the attempt `admitted` with nothing dispatched; no
process is ever signalled here.
"""

import hashlib
import json
import shlex
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, Protocol

from git_porcelain import GitUnavailable
from stream_proc import OwnedProcess

from taskloop.attempt_types import AttemptKey, AttemptRecord, AttemptResult, Checkouts
from taskloop.evidence_files import EvidenceFiles, SetupLog
from taskloop.prepare import Prepared
from taskloop.profile import ProfileFiles, Refused, Unavailable, read_profile
from taskloop.setup_store import Conclusion, SetupStore

SETUP_RUNS: Final = 2  # failed runs of one attempt before relaunches stop running its setup
type Renewal = Literal["held", "unrenewed", "lost"]
type Renew = Callable[[], Renewal]  # one claim renewal, now (the entry's keep-alive)
type ProcessSeen = Literal["gone", "alive", "unknown"]
type SetupSeen = Callable[[OwnedProcess], ProcessSeen]  # a registered setup command and its group; another boot is gone
type GroupAlive = Callable[[int], bool]  # any process left in a process group
type SlotProfiles = Callable[[Path, Path], ProfileFiles]  # (slot, its verified Git directory): the profile at a commit


@dataclass(frozen=True)
class SetupEnded:
    """How one setup command ended: `rc` (None when a signal or the stop ended it), whether the deadline stopped it, whether
    its exec failed after registration (it never ran), whether its start is uncertain (it may run; nothing waited)."""

    rc: int | None
    timed_out: bool
    exec_failed: bool
    pgid: int
    uncertain: bool = False


class SetupProcess(Protocol):
    """The registered start of one command (real: `stream_proc.run_registered`): `registered` commits its identity
    before it executes; stdin is empty, stderr merged into stdout, each output line to `line`; `timeout` stops and
    proves its tree."""

    def __call__(
        self, argv: Sequence[str], *, registered: Callable[[OwnedProcess], None], cwd: str, env: Mapping[str, str],
        timeout: float, line: Callable[[bytes], None],
    ) -> SetupEnded: ...


class EnvFiles(Protocol):
    """Folder creation and emptying outside the slot; never follows a link, never removes by age."""

    def ensure(self, path: Path) -> bool:
        """The folder exists as a directory, not a link (created 0700 with its parents when missing)."""
        ...

    def empty(self, path: Path) -> bool:
        """Everything inside the folder removed, the folder kept; a missing folder is empty. False when anything stays."""
        ...


@dataclass(frozen=True)
class Folders:
    """Beside the slots and `.locks/` under `<slots_root>/<repo_id>/`: the scratch (`TMPDIR`), uv's cache and its tools."""

    tmp: Path
    cache: Path
    tools: Path

    @property
    def env(self) -> Path:
        """`.env/<slot>`: emptied whole by every reset."""
        return self.cache.parent


def folders(slot: Path) -> Folders:
    return Folders(slot.parent / ".t" / slot.name, slot.parent / ".env" / slot.name / "uv-cache",
                   slot.parent / ".env" / slot.name / "uv-tools")


def setup_env(env: Mapping[str, str], found: Folders) -> dict[str, str]:
    """The agent's scrubbed environment plus the slot's folders; no `UV_OFFLINE` (setup has network)."""
    return {**env, "TMPDIR": str(found.tmp), "UV_CACHE_DIR": str(found.cache), "UV_TOOL_DIR": str(found.tools)}


def setup_digest(setup: Sequence[Sequence[str]]) -> str:
    """sha256 of the setup argv list as canonical JSON."""
    text = json.dumps([list(argv) for argv in setup], separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def _ending(ended: SetupEnded) -> bytes:
    """The factory's own frame line after a command."""
    if ended.timed_out:
        return b"timed out\n"
    if ended.exec_failed:
        return b"not started\n"
    return b"ended by a signal\n" if ended.rc is None else f"exit {ended.rc}\n".encode()


def _refused(reason: str) -> AttemptResult:
    return AttemptResult("refused", reason)


def _unavailable(reason: str) -> AttemptResult:
    return AttemptResult("unavailable", reason)


@dataclass(frozen=True)
class EnvironmentPorts:
    store: SetupStore
    checkouts: Checkouts
    profiles: SlotProfiles
    files: EnvFiles
    process: SetupProcess
    seen: SetupSeen
    lingering: GroupAlive
    logs: EvidenceFiles
    clock: Callable[[], float]
    platform: str  # `sys.platform`
    safe_removal: bool  # `shutil.rmtree.avoids_symlink_attacks`


@dataclass(frozen=True)
class _Run:
    """One setup run under way: whose, which, at which B, with which environment and log."""

    key: AttemptKey
    run: int
    slot: Path
    deadline: float
    env: Mapping[str, str]
    log: SetupLog


class Preparation:
    def __init__(self, ports: EnvironmentPorts) -> None:
        self.ports = ports

    def prepare(self, record: AttemptRecord, slot: Prepared, renew: Renew, env: Mapping[str, str]) -> AttemptResult | None:
        """Section 4's order; None when the agent may be dispatched."""
        admission = record.admission
        key, path = admission.key, Path(admission.slot_path)
        found = folders(path)
        stopped = self._ready(key, found)
        if stopped is None and admission.number == 1:
            try:
                stopped = self._setup(key, path, slot, admission.deadline, setup_env(env, found))
            except GitUnavailable:
                stopped = _unavailable("git")
        return stopped or self._finish(found, renew, admission.deadline)

    def _ready(self, key: AttemptKey, found: Folders) -> AttemptResult | None:
        """Steps 1-4: the failure count, the reconcile, the preflight, the scratch emptied."""
        if self.ports.store.failures(key) >= SETUP_RUNS:
            return _refused("environment:failed")
        stopped = self._reconcile(key) or self._preflight(found)
        if stopped is None and not self.ports.files.empty(found.tmp):
            return _unavailable("environment:files")
        return stopped

    def _finish(self, found: Folders, renew: Renew, deadline: float) -> AttemptResult | None:
        """Steps 9-11: the scratch emptied again (setup's temporary files never reach the agent), one claim renewal, the
        deadline."""
        if not self.ports.files.empty(found.tmp):
            return _unavailable("environment:files")
        if renew() == "lost":
            return _refused("claim_lost")
        return _refused("expired") if self.ports.clock() >= deadline else None

    def _reconcile(self, key: AttemptKey) -> AttemptResult | None:
        """An unfinished latest run: `interrupted` when nothing registered or its process and group are gone (another
        boot included); a live or unknown one refuses, never signalled."""
        latest = self.ports.store.latest(key)
        if latest is None or latest.conclusion is not None:
            return None
        seen = "gone" if latest.process is None else self.ports.seen(latest.process)
        if seen == "alive":
            return _unavailable("environment:running")
        if seen == "unknown":
            return _unavailable("environment:unknown")
        self.ports.store.conclude(key, latest.run, "interrupted", None, self.ports.clock())
        return None

    def _preflight(self, found: Folders) -> AttemptResult | None:
        """Checks and folder creation only (the access checks and the sandbox probe come with the agent's roots)."""
        if self.ports.platform != "linux":  # nothing of the environment is observed elsewhere (owner question Q2)
            return _refused("environment:platform")
        if not self.ports.safe_removal:
            return _refused("environment:remove_unsafe")
        ensured = all(self.ports.files.ensure(path) for path in (found.tmp, found.cache, found.tools))
        return None if ensured else _unavailable("environment:files")

    def _setup(self, key: AttemptKey, path: Path, slot: Prepared, deadline: float, env: Mapping[str, str]) -> AttemptResult | None:
        """Steps 5-8: the profile at B, reuse of a passed run, else the reset and a new run."""
        ports = self.ports
        profile = read_profile(ports.profiles(path, slot.gitdir), slot.head)
        if isinstance(profile, Refused):
            return _refused("environment:profile")
        if isinstance(profile, Unavailable):
            return _unavailable("environment:profile")
        digest = setup_digest(profile.setup)
        latest = ports.store.latest(key)
        if latest is not None and (latest.conclusion, latest.commit, latest.digest) == ("passed", slot.head, digest):
            return None  # no agent ran since it passed: this attempt is still `admitted`
        reset = self._reset(path, slot.gitdir, folders(path))
        if reset is not None:
            return reset
        run = 1 if latest is None else latest.run + 1
        try:
            log = ports.logs.open_setup_log(key, run)
        except OSError:
            return _unavailable("environment:files")
        with closing(log):
            ports.store.start(key, run, slot.head, digest, ports.clock())
            return self._run(_Run(key, run, path, deadline, env, log), slot.gitdir, profile.setup)

    def _reset(self, path: Path, gitdir: Path, found: Folders) -> AttemptResult | None:
        """The slot's ignored files and nested repositories removed (`git clean -ffdx` on the pinned view), then an empty
        ignored listing; `.env/<slot>` emptied and its two folders made again."""
        worktree = self.ports.checkouts(path, git_dir=gitdir).worktree(path)
        worktree.clean(ignored=True, nested=True)
        if worktree.dirty(ignored_under=["."]).ignored:
            return _refused("environment:reset")
        files = self.ports.files
        emptied = files.empty(found.env) and files.ensure(found.cache) and files.ensure(found.tools)
        return None if emptied else _unavailable("environment:files")

    def _run(self, run: _Run, gitdir: Path, setup: Sequence[Sequence[str]]) -> AttemptResult | None:
        """Each command in order; the first that does not end cleanly concludes the run. Then the slot must be clean."""
        ports = self.ports
        for index, argv in enumerate(setup):
            stopped = self._command(run, index, argv)
            if stopped is not None:
                return stopped
        if ports.checkouts(run.slot, git_dir=gitdir).worktree(run.slot).dirty().raw:
            return self._concluded(run, "dirty", None, _refused("environment:dirty"))
        return self._concluded(run, "passed", 0, None)

    def _command(self, run: _Run, index: int, argv: Sequence[str]) -> AttemptResult | None:
        ports = self.ports
        remaining = run.deadline - ports.clock()
        if remaining <= 0:
            return self._concluded(run, "timed_out", None, _refused("expired"))
        run.log.write(f"$ {shlex.join(argv)}\n".encode())

        def registered(process: OwnedProcess) -> None:
            ports.store.registered(run.key, run.run, index, process)

        try:
            ended = ports.process(argv, registered=registered, cwd=str(run.slot), env=run.env, timeout=remaining, line=run.log.write)
        except OSError:  # the start failed before any registration: nothing executed
            ended = SetupEnded(None, False, True, 0)
        if ended.uncertain:  # the identity is recorded; the next entry reconciles it
            run.log.write(b"start uncertain\n")
            return _unavailable("environment:uncertain")
        run.log.write(_ending(ended))
        if ended.timed_out:
            return self._concluded(run, "timed_out", ended.rc, _refused("expired"))
        if not ended.exec_failed and ports.lingering(ended.pgid):
            run.log.write(b"lingering\n")
            return self._concluded(run, "lingering", ended.rc, _unavailable("environment:lingering"))
        if ended.exec_failed or ended.rc != 0:
            return self._concluded(run, "failed", ended.rc, _unavailable("environment:exit"))
        return None

    def _concluded(self, run: _Run, conclusion: Conclusion, rc: int | None, result: AttemptResult | None) -> AttemptResult | None:
        self.ports.store.conclude(run.key, run.run, conclusion, rc, self.ports.clock())
        return result
