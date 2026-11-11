"""The slot's environment before an implement agent or a checks block: the repository's `setup` run by the entry, outside
the sandbox, with network, recorded in factory.db (`setup_store`), its output kept as an evidence file (S5e, design
tl-8bh9.4.3.1.16.2 section 4; checks: tl-8bh9.14.6 section 8).

In the entry process, after `prepare.base` and before the dispatch write, under the slot custody lock the entry holds
and inside the claim keep-alive; only for a step kind with `environment`. Order (a repeat skips 5-8: its slot keeps
attempt 1's environment): 1 two failed runs of this attempt refuse `environment:failed`; 2 the latest unfinished run is
reconciled (`interrupted` when its process is gone, else `environment:running` or `environment:unknown`, never
signalled); 3 preflight (platform, the TMPDIR budget, each root exactly beside the slot and apart from it, its Git
directories, the person's checkout, the evidence and factory.db's folder, symlink-safe removal, the folders made 0700);
4 the scratch emptied, then the sandbox probe run in it; 5 the profile read from Git at B, and a `passed` run at this B
and setup digest reused; 6 the reset (the slot's ignored files and nested repositories removed, then an empty ignored
listing, and the uv folders emptied); 7 each setup command in order, through
the registered start, its process group proven empty after it; 8 the slot clean afterwards; 9 the scratch emptied again;
10 the claim renewed once; 11 the deadline. Every refusal leaves the attempt `admitted` with nothing dispatched; no
process is ever signalled here.

A checks slot (`SetupFor.commit` set) differs in three points: no sandbox probe (`probe=None`), no reuse of a passed run
(a block ran task code on the host), and the reset first puts tracked files back to exactly X (`reset --hard X`) before
the same `clean`; it expects `(X, detached)` after setup. The implement path never resets tracked files.
"""

import hashlib
import json
import shlex
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from git_porcelain import GitUnavailable
from stream_proc import OwnedProcess

from taskloop.access import TMP_BYTES, Folders, folders
from taskloop.attempt_types import AttemptKey, AttemptRecord, AttemptResult, Checkouts
from taskloop.evidence_files import CappedLog, EvidenceFiles
from taskloop.prepare import Prepared, task_branch
from taskloop.profile import ProfileFiles, Refused, Unavailable, read_profile
from taskloop.setup_store import SETUP_RUNS, Conclusion, SetupSeen, SetupStore

type Renewal = Literal["held", "unrenewed", "lost"]
type Renew = Callable[[], Renewal]  # one claim renewal, now (the entry's keep-alive)
type GroupAlive = Callable[[int], bool]  # any process left in a process group
type SlotProfiles = Callable[[Path, Path], ProfileFiles]  # (slot, its verified Git directory): the profile at a commit
type Launch = tuple[str, Mapping[str, str]]  # the agent's Codex executable and its scrubbed environment (the credentials)
# Whether the implement agent's sandbox works here: `codex sandbox` (exe) with the agent's environment and keys, run in the
# freshly emptied scratch, gives the shell its variables and writes each folder and not /tmp.
type SandboxProbe = Callable[[str, Mapping[str, str], Folders], bool]


@dataclass(frozen=True)
class SetupEnded:
    """How one setup command ended: `rc` (None when a signal or the stop ended it), whether the deadline stopped it, whether
    its exec failed after registration (it never ran), whether its start is uncertain (it may run; nothing waited)."""

    rc: int | None
    timed_out: bool
    exec_failed: bool
    pgid: int
    uncertain: bool = False
    survivors: bool = False  # the stop left a process of its tree alive (`Result.survivors`): it is lingering


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

    def resolve(self, path: Path) -> Path | None:
        """The absolute path with every existing link followed (a missing tail kept as written); None when unreadable."""
        ...


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


