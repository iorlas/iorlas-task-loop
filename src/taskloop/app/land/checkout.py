"""The slot's checkout as git sees it: the base, a fetch, what is dirty, the tree git would commit now, what the task changed,
what to stage."""
import time
from typing import Any

from taskloop.adapters import gitrepo, treehash
from taskloop.adapters.gitenv import git_env, run_git
from taskloop.contracts.ids import TreeSha


class Checkout:
    def __init__(self, host: Any) -> None:
        self.e = host

    def slot_status(self) -> tuple[list[str], list[str], Any]:
        """(tracked paths changed, untracked paths, git's result) from the slot's own `git status`."""
        st = run_git(self.e.wt, "status", "--porcelain", "-z", "--untracked-files=all", capture_output=True)
        parts = st.stdout.decode("utf-8", "surrogateescape").split("\0")
        paths: list[str] = []
        new: list[str] = []
        k = 0
        while k < len(parts):
            entry = parts[k]
            k += 1
            if len(entry) > 3:
                (new if entry[:2] == "??" else paths).append(entry[3:])
                if entry[0] in "RC":  # the next entry is the path it came from: gone from the tree, staged already
                    k += 1
        return paths, new, st

    def fetch(self, check: bool = False) -> tuple[int, str]:
        """git fetch, again while it loses a ref lock to another process's fetch into this repo (gitrepo.REF_RACE)."""
        e = self.e
        for i in range(5):
            rc, tail = e.sh(["git", "fetch", "-q", "origin"], pin=True)
            if rc == 0 or not gitrepo.REF_RACE.search(tail):
                break
            time.sleep(0.1 * (i + 1))
        if check and rc:
            raise e.blocked_for(f"failed: `git fetch -q origin` exit {rc}\n{tail}", "FAULT_INFRA")
        return rc, tail

    def git_env(self) -> dict[str, str]:
        """The environment for a git command on this checkout (pinned to it)."""
        return git_env(self.e.wt)

    def base_sha(self) -> str:
        """Where the task's work starts: an earlier run's commits on the task branch count as the task's diff."""
        e = self.e
        return str(e.git("merge-base", e.cfg.base, "HEAD") or e.cfg.base)

    def branch_now(self) -> str:
        """The branch HEAD is on; "" when detached."""
        return str(self.e.git("symbolic-ref", "--short", "-q", "HEAD"))

    def dirty_status(self) -> str:
        """`git status --porcelain` of the slot, leaving out what the BASE's .gitignore files ignore (tl-g6a): Unity's client/log.txt
        is untracked on an old branch and ignored on main, and made a slot 'dirty with another branch's work' for 7 beads."""
        out = self.e.git("status", "--porcelain", "--untracked-files=all")
        if not out:
            return ""
        lines = out.splitlines()
        untracked = [ln[3:] for ln in lines if ln.startswith("?? ")]
        ignored = self.base_ignored(untracked)
        return "\n".join(ln for ln in lines if not (ln.startswith("?? ") and ln[3:] in ignored))

    def base_ignored(self, paths: list[str]) -> set[str]:
        """The subset of `paths` that the BASE's .gitignore files ignore (the user's own global excludes are not replaced)."""
        if not paths:
            return set()
        e = self.e
        base = e.cfg.base
        files = {str(p): str(e.git("show", f"{base}:{p}") or "").splitlines()
                 for p in (e.git("ls-tree", "-r", "--name-only", base) or "").splitlines() if p.split("/")[-1] == ".gitignore"}
        rules = treehash.ignore_rules(base, files)
        return treehash.ignored_by(e.wt, rules, paths) if rules else set()

    def stage_all(self, check: bool = False, everything: bool = False) -> int:
        """Stage the slot's own changes: exactly the paths `git status --porcelain` lists under the pinned env, never a
        bare `git add -A` (tl-bxk.10.12). Tracked changes always; an untracked file only when a stage meant it
        (new_file_kind, tl-bxk.10.24). Returns the exit code."""
        e = self.e
        e.log.note("git add -A (the slot's own status paths)")
        paths, new, st = self.slot_status()
        if everything:  # a parked bead's work: every new file the base does not ignore goes to its branch, the unexplained ones too
            ignored = self.base_ignored(new)
            paths += [p for p in new if p not in ignored]
        else:
            paths += [p for p in new if e.newfiles.new_file_kind(p) == "meant"]
        rc = st.returncode
        if rc == 0 and paths:
            r = run_git(e.wt, "--literal-pathspecs", "add", "-A", "--pathspec-from-file=-", "--pathspec-file-nul",
                        input="\0".join(paths).encode("utf-8", "surrogateescape"), capture_output=True)
            rc = r.returncode
            st = r
        if check and rc:
            raise e.blocked_for(f"failed: staging the slot's paths exit {rc}\n{st.stderr.decode('utf-8', 'replace')[-600:]}", "FAULT_SLOT")
        return rc

    def tree_hash(self) -> TreeSha:
        """The worktree as git would commit it now, untracked files included, without touching the real index."""
        e = self.e
        state = treehash.state_of(e.wt)
        memo = e.tree_memo
        if state and memo and memo[0] == state:
            return TreeSha(memo[1])
        tree = treehash.tree_of(e.wt)
        if state:
            e.tree_memo = (state, tree)
        return tree

    def task_diff(self) -> str:
        """The task's diff against where it started, untracked files included."""
        e = self.e
        tree = self.tree_hash()
        return str(gitrepo.git("diff", self.base_sha(), tree, cwd=e.wt) if tree else e.git("diff", self.base_sha()))

    def changed_paths(self) -> list[str]:
        """Paths the task changed since it started, untracked files included."""
        tree = self.tree_hash()
        out = gitrepo.git("diff", "--name-only", self.base_sha(), tree, cwd=self.e.wt) if tree else ""
        return [p for p in out.splitlines() if p]
