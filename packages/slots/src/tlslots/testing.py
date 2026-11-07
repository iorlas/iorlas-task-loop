"""Small stateful recording fakes for slot orchestration."""
import contextlib
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from tlkernel import paths
from tlkernel.bead import Bead
from tlkernel.beadsport import Beads
from tlkernel.config import SlotsConfig
from tlkernel.identity import Identity
from tlkernel.ids import BeadId
from tlkernel.lockenums import LockWhat
from tlkernel.locks import LockRecord
from tlkernel.slots import BranchPinned, Checkout, SlotFail, SlotGitError
from tltestkit.case import Case
from tltestkit.membeads import MemBeads
from tltestkit.memdoc import MemLockTable, MemTickets
from tltestkit.tmpdir import TemporaryDirectory

from tlslots.effects import Effects
from tlslots.env import SlotEnv
from tlslots.host import SlotsHost
from tlslots.pool import Slot, SlotPool

ME = "tl-me"
LIVE_PID = os.getpid()


@dataclass
class Tree:
    branch: str = ""
    head: str = "origin/main"
    dirty: bool = False
    rebasing: bool = False
    cleaned: list[str] = field(default_factory=list)


class FakeSlotGit:
    def __init__(self) -> None:
        self.trees: dict[str, Tree] = {}
        self.branches: set[str] = set()
        self.elsewhere: dict[str, Checkout] = {}  # branch -> the other checkout that holds it
        self.faults: list[tuple[str, SlotGitError]] = []
        self.calls: list[tuple[str, ...]] = []
        self.removed: list[str] = []
        self.added: list[tuple[str, str]] = []

    def tree(self, d: str) -> Tree:
        return self.trees.setdefault(d, Tree())

    def fail(self, op: str, error: SlotGitError, times: int = 1) -> None:
        self.faults += [(op, error)] * times

    def _go(self, op: str, d: str, *args: str) -> Tree:
        self.calls.append((op, d, *args))
        for i, (name, err) in enumerate(self.faults):
            if name == op:
                del self.faults[i]
                raise err
        return self.tree(d)

    def fetch(self, d: str) -> None:
        self._go("fetch", d)

    def rebasing(self, d: str) -> bool:
        return self._go("rebasing", d).rebasing

    def rebase_abort(self, d: str) -> None:
        self._go("rebase_abort", d).rebasing = False

    def dirty(self, d: str) -> bool:
        return self._go("dirty", d).dirty

    def branch(self, d: str) -> str:
        return self._go("branch", d).branch

    def commit_all(self, d: str, branch: str, message: str) -> None:
        t = self._go("commit_all", d, branch, message)
        t.branch = t.branch or branch
        self.branches.add(t.branch)
        t.dirty = False

    def has_branch(self, d: str, branch: str) -> bool:
        self._go("has_branch", d, branch)
        return branch in self.branches

    def checkout(self, d: str, branch: str) -> None:
        t = self._go("checkout", d, branch)
        if branch in self.elsewhere:
            where = self.elsewhere[branch].path
            raise BranchPinned(f"fatal: '{branch}' is already used by worktree at '{where}'", where)
        t.branch, t.head = branch, branch

    def checkout_new(self, d: str, branch: str, start: str) -> None:
        t = self._go("checkout_new", d, branch, start)
        self.branches.add(branch)
        t.branch, t.head = branch, start

    def checkout_detached(self, d: str, ref: str) -> None:
        t = self._go("checkout_detached", d, ref)
        t.branch, t.head = "", ref

    def clean(self, d: str, keep: list[str]) -> None:
        self._go("clean", d).cleaned = list(keep)

    def checkouts(self, d: str) -> list[Checkout]:
        self._go("checkouts", d)
        return [Checkout(path=d, branch=self.tree(d).branch, main=False), *self.elsewhere.values()]

    def remove_worktree(self, repo: str, path: str) -> bool:
        self._go("remove_worktree", repo, path)
        self.removed.append(path)
        self.elsewhere = {b: c for b, c in self.elsewhere.items() if c.path != path}
        return True

    def init_bare(self, d: str, branch: str) -> None:
        self._go("init_bare", d, branch)

    def clone(self, src: str, dst: str) -> None:
        self._go("clone", src, dst)

    def push(self, d: str, remote: str, refspec: str) -> None:
        self._go("push", d, remote, refspec)

    def add_worktree(self, repo: str, path: str, ref: str) -> None:
        self._go("add_worktree", repo, path, ref)
        self.added.append((path, ref))

    def prune_worktrees(self, repo: str) -> None:
        self._go("prune_worktrees", repo)


class Beating(MemBeads):
    """A bead store that records heartbeat attempts, including refused ones."""

    def __init__(self, actor: str = "fake", prefix: str = "fk") -> None:
        super().__init__(actor=actor, prefix=prefix)
        self.beats: list[BeadId] = []

    def heartbeat(self, bead: BeadId) -> None:
        self.beats.append(bead)
        super().heartbeat(bead)


