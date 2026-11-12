"""The checks block (tl-8bh9.14.6 section 7): every check of the profile at X run once, in profile order, required or not,
on the host in a slot detached at X; each result recorded through a `ResultSink` before its command starts and after it
ends. Also the two readings of a block's results the checks entry needs: whether the latest block completed (it is never
run again) and the conclusion it gives.

Before the first command, each stored required name the profile at X does not define gets an `undefined` result. Per
check: its log opened (`check-<block>-<name>.log`, capped), its result started with its argv digest and timeout, the
command run through the registered start (its identity committed before it executes) in the slot with `env`, for
`min(timeout, deadline - now)`. After every end, whatever it was: a process left (the stop's survivors, or its group
still alive) is `lingering` and stops the block; then the slot, through its pinned view, must be at X detached with no
tracked change (untracked files are listed in the log only), else `dirty`, which stops the block; then the deadline's
stop is `interrupted` (the attempt expires), its own timeout `timed_out`, a failed exec or a non-zero exit `failed`,
exit 0 `passed`. A start that may have run is not judged: its identity is stored and the next entry reconciles it. Never
signals anything; no Git write. The block knows no checks attempt: the sink binds the record (`CheckSink` for a checks
attempt; land validates its candidate with the same block and its own record).
"""

import hashlib
import json
import shlex
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, Protocol

from git_porcelain import GitUnavailable, Repo
from stream_proc import OwnedProcess

from taskloop.access import folders
from taskloop.attempt_types import AttemptKey, AttemptResult
from taskloop.check_store import CheckStore, Conclusion, Outcome, Required, ResultRow
from taskloop.environment import GroupAlive, SetupEnded, SetupProcess, setup_env
from taskloop.evidence_files import CappedLog, EvidenceFiles
from taskloop.prepare import MAIN
from taskloop.profile import Check
from taskloop.slot_state import bounded

TERMINAL: Final[tuple[Conclusion, ...]] = ("passed", "failed", "timed_out", "undefined")
STOPPING: Final[tuple[Conclusion, ...]] = ("lingering", "dirty")  # the block stops; the attempt fails with this result
type _Next = Literal["next", "stopped"]


def argv_digest(argv: Sequence[str]) -> str:
    """sha256 of one argv as compact JSON (`environment.setup_digest`'s rule on one argv)."""
    return hashlib.sha256(json.dumps(list(argv), separators=(",", ":")).encode()).hexdigest()


def check_env(scrubbed: Mapping[str, str], slot: Path) -> dict[str, str]:
    """What every check command gets: the scrubbed environment with the push bar (`agent_credentials.scrubbed`), the
    person's HOME, and the slot's folders (`TMPDIR`, uv's cache and tools); no `UV_OFFLINE`: checks have host networking."""
    return setup_env(scrubbed, folders(slot))


def main_seen(view: Repo) -> str | None:
    """`main`'s commit as read now (the target is compared with it before and after a block: `main_moved`); None when
    the branch is gone."""
    return next((entry.sha for entry in view.refs([MAIN]) if entry.name == MAIN), None)


class ResultSink(Protocol):
    """Where one block's results go: a record bound to its owner (and its clock), and each check's log."""

    def start(self, block: int, position: int, name: str, argv_digest: str, timeout: int) -> None: ...

    def registered(self, block: int, position: int, process: OwnedProcess) -> None:
        """The command's identity, committed before it executes."""
        ...

    def conclude(self, block: int, position: int, conclusion: Conclusion, rc: int | None) -> None: ...

    def undefined(self, block: int, position: int, name: str) -> None: ...

    def log(self, block: int, name: str) -> CappedLog:
        """The check's log, opened for append; OSError when it cannot be."""
        ...


