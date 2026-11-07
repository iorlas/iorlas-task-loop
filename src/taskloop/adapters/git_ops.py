"""What a task's land, its close and its checks ask of git beyond the slot's life: counts, the unmerged paths, the writes that read git's
words (commit, push, rebase --continue), and the rest of the staged-work and branch moves. RealGit (git.py) adds the rest."""

from functools import partial
from pathlib import Path
from typing import Self

from git_porcelain.real import RealRepo

from taskloop.adapters.git_base import GitBase, classify
from taskloop.adapters.git_pool import pool_errors, pool_read_error, remote_error
from tlkernel.gitfacts import DiffEntry, GitOutcome
from tlkernel.slots import GitReadFailure, MissingRevision, SlotGitError

PUSH_WALL_S = 3600.0  # a push (or an LFS upload) that has not ended after this long is a failure with these words


class LandGit(GitBase):
    def _pool(self, d: str) -> RealRepo:
        raise NotImplementedError

    def profile_diff(self, d: str, base: str, tip: str) -> str:
        """Preserve the complete patch text used by the owner's audit and the pre-push judge."""
        return self._read(d, "diff", "--no-ext-diff", "--no-textconv", base, tip, "--", ".task-loop.json")

    def unpinned(self) -> Self:
        """The same port asked as a worker's or a check's git would see the folder (no pin): for whether the pin itself is right."""
        return type(self)(self.env, self.sleep, pinned=False)

    def count(self, d: str, include: list[str], exclude: list[str] | None = None) -> int:
        if not include:
            # history([]) defaults to HEAD; rev-list has no default positive revision.
            out = self._must(d, "rev-list", "--count", *(f"^{x}" for x in exclude or []))
            return int(out) if out.isdigit() else 0
        with pool_errors():
            return len(self._pool(d).history(include, not_on=exclude or []))

    def unmerged(self, d: str) -> list[str]:
        with pool_errors(pool_read_error):
            return list(self._pool(d).worktree(Path(d).resolve()).unmerged())

    def changed_paths(self, d: str, a: str, b: str, *, required: bool = False) -> list[str]:
        return self._diff_paths(d, a, b, "--name-only", required=required)

    def _diff_paths(self, d: str, a: str, b: str, *opts: str, required: bool) -> list[str]:
        try:
            return self._paths(d, "diff", "--no-ext-diff", *opts, "-z", a, b)
        except MissingRevision:
            if required:
                raise
            return []

    def _paths(self, d: str, *args: str) -> list[str]:
        out = self._read(d, *args)
        if out and not out.endswith("\0"):
            raise GitReadFailure(f"git {args[0]}: incomplete path record")
        fields = out.split("\0")[:-1]
        if any(not field for field in fields):
            raise GitReadFailure(f"git {args[0]}: empty path record")
        return fields

    def diff_entries(self, d: str, a: str, b: str, ignore_space: bool = False, *, required: bool = False) -> list[DiffEntry]:
        space = ["-w", "--ignore-blank-lines"] if ignore_space else []
        fields = self._diff_paths(d, a, b, "--name-status", "-M100%", *space, required=required)
        out: list[DiffEntry] = []
        words = iter(fields)
        for status in words:
            if status not in ("A", "D", "M", "T", "R100"):
                raise GitReadFailure("git diff: malformed status record")
            if status[0] == "R":
                old, new = next(words, ""), next(words, "")
                if not old or not new:
                    raise GitReadFailure("git diff: incomplete rename record")
                out.append(DiffEntry(status="R", path=new, old=old))
            else:
                path = next(words, "")
                if not path:
                    raise GitReadFailure("git diff: incomplete path record")
                out.append(DiffEntry(status=status[0], path=path))
        if ignore_space:
            out = [e for e in out if e.status != "M" or self._space_changes(d, a, b, e.path)]
        return out

    def _space_changes(self, d: str, a: str, b: str, path: str) -> bool:
        """Older git still lists a whitespace-only edit as M under -w; the path's own -w diff decides, whatever the version."""
        return not self._predicate(d, "diff", "--no-ext-diff", "--quiet", "-w", "--ignore-blank-lines", a, b, "--", path)

    def staged(self, d: str) -> bool:
        return not self._predicate(d, "diff", "--cached", "--quiet")

    def staged_paths(self, d: str) -> list[str]:
        return self._paths(d, "diff", "--cached", "--no-ext-diff", "--name-only", "--diff-filter=ACMRT", "-z")

    def export_index(self, d: str, dest: str) -> None:
        """Lay the index over the checkout at `dest` (a worktree of HEAD): staged content in, staged deletions out."""
        self._must(d, "checkout-index", "-a", "-f", f"--prefix={dest.rstrip('/')}/")
        for gone in self._paths(d, "diff", "--cached", "--no-ext-diff", "--name-only", "--diff-filter=D", "-z"):
            Path(dest, gone).unlink(missing_ok=True)

    def stage_literal(self, d: str, paths: list[str]) -> None:
        """Stage exactly these paths (as given, no globbing; a deleted one stages its deletion), however many there are."""
        if not paths:
            return
        r = self._run(d, "--literal-pathspecs", "add", "-A", "--pathspec-from-file=-", "--pathspec-file-nul", stdin="\0".join(paths))
        if r.returncode != 0:
            raise classify(r.stderr or r.stdout)

    def rename_branch(self, d: str, old: str, new: str) -> None:
        with pool_errors():
            self._pool(d).rename_branch(old, new)

    def try_commit(self, d: str, message: str, verify: bool = True, allow_empty: bool = False) -> GitOutcome:
        # record() has no complete stdout+stderr for hook refusals, empty index, or successful hooks.
        opts = [*([] if verify else ["--no-verify"]), *(["--allow-empty"] if allow_empty else [])]
        return self._try(d, "commit", "-q", *opts, "-m", message)

    def amend(self, d: str) -> None:
        # record(amend) replaces unborn-HEAD refusal with ValueError and truncates other diagnostics.
        self._must(d, "commit", "-q", "--no-verify", "--amend", "--no-edit")

    def rebase_continue(self, d: str) -> GitOutcome:
        with pool_errors():
            result = self._pool(d).worktree(Path(d).resolve()).continue_rebase()
        return GitOutcome(ok=result.ok, output=result.output)

    def push_lease(self, d: str, remote: str, refspec: str, expect_sha: str) -> GitOutcome:
        src, colon, dst = refspec.partition(":")
        if not colon or not dst or src.startswith("+"):
            raise SlotGitError(f"a lease push needs SRC:DST without '+', got {refspec!r}")
        with pool_errors(partial(remote_error, push=True)):
            done = self._pool(d).worktree(Path(d).resolve()).push_request(
                remote, [refspec], options=[f"--force-with-lease={dst}:{expect_sha}"] if expect_sha else [], timeout=PUSH_WALL_S)
        return GitOutcome(ok=done.ok, output=done.output)

    def lfs_push(self, d: str, remote: str, refs: list[str]) -> GitOutcome:
        with pool_errors(remote_error):
            done = self._pool(d).worktree(Path(d).resolve()).lfs_push(remote, refs, timeout=PUSH_WALL_S)
        return GitOutcome(ok=done.ok, output=done.output)