class SlotRig(Case):
    def setup_method(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.git, self.tickets = FakeSlotGit(), MemTickets()
        self.bd = Beating(actor=ME, prefix="sl")
        self.out: list[str] = []
        self.err: list[str] = []
        self.events: list[tuple[str, object]] = []
        self.sleeps: list[float] = []
        self.busy_at: dict[str, str] = {}
        self.t = [1000.0]
        self.env = SlotEnv(
            repo=str(Path(tmp.name) / "repo"), repo_key="r-1", cfg=SlotsConfig(count=2, keep=["ignored"]),
            store=self.bd, git=self.git, tickets=self.tickets,
            cfgdir=paths.ConfigDir(Path(tmp.name)), actor=ME, host="h", take_lock=contextlib.nullcontext,
            busy=lambda d: self.busy_at.get(d, ""), drop_engine_lock=self.drop_engine_lock,
            event=lambda kind, bead="", **kw: self.events.append((kind, kw.get("slot"))), run_setup=lambda cmd, d: 0,
            exclude_local=lambda r: None, say=self.out.append, warn=self.err.append, pid=LIVE_PID, now=lambda: self.t[0],
            sleep=self.sleeps.append)
        self.pool = SlotPool(self.env)
        for n in ("s1", "s2"):
            self.bd.beads[BeadId("sl-" + n)] = Bead(id=BeadId("sl-" + n), title="slot h " + n, status="open", labels=["slot"])
        self.d1 = self.env.dir_of("s1")
        for name in ("s1", "s2"):
            Path(self.env.dir_of(name)).mkdir(parents=True)

    def drop_engine_lock(self, d: str, pid: int | None = None) -> None:
        self.busy_at.pop(d, None)

    def slot(self, name: str = "s1") -> Slot:
        return self.pool.slot(name)

    def code(self, call: Callable[[], object]) -> str:
        try:
            call()
        except SlotFail as err:
            return err.code
        raise AssertionError("expected SlotFail")


Rig = SlotRig


class FakeEffects:
    """Configurable process answers and locks; every capability call is recorded."""

    def __init__(self, host: str = "h", alive: bool = False, start: str = "fake-start") -> None:
        self.host, self.alive, self.start = host, alive, start
        self.processes: dict[object, str] = {}
        self.workers: dict[str, list[str]] = {}
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.locks = MemLockTable(alive=lambda pid: True)
        self.fx = Effects(self.hostname, self.proc_alive, self.proc_start, self.hold_path, self.running_for)

    def hostname(self) -> str:
        self.calls.append(("hostname", ()))
        return self.host

    def proc_alive(self, pid: object, start: str = "") -> bool:
        self.calls.append(("proc_alive", (pid, start)))
        if pid in self.processes:
            return not start or self.processes[pid] == start
        return self.alive

    def proc_start(self, pid: object) -> str:
        self.calls.append(("proc_start", (pid,)))
        return self.processes.get(pid, self.start)

    @contextlib.contextmanager
    def hold_path(self, path: Path | str, holder: str, *, what: LockWhat = LockWhat.LAND,
                  timeout: float | None = None, waiting: Callable[[LockRecord | None], None] | None = None,
                  check: Callable[[], None] | None = None) -> Iterator[LockRecord]:
        self.calls.append(("hold_path", (path, holder, what, timeout)))
        if check is not None:
            check()
        with self.locks.hold(what, str(path), holder, timeout=timeout, waiting=waiting) as rec:
            yield rec

    def running_for(self, bead: str) -> list[str]:
        self.calls.append(("running_for", (bead,)))
        return list(self.workers.get(bead, []))


class FakeSlotsHost:
    """Machine capabilities over an independent bead store, tickets and clock."""

    def __init__(self, store: Beads | None = None, *, host: str = "fakehost", repo: str = "/repo",
                 peek: Callable[[Beads, BeadId], Bead | None] | None = None) -> None:
        self.store = store if store is not None else MemBeads()
        self.repo, self.t = repo, 1.0
        self.effects, self.ticket_store = FakeEffects(host), MemTickets()
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.events: list[tuple[Identity, str, str, dict[str, object]]] = []
        self.host = SlotsHost(bd=self.bd, peek=peek or self.peek, repo_root=self.repo_root,
                              hostname=self.effects.hostname, os_lock=self.os_lock, event=self.event,
                              tickets=self.tickets, now=self.now, fx=self.effects.fx)

    def bd(self, actor: str, repo: str) -> Beads:
        self.calls.append(("bd", (actor, repo)))
        return self.store

    def peek(self, store: Beads, bead: BeadId) -> Bead | None:
        self.calls.append(("peek", (bead,)))
        return store.show(bead)

    def repo_root(self) -> str:
        self.calls.append(("repo_root", ()))
        return self.repo

    def os_lock(self, path: Path | str, holder: str) -> contextlib.AbstractContextManager[LockRecord]:
        return self.effects.hold_path(path, holder)

    def event(self, by: Identity, kind: str, bead: str = "", **fields: object) -> None:
        self.events.append((by, kind, bead, fields))

    def tickets(self, cfg: paths.ConfigDir) -> MemTickets:
        self.calls.append(("tickets", (cfg,)))
        return self.ticket_store

    def now(self) -> float:
        self.calls.append(("now", ()))
        return self.t