@dataclass(frozen=True)
class CheckSink:
    """The `ResultSink` of a checks attempt: its fenced `CheckStore` writes under its key (a result's conclusion is the
    store's `finish`), and its evidence directory's check logs."""

    store: CheckStore
    key: AttemptKey
    files: EvidenceFiles
    clock: Callable[[], float]

    def start(self, block: int, position: int, name: str, argv_digest: str, timeout: int) -> None:
        self.store.start(self.key, block, position, name, argv_digest, timeout, self.clock())

    def registered(self, block: int, position: int, process: OwnedProcess) -> None:
        self.store.registered(self.key, block, position, process)

    def conclude(self, block: int, position: int, conclusion: Conclusion, rc: int | None) -> None:
        self.store.finish(self.key, block, position, conclusion, rc, self.clock())

    def undefined(self, block: int, position: int, name: str) -> None:
        self.store.undefined(self.key, block, position, name, self.clock())

    def log(self, block: int, name: str) -> CappedLog:
        return self.files.open_check_log(self.key, block, name)


@dataclass(frozen=True)
class BlockTarget:
    """What one block validates: the slot detached at `commit` (X) and its Git view pinned to the slot's verified Git
    directory, the stored required names (with their argv digests at the target), the deadline, the commands' env."""

    slot: Path
    view: Repo
    commit: str
    required: Required
    deadline: float
    env: Mapping[str, str]


@dataclass(frozen=True)
class BlockPorts:
    process: SetupProcess  # the registered start (real: `slot_env.setup_process`)
    lingering: GroupAlive
    clock: Callable[[], float]


def _refused(reason: str) -> AttemptResult:
    return AttemptResult("refused", reason)


def _unavailable(reason: str) -> AttemptResult:
    return AttemptResult("unavailable", reason)


def _ending(ended: SetupEnded, own: bool) -> bytes:
    """The factory's frame line after a command; `own`: its own timeout, not the deadline, bounded it."""
    if ended.timed_out:
        return b"timed out\n" if own else b"stopped at the deadline\n"
    if ended.exec_failed:
        return b"not started\n"
    return b"ended by a signal\n" if ended.rc is None else f"exit {ended.rc}\n".encode()


class Block:
    def __init__(self, ports: BlockPorts) -> None:
        self.ports = ports

    def run(self, target: BlockTarget, sink: ResultSink, block: int, checks: Sequence[Check]) -> AttemptResult | None:
        """Block `block` over the profile's `checks` at X. None when it ended (every check ran, or a `lingering` or
        `dirty` result stopped it): its results decide (`conclusion`). Otherwise the attempt's word: `refused
        expired:<name>` (the deadline reached before or during that check), `unavailable checks:uncertain`, `git` (the
        slot unreadable after a check; its result stays unfinished for the reconcile) or `log` (the artifacts directory)."""
        defined = {check.name for check in checks}
        missing = [name for name, _ in target.required if name not in defined]
        for offset, name in enumerate(missing):
            sink.undefined(block, len(checks) + offset, name)
        try:
            for position, check in enumerate(checks):
                step = self._check(target, sink, (block, position), check)
                if step != "next":
                    return None if step == "stopped" else step
        except GitUnavailable:
            return _unavailable("git")
        return None

    def _check(self, target: BlockTarget, sink: ResultSink, at: tuple[int, int], check: Check) -> AttemptResult | _Next:
        block, position = at
        remaining = target.deadline - self.ports.clock()
        if remaining <= 0:
            return _refused(f"expired:{check.name}")
        try:
            log = sink.log(block, check.name)
        except OSError:
            return _unavailable("log")  # the artifacts directory cannot be written
        with closing(log):
            sink.start(block, position, check.name, argv_digest(check.argv), check.timeout)
            log.write(f"$ {shlex.join(check.argv)}\n".encode())
            own = check.timeout < remaining
            ended = self._started(target, sink, at, check.argv, min(check.timeout, remaining), log)
            if ended.uncertain:  # the identity is stored; the next entry reconciles it
                log.write(b"start uncertain\n")
                return _unavailable("checks:uncertain")
            log.write(_ending(ended, own))
            judged = self._judged(target, ended, own, log)
            sink.conclude(block, position, judged, ended.rc)
        if judged == "interrupted":
            return _refused(f"expired:{check.name}")
        return "stopped" if judged in STOPPING else "next"

    def _started(self, target: BlockTarget, sink: ResultSink, at: tuple[int, int], argv: Sequence[str], wall: float,
                 log: CappedLog) -> SetupEnded:
        """The registered start; a supervision failure after registration is an end of unknown kind (its group is still
        judged), one before it a command that never ran."""
        committed: list[OwnedProcess] = []

        def registered(process: OwnedProcess) -> None:
            sink.registered(*at, process)
            committed.append(process)

        try:
            return self.ports.process(argv, registered=registered, cwd=str(target.slot), env=target.env, timeout=wall, line=log.write)
        except OSError:
            if not committed:
                return SetupEnded(None, False, True, 0)
            log.write(b"ended uncertainly\n")
            return SetupEnded(None, False, False, committed[0].pgid)

    def _judged(self, target: BlockTarget, ended: SetupEnded, own: bool, log: CappedLog) -> Conclusion:
        """Section 7 steps 4-6 for a command that ended."""
        if not ended.exec_failed and (ended.survivors or self.ports.lingering(ended.pgid)):
            log.write(b"lingering\n")
            return "lingering"
        if not ended.exec_failed and _dirty(target, log):
            log.write(b"dirty\n")
            return "dirty"
        if ended.timed_out:
            return "timed_out" if own else "interrupted"
        return "passed" if not ended.exec_failed and ended.rc == 0 else "failed"