def _nested(one: Path, other: Path) -> bool:
    return one.is_relative_to(other) or other.is_relative_to(one)


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
    probe: SandboxProbe
    protected: tuple[Path, ...]  # no root may equal, hold or sit inside these: the evidence root, factory.db's folder
    tmp_bytes: int = TMP_BYTES  # TMPDIR's budget; only a test of the sequence on a long tmp_path widens it


@dataclass(frozen=True)
class SetupFor:
    """Whose slot is set up: `commit` None for an implement slot (B is the prepared HEAD on `branch`, `task/<id>`); for a
    checks slot X, the slot reset hard to it and expected detached there (`branch` None). `first`: the setup runs (an
    implement repeat keeps attempt 1's environment)."""

    key: AttemptKey
    slot: Path
    commit: str | None
    branch: str | None
    deadline: float
    first: bool


@dataclass(frozen=True)
class _Run:
    """One setup run under way: whose, which, at which commit, with which environment and log."""

    key: AttemptKey
    run: int
    slot: Path
    head: str  # B, or X for a checks slot
    branch: str | None  # task/<id>, None for a checks slot (detached)
    deadline: float
    env: Mapping[str, str]
    log: CappedLog


class Preparation:
    def __init__(self, ports: EnvironmentPorts) -> None:
        self.ports = ports

    def prepare(self, record: AttemptRecord, slot: Prepared, renew: Renew, launch: Launch) -> AttemptResult | None:
        """Section 4's order; None when the agent may be dispatched. `launch`: the agent's executable and the credentials'
        scrubbed environment (setup gets it with the folders, the probe with the agent's additions)."""
        admission = record.admission
        target = SetupFor(admission.key, Path(admission.slot_path), None, task_branch(admission.task.task_id),
                          admission.deadline, admission.number == 1)
        return self.prepare_for(target, slot, renew, launch[1], probe=launch)

    def prepare_for(self, target: SetupFor, slot: Prepared, renew: Renew, env: Mapping[str, str], *,
                    probe: Launch | None) -> AttemptResult | None:
        """Both paths: `env` is the scrubbed environment setup gets with the folders; `probe` the agent's Codex and
        environment for the sandbox probe, None for no probe (a checks slot)."""
        found = folders(target.slot)
        stopped = self._ready(target.key, target.slot, slot, probe)
        if stopped is None and target.first:
            try:
                stopped = self._setup(target, slot, setup_env(env, found))
            except GitUnavailable:
                stopped = _unavailable("git")
        return stopped or self._finish(found, renew, target.deadline)

    def _ready(self, key: AttemptKey, path: Path, slot: Prepared, probe: Launch | None) -> AttemptResult | None:
        """Steps 1-4: the failure count (before the probe: a dead attempt costs nothing), the reconcile, the preflight,
        the scratch emptied, then the sandbox probe in it (never in the slot, whose ignored files are not reset yet)."""
        if self.ports.store.failures(key) >= SETUP_RUNS:
            return _refused("environment:failed")
        found = folders(path)
        stopped = self._reconcile(key) or self._preflight(path, slot, found)
        if stopped is not None:
            return stopped
        if not self.ports.files.empty(found.tmp):
            return _unavailable("environment:files")
        if probe is None:
            return None
        exe, env = probe
        return None if self.ports.probe(exe, env, found) else _refused("environment:sandbox")

    def _finish(self, found: Folders, renew: Renew, deadline: float) -> AttemptResult | None:
        """Steps 9-11: the scratch emptied again (setup's temporary files never reach the agent), one claim renewal, the
        deadline."""
        if not self.ports.files.empty(found.tmp):
            return _unavailable("environment:files")
        if renew() == "lost":
            return _refused("claim_lost")
        return _refused("expired") if self.ports.clock() >= deadline else None

    def _reconcile(self, key: AttemptKey) -> AttemptResult | None:
        """The latest run's `unsettled` command (unfinished, or concluded `lingering`/`timed_out`) must be gone with its
        group (another boot counts as gone); a live or unknown one refuses, never signalled. An unfinished run whose
        command is gone, or that never registered one, is concluded `interrupted`."""
        latest = self.ports.store.latest(key)
        if latest is None or (latest.conclusion is not None and latest.unsettled is None):
            return None
        command = latest.unsettled
        seen = "gone" if command is None else self.ports.seen(command)
        if seen == "alive":
            return _unavailable("environment:running")
        if seen == "unknown":
            return _unavailable("environment:unknown")
        if latest.conclusion is None:
            self.ports.store.conclude(key, latest.run, "interrupted", None, self.ports.clock())
        return None

    def _preflight(self, path: Path, slot: Prepared, found: Folders) -> AttemptResult | None:
        """Checks and folder creation only (section 6); the probe follows the scratch's emptying."""
        ports = self.ports
        if ports.platform != "linux":  # nothing of the environment is observed elsewhere (owner question Q2)
            return _refused("environment:platform")
        if len(str(found.tmp).encode()) > ports.tmp_bytes:
            return _refused("environment:path_long")
        if not self._apart(path, slot, found):
            return _refused("environment:roots")
        if not ports.safe_removal:
            return _refused("environment:remove_unsafe")
        return None if all(ports.files.ensure(root) for root in found.roots) else _unavailable("environment:files")

    def _apart(self, path: Path, slot: Prepared, found: Folders) -> bool:
        """Resolved, each root is exactly where `folders` puts it beside the resolved slot (no link anywhere below
        `<slots_root>/<repo_id>/`, so never a sibling slot, `.locks/` or another root), and none equals, holds or sits
        inside the slot, its Git directory G, the common one C, the person's checkout, the evidence root or factory.db's
        folder."""
        resolve = self.ports.files.resolve
        base = resolve(path.parent)
        roots = [resolve(root) for root in found.roots]
        kept = [resolve(each) for each in (path, slot.gitdir, slot.gitdir.parent.parent, slot.root, *self.ports.protected)]
        if base is None:
            return False
        expected = folders(base / path.name).roots
        if roots != list(expected):
            return False
        return not any(other is None or _nested(root, other) for root in expected for other in kept)

    def _setup(self, target: SetupFor, slot: Prepared, env: Mapping[str, str]) -> AttemptResult | None:
        """Steps 5-8: the profile at B (X for a checks slot), reuse of a passed run (never for a checks slot), else the
        reset and a new run."""
        ports, key, path = self.ports, target.key, target.slot
        head = target.commit or slot.head
        profile = read_profile(ports.profiles(path, slot.gitdir), head)
        if isinstance(profile, Refused):
            return _refused("environment:profile")
        if isinstance(profile, Unavailable):
            return _unavailable("environment:profile")
        digest = setup_digest(profile.setup)
        latest = ports.store.latest(key)
        reusable = latest is not None and (latest.conclusion, latest.commit, latest.digest) == ("passed", head, digest)
        if reusable and target.commit is None:
            return None  # no agent ran since it passed: this attempt is still `admitted`
        reset = self._reset(path, slot.gitdir, folders(path), target.commit)
        if reset is not None:
            return reset
        run = 1 if latest is None else latest.run + 1
        try:
            log = ports.logs.open_setup_log(key, run)
        except OSError:
            return _unavailable("environment:files")
        with closing(log):
            ports.store.start(key, run, head, digest, ports.clock())
            return self._run(_Run(key, run, path, head, target.branch, target.deadline, env, log), slot.gitdir, profile.setup)

    def _reset(self, path: Path, gitdir: Path, found: Folders, commit: str | None) -> AttemptResult | None:
        """A checks slot's tracked files and index back to exactly `commit` first (`git reset --hard`, so a check killed
        mid-rewrite cannot poison the next block), only while the pinned view lists it detached at `commit` (an attached
        HEAD would carry its branch to X: `environment:moved`); then the slot's ignored files and nested repositories
        removed (`git clean -ffdx` on the pinned view), then an empty ignored listing; `.env/<slot>` emptied and its two
        folders made again."""
        view = self.ports.checkouts(path, git_dir=gitdir)
        worktree = view.worktree(path)
        if commit is not None:
            listed = next((info for info in view.worktrees() if info.path == path), None)
            if listed is None or (listed.head, listed.branch) != (commit, None):
                return _refused("environment:moved")
            worktree.reset(commit, mode="hard")
        worktree.clean(ignored=True, nested=True)
        if worktree.dirty(ignored_under=["."]).ignored:
            return _refused("environment:reset")
        files = self.ports.files
        emptied = files.empty(found.env) and files.ensure(found.cache) and files.ensure(found.tools)
        return None if emptied else _unavailable("environment:files")

    def _run(self, run: _Run, gitdir: Path, setup: Sequence[Sequence[str]]) -> AttemptResult | None:
        """Each command in order; the first that does not end cleanly concludes the run. Then, through the pinned view,
        the slot must still be at B on its task branch, or at X detached (`dirty`, word `moved`), and clean (`dirty`)."""
        for index, argv in enumerate(setup):
            stopped = self._command(run, index, argv)
            if stopped is not None:
                return stopped
        view = self.ports.checkouts(run.slot, git_dir=gitdir)
        listed = next((info for info in view.worktrees() if info.path == run.slot), None)
        if listed is None or (listed.head, listed.branch) != (run.head, run.branch):
            return self._concluded(run, "dirty", None, _refused("environment:moved"))
        if view.worktree(run.slot).dirty().raw:
            return self._concluded(run, "dirty", None, _refused("environment:dirty"))
        return self._concluded(run, "passed", 0, None)

    def _command(self, run: _Run, index: int, argv: Sequence[str]) -> AttemptResult | None:
        ports = self.ports
        remaining = run.deadline - ports.clock()
        if remaining <= 0:
            return self._concluded(run, "timed_out", None, _refused("expired"))
        run.log.write(f"$ {shlex.join(argv)}\n".encode())

        committed: list[OwnedProcess] = []

        def registered(process: OwnedProcess) -> None:
            ports.store.registered(run.key, run.run, index, process)
            committed.append(process)

        try:
            ended = ports.process(argv, registered=registered, cwd=str(run.slot), env=run.env, timeout=remaining, line=run.log.write)
        except OSError:
            if committed:  # the supervision failed after the command started: how it ended is unknown, its group is not
                run.log.write(b"ended uncertainly\n")
                return self._judged(run, SetupEnded(None, False, False, committed[0].pgid))
            ended = SetupEnded(None, False, True, 0)  # the start failed before any registration: nothing executed
        if ended.uncertain:  # the identity is recorded; the next entry reconciles it
            run.log.write(b"start uncertain\n")
            return _unavailable("environment:uncertain")
        run.log.write(_ending(ended))
        return self._judged(run, ended)

    def _judged(self, run: _Run, ended: SetupEnded) -> AttemptResult | None:
        """A command that ended, whatever the end: a process left (its stop's survivors, or its group still alive), then
        stopped by the deadline, then a failed or never-run command."""
        if not ended.exec_failed and (ended.survivors or self.ports.lingering(ended.pgid)):
            run.log.write(b"lingering\n")
            return self._concluded(run, "lingering", ended.rc, _unavailable("environment:lingering"))
        if ended.timed_out:
            return self._concluded(run, "timed_out", ended.rc, _refused("expired"))
        if ended.exec_failed or ended.rc != 0:
            return self._concluded(run, "failed", ended.rc, _unavailable("environment:exit"))
        return None

    def _concluded(self, run: _Run, conclusion: Conclusion, rc: int | None, result: AttemptResult | None) -> AttemptResult | None:
        self.ports.store.conclude(run.key, run.run, conclusion, rc, self.ports.clock())
        return result
