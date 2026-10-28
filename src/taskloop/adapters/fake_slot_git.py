"""FakeSlotGit: a slot's git in memory, with faults to inject. `fail(op, error, times=1)` makes the next `times` calls of `op`
raise `error` before they change anything, so a test walks every typed failure of a slot reset in microseconds."""
from dataclasses import dataclass, field

from taskloop.contracts.slots import BranchPinned, Checkout, SlotGitError


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

    def add_worktree(self, repo: str, path: str, ref: str) -> None:
        self._go("add_worktree", repo, path, ref)
        self.added.append((path, ref))
