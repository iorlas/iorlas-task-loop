"""The slot's checkout as git sees it: the base, a fetch, what is dirty, the tree git would commit now, what the task changed,
what to stage."""

from typing import Protocol

from taskloop.adapters import treehash
from taskloop.contracts.gitfacts import StatusRow
from taskloop.contracts.ids import TreeSha
from taskloop.contracts.ports import Git
from taskloop.contracts.slots import SlotGitError
from taskloop.stores.runlog import RunLog


class CheckoutConfig(Protocol):
    @property
    def base(self) -> str: ...


class CheckoutNewFiles(Protocol):
    def new_file_kind(self, path: str) -> str: ...


class CheckoutHost(Protocol):
    """What the checkout reads of the engine: the slot's path, git, the base, the log, the new-file verdicts and the memo
    of the last tree hash (which it sets)."""

    tree_memo: tuple[treehash.State, TreeSha] | None  # (git status, file stats) -> tree hash, of the last tree_hash()

    @property
    def wt(self) -> str: ...
    @property
    def git(self) -> Git: ...
    @property
    def cfg(self) -> CheckoutConfig: ...
    @property
    def log(self) -> RunLog: ...
    @property
    def newfiles(self) -> CheckoutNewFiles: ...
    def blocked_for(self, why: str, kind: str) -> Exception: ...


def line(r: StatusRow) -> str:
    """One path as `git status --porcelain` prints it."""
    return f"{r.index}{r.work} {r.path}"


class Checkout:
    def __init__(self, host: CheckoutHost) -> None:
        self.e = host

    def slot_status(self) -> tuple[list[str], list[str], str]:
        """(tracked paths changed, untracked paths, git's complaint or "") from the slot's own `git status`."""
        try:
            rows = self.e.git.status(self.e.wt, all_untracked=True)
        except SlotGitError as err:
            return [], [], str(err)
        return [r.path for r in rows if not r.untracked], [r.path for r in rows if r.untracked], ""

    def fetch(self, check: bool = False) -> tuple[int, str]:
        """git fetch (the port goes again while it loses a ref lock to another process's fetch into this repo). -> (0, "") or (1, why)."""
        e = self.e
        try:
            e.git.fetch(e.wt)
        except SlotGitError as err:
            if check:
                raise e.blocked_for(f"failed: `git fetch -q origin`: {err}", "FAULT_INFRA") from err
            return 1, str(err)
        return 0, ""

    def base_sha(self) -> str:
        """Where the task's work starts: an earlier run's commits on the task branch count as the task's diff."""
        e = self.e
        return e.git.merge_base(e.wt, e.cfg.base, "HEAD") or e.cfg.base

    def branch_now(self) -> str:
        """The branch HEAD is on; "" when detached."""
        return self.e.git.branch(self.e.wt)

    def dirty_status(self) -> str:
        """`git status --porcelain` of the slot, leaving out what the BASE's .gitignore files ignore (tl-g6a): Unity's client/log.txt
        is untracked on an old branch and ignored on main, and made a slot 'dirty with another branch's work' for 7 beads."""
        rows = self.e.git.status(self.e.wt, all_untracked=True)
        if not rows:
            return ""
        ignored = self.base_ignored([r.path for r in rows if r.untracked])
        return "\n".join(line(r) for r in rows if not (r.untracked and r.path in ignored))

    def base_ignored(self, paths: list[str]) -> set[str]:
        """The subset of `paths` that the BASE's .gitignore files ignore (the user's own global excludes are not replaced)."""
        if not paths:
            return set()
        e = self.e
        base = e.cfg.base
        files = {
            t.path: self.read_base(base, t.path).splitlines()
            for t in e.git.ls_tree(e.wt, base, recursive=True)
            if t.path.split("/")[-1] == ".gitignore"
        }
        rules = treehash.ignore_rules(base, files)
        return treehash.ignored_by(e.git, e.wt, rules, paths) if rules else set()

    def read_base(self, base: str, path: str) -> str:
        try:
            return self.e.git.show(self.e.wt, base, path)
        except SlotGitError:
            return ""

    def stage_all(self, check: bool = False, everything: bool = False) -> int:
        """Stage the slot's own changes: exactly the paths `git status --porcelain` lists under the pinned env, never a
        bare `git add -A` (tl-bxk.10.12). Tracked changes always; an untracked file only when a stage meant it
        (new_file_kind, tl-bxk.10.24). Returns the exit code."""
        e = self.e
        e.log.note("git add -A (the slot's own status paths)")
        paths, new, why = self.slot_status()
        if everything:  # a parked bead's work: every new file the base does not ignore goes to its branch, the unexplained ones too
            ignored = self.base_ignored(new)
            paths += [p for p in new if p not in ignored]
        else:
            paths += [p for p in new if e.newfiles.new_file_kind(p) == "meant"]
        if not why and paths:
            try:
                e.git.stage_literal(e.wt, paths)
            except SlotGitError as err:
                why = str(err)
        if check and why:
            raise e.blocked_for(f"failed: staging the slot's paths: {why[-600:]}", "FAULT_SLOT")
        return 1 if why else 0

    def tree_hash(self) -> TreeSha:
        """The worktree as git would commit it now, untracked files included, without touching the real index."""
        e = self.e
        state = treehash.state_of(e.git, e.wt)
        memo = e.tree_memo
        if state and memo and memo[0] == state:
            return memo[1]
        tree = treehash.tree_of(e.git, e.wt)
        if state:
            e.tree_memo = (state, tree)
        return tree

    def task_diff(self) -> str:
        """The task's diff against where it started, untracked files included."""
        e = self.e
        tree = self.tree_hash()
        return e.git.diff(e.wt, self.base_sha(), tree) if tree else ""

    def changed_paths(self) -> list[str]:
        """Paths the task changed since it started, untracked files included."""
        tree = self.tree_hash()
        return self.e.git.changed_paths(self.e.wt, self.base_sha(), tree) if tree else []