def _dirty(target: BlockTarget, log: CappedLog) -> bool:
    """Through the pinned view: HEAD not X, a branch checked out, or a tracked change (staged or not). Untracked files
    are not `dirty` (the next block's reset removes them): each is listed in the log, at most 50, then a count."""
    listed = next((info for info in target.view.worktrees() if info.path == target.slot), None)
    found = target.view.worktree(target.slot).dirty()
    for line in bounded(found.untracked):
        log.write(f"untracked: {line}\n".encode())
    return listed is None or (listed.head, listed.branch) != (target.commit, None) or bool(found.tracked)


def completed(results: Sequence[ResultRow], checks: Sequence[Check], required: Required) -> bool:
    """A latest block that is never run again: one of its results stopped it (`lingering`, `dirty`), or every check at X
    and every undefined required name has a terminal result. An `interrupted` or unfinished result, or a missing name,
    means the block repeats whole."""
    if any(row.conclusion in STOPPING for row in results):
        return True
    defined = {check.name for check in checks}
    expected = defined | {name for name, _ in required if name not in defined}
    finished = {row.name for row in results if row.conclusion in TERMINAL}
    return bool(results) and expected <= finished


def conclusion(results: Sequence[ResultRow], required: Required) -> tuple[Outcome, str | None]:
    """The checks attempt's conclusion from its latest block: a stopping result fails it with that result
    (`<name>:lingering|dirty`, required or not); else `passed` when every required name passed, else `failed` with the
    first required name (the target's order) that did not: `<name>:<conclusion>`, or `<name>:not_run`."""
    stopping = next((row for row in results if row.conclusion in STOPPING), None)
    if stopping is not None:
        return "failed", f"{stopping.name}:{stopping.conclusion}"
    found = {row.name: row.conclusion for row in results}
    failing = next((name for name, _ in required if found.get(name) != "passed"), None)
    return ("passed", None) if failing is None else ("failed", f"{failing}:{found.get(failing) or 'not_run'}")


def differs(required: Required, row: ResultRow) -> bool:
    """A required check whose argv at X differs from the one stored from the target (`tl step show` marks it)."""
    stored = dict(required).get(row.name)
    return stored is not None and row.argv_digest is not None and row.argv_digest != stored
