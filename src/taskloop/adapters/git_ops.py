"""What a task's land, its close and its checks ask of git beyond the slot's life: counts, the unmerged paths, the writes that read git's
words (commit, push, rebase --continue), and the rest of the staged-work and branch moves. RealGit (git.py) adds the rest."""

from typing import Self

from taskloop.adapters.git_base import GitBase, classify
from taskloop.contracts.gitfacts import GitOutcome

PUSH_WALL_S = 3600.0  # a push (or an LFS upload) that has not ended after this long is a failure with these words


class LandGit(GitBase):
    def unpinned(self) -> Self:
        """The same port asked as a worker's or a check's git would see the folder (no pin): for whether the pin itself is right."""
        return type(self)(self.env, self.sleep, pinned=False)

    def count(self, d: str, include: list[str], exclude: list[str] | None = None) -> int:
        out = self._must(d, "rev-list", "--count", *include, *(f"^{x}" for x in exclude or []))
        return int(out) if out.isdigit() else 0

    def unmerged(self, d: str) -> list[str]:
        return [p for p in self._ask(d, "diff", "--name-only", "--diff-filter=U").splitlines() if p]

    def changed_paths(self, d: str, a: str, b: str) -> list[str]:
        r = self._run(d, "diff", "--name-only", a, b)
        return [p for p in r.stdout.splitlines() if p] if r.returncode == 0 else []

    def staged(self, d: str) -> bool:
        return self._run(d, "diff", "--cached", "--quiet").returncode != 0

    def stage_literal(self, d: str, paths: list[str]) -> None:
        """Stage exactly these paths (as given, no globbing; a deleted one stages its deletion), however many there are."""
        if not paths:
            return
        r = self._run(d, "--literal-pathspecs", "add", "-A", "--pathspec-from-file=-", "--pathspec-file-nul", stdin="\0".join(paths))
        if r.returncode != 0:
            raise classify(r.stderr or r.stdout)

    def rename_branch(self, d: str, old: str, new: str) -> None:
        self._must(d, "branch", "-m", old, new)

    def checkout_reset(self, d: str, branch: str, start: str) -> None:
        self._must(d, "checkout", "-q", "-B", branch, start)

    def try_commit(self, d: str, message: str, verify: bool = True, allow_empty: bool = False) -> GitOutcome:
        opts = [*([] if verify else ["--no-verify"]), *(["--allow-empty"] if allow_empty else [])]
        return self._try(d, "commit", "-q", *opts, "-m", message)

    def amend(self, d: str) -> None:
        self._must(d, "commit", "-q", "--no-verify", "--amend", "--no-edit")

    def rebase_continue(self, d: str) -> GitOutcome:
        return self._try(d, "-c", "core.editor=true", "rebase", "--continue")

    def push_lease(self, d: str, remote: str, refspec: str) -> GitOutcome:
        return self._try(d, "push", "--no-verify", "--force-with-lease", remote, refspec, timeout=PUSH_WALL_S)

    def lfs_push(self, d: str, remote: str, refs: list[str]) -> GitOutcome:
        return self._try(d, "lfs", "push", remote, *refs, timeout=PUSH_WALL_S)
