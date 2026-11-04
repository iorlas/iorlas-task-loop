"""Git (the port in contracts/ports.py) on the real git binary, pinned to the checkout. git's words are read here and nowhere else:
a failure becomes one of the typed SlotGitErrors (BranchPinned, DirtyTree, RefRace, IndexLocked) or the plain SlotGitError."""
import os
from contextlib import suppress
from pathlib import Path
from typing import Literal, override

from git_porcelain.api import BranchHeld, Recorded, Sha
from git_porcelain.errors import GitError, WorktreeRemoveRefused
from git_porcelain.real import RealRepo

from taskloop.adapters.git_base import classify, real_checkout
from taskloop.adapters.git_ops import LandGit
from taskloop.adapters.git_pool import UnpinnedRepo, pool_error, pool_read_error
from taskloop.contracts.gitfacts import ConfigEntry, GitOutcome, GrepHit, LogRow, Pick, Ref, StatusRow, TreeEntry
from taskloop.contracts.slots import BranchPinned, Checkout, GitReadFailure, MissingRevision, NotARepo, NotAWorktree, RefRace, SlotGitError

FETCH_TRIES = 5


class RealGit(LandGit):
    def fetch(self, d: str) -> None:
        """`git fetch -q origin`, again while it loses a ref lock to a concurrent fetch (worktrees share refs/remotes)."""
        for i in range(FETCH_TRIES):
            r = self._run(d, "fetch", "-q", "origin")
            if r.returncode == 0:
                return
            err = classify(r.stderr)
            if not isinstance(err, RefRace) or i == FETCH_TRIES - 1:
                raise err
            self.sleep(0.1 * (i + 1))

    def rebasing(self, d: str) -> bool:
        try:
            return self._pool(d).worktree(real_checkout(d)).rebasing()
        except GitError as err:
            raise pool_read_error(err) from err

    def rebase_abort(self, d: str) -> None:
        try:
            self._pool(d).worktree(real_checkout(d)).abort_rebase(missing_ok=False)
        except GitError as err:
            raise pool_error(err) from err

    def dirty(self, d: str) -> bool:
        try:
            return self._pool(d).worktree(real_checkout(d)).dirty().raw
        except GitError as err:
            raise pool_read_error(err) from err

    @override
    def _pool(self, d: str) -> RealRepo:
        repo = RealRepo if self.pinned else UnpinnedRepo
        return repo(real_checkout(d), env=self.git_env(d), memoize=False, sleep=self.sleep)

    def branch(self, d: str) -> str:
        return self._ask(d, "symbolic-ref", "--short", "-q", "HEAD", missing=True)

    def symbolic_ref(self, d: str, ref: str) -> str:
        return self._ask(d, "symbolic-ref", "-q", ref, missing=True)

    def commit_all(self, d: str, branch: str, message: str) -> None:
        if not self.branch(d):
            # take_branch(resume) accepts an existing branch; this must refuse to overwrite a checkpoint.
            self.checkout_new(d, branch, "HEAD")
        try:
            result = self._pool(d).worktree(real_checkout(d)).record(message, paths="all", hooks=False)
        except GitError as err:
            raise pool_error(err) from err
        if not isinstance(result, Recorded):
            raise SlotGitError("nothing to commit")

    def has_branch(self, d: str, branch: str) -> bool:
        try:
            return any(name == branch for name, _ in self._pool(d).branches(prefix=branch))
        except GitError as err:
            raise pool_read_error(err) from err

    def checkout(self, d: str, branch: str) -> None:
        try:
            self._pool(d).worktree(real_checkout(d)).checkout(branch)
        except GitError as err:
            raise pool_error(err) from err

    def checkout_new(self, d: str, branch: str, start: str) -> None:
        try:
            self._pool(d).worktree(real_checkout(d)).checkout_new(branch, start)
        except GitError as err:
            raise pool_error(err) from err

    def checkout_detached(self, d: str, ref: str) -> None:
        try:
            self._pool(d).worktree(real_checkout(d)).park(ref)
        except GitError as err:
            raise pool_error(err) from err

    def checkout_reset(self, d: str, branch: str, start: str) -> None:
        try:
            result = self._pool(d).worktree(real_checkout(d)).take_branch(branch, start, mode="restart")
        except GitError as err:
            raise pool_error(err) from err
        if isinstance(result, BranchHeld):
            holder = str(result.holders[0].path)
            raise BranchPinned(f"branch {branch!r} is already used by worktree at '{holder}'", holder)

    def clean(self, d: str, keep: list[str], ignored: bool = False) -> None:
        try:
            self._pool(d).worktree(real_checkout(d)).clean(keep, ignored=ignored)
        except GitError as err:
            # The old best-effort clean ignored command refusal, but not invocation failure.
            if not str(err).startswith("git clean exited "):
                raise pool_error(err) from err

    def checkouts(self, d: str) -> list[Checkout]:
        try:
            return [Checkout(path=str(w.path), branch=w.branch or "", main=w.is_main) for w in self._pool(d).worktrees()]
        except GitError as err:
            raise pool_read_error(err) from err

    def remove_worktree(self, repo: str, path: str) -> bool:
        try:
            self._pool(repo).drop_worktree(Path(path), missing_ok=False)
        except GitError:
            return False
        return True

    def remove_worktree_why(self, repo: str, path: str) -> str:
        try:
            self._pool(repo).drop_worktree(Path(path), missing_ok=False)
        except WorktreeRemoveRefused as err:
            return err.reason
        except GitError as err:
            raise pool_error(err) from err
        return ""

    def add_worktree(self, repo: str, path: str, ref: str) -> None:
        try:
            self._pool(repo).add_worktree(Path(path), ref)
        except GitError as err:
            raise pool_error(err) from err

    def init_bare(self, d: str, branch: str) -> None:
        self._must(os.path.dirname(d) or ".", "init", "-q", "--bare", "-b", branch, d)

    def clone(self, src: str, dst: str) -> None:
        self._must(os.path.dirname(dst) or ".", "clone", "-q", src, dst)

    def push(self, d: str, remote: str, refspec: str) -> None:
        self._must(d, "push", "-q", remote, refspec)

    # -- reads that return rows ------------------------------------------------------------------------------------------------

    def for_each_ref(self, d: str, *prefixes: str) -> list[Ref]:
        out = self._read(d, "for-each-ref", "--format=%(objectname) %(refname)", *prefixes)
        return [Ref(name=name, oid=oid) for oid, _, name in (ln.partition(" ") for ln in out.splitlines())]

    def ls_remote(self, d: str, remote: str, *patterns: str) -> list[Ref]:
        out = self._read(d, "ls-remote", remote, *patterns)
        return [Ref(name=name, oid=oid) for oid, _, name in (ln.partition("\t") for ln in out.splitlines())]

    def cherry(self, d: str, upstream: str, head: str) -> list[Pick]:
        try:
            return [Pick(oid=row.oid, upstream=row.upstream) for row in self._pool(d).cherry(upstream, head)]
        except GitError as err:
            raise pool_error(err) from err

    def merged(self, d: str, into: str) -> list[Ref]:
        try:
            repo = self._pool(d)
            repo.relate(into, into)  # Validate even when no local branches exist.
            return [Ref(name=name, oid=oid) for name, oid in repo.branches()
                    if not name.startswith("(") and repo.relate(oid, into).ahead == 0]
        except GitError as err:
            raise pool_read_error(err) from err

    def merge_base(self, d: str, a: str, b: str) -> str:
        try:
            return self._ask(d, "merge-base", a, b, missing=True)
        except MissingRevision:
            return ""
        except GitReadFailure:
            # merge-base reports an absent object with exit 128; verify absence
            # separately so an unreadable object or repository is still a fault.
            if not self.rev_parse(d, a) or not self.rev_parse(d, b):
                return ""
            raise

    def is_ancestor(self, d: str, a: str, b: str) -> bool:
        return self._predicate(d, "merge-base", "--is-ancestor", a, b)

    def rev_parse(self, d: str, rev: str) -> str:
        return self._ask(d, "rev-parse", "--verify", "-q", rev, missing=True)

    def log(self, d: str, include: list[str], exclude: list[str] | None = None, limit: int = 0, grep: str = "") -> list[LogRow]:
        try:
            rows = self._pool(d).history(include, not_on=exclude or [], limit=limit if limit and not grep else None)
        except GitError as err:
            raise pool_error(err) from err
        found = [LogRow(oid=row.sha, time=row.ts, subject=row.subject) for row in rows if grep in row.subject]
        return found[:limit] if limit else found

    def ls_tree(self, d: str, rev: str, *paths: str, recursive: bool = False) -> list[TreeEntry]:
        out = self._must(d, "ls-tree", "-z", *(["-r"] if recursive else []), rev, *paths)
        found = []
        for rec in out.split("\0"):
            head, _, path = rec.partition("\t")
            if path:
                mode, kind, oid = head.split(" ")
                found.append(TreeEntry(mode=mode, kind=kind, oid=oid, path=path))
        return found

    def status(self, d: str, all_untracked: bool = False) -> list[StatusRow]:
        out = self._read(d, "status", "--porcelain", "-z", *(["--untracked-files=all"] if all_untracked else []),
                         extra={"GIT_OPTIONAL_LOCKS": "0"})
        if out and not out.endswith("\0"):
            raise GitReadFailure("git status: incomplete path record")
        fields = out.split("\0")[:-1]
        found: list[StatusRow] = []
        i = 0
        while i < len(fields):
            f = fields[i]
            i += 1
            if len(f) <= 3 or f[2] != " " or any(c not in " MADRCUT?!" for c in f[:2]):
                raise GitReadFailure("git status: malformed path record")
            found.append(StatusRow(path=f[3:], index=f[0], work=f[1]))
            if any(c in "RC" for c in f[:2]):
                if i >= len(fields) or not fields[i]:
                    raise GitReadFailure("git status: incomplete rename record")
                i += 1  # a rename or copy is followed by the path it came from
        return found

    def check_ignore(self, d: str, paths: list[str], excludes: str = "") -> list[str]:
        if not paths:
            return []
        opts = ["-c", "core.excludesFile=" + excludes] if excludes else []
        r = self._run(d, *opts, "check-ignore", "--no-index", "--stdin", "-z", stdin="\0".join(paths) + "\0")
        if r.returncode not in (0, 1):
            raise classify(r.stderr or r.stdout)
        return [p for p in r.stdout.split("\0") if p]

    def git_dir(self, d: str) -> str:
        try:
            return self._ask(d, "rev-parse", "--absolute-git-dir")
        except NotARepo:
            return ""

    def has_commit(self, d: str, oid: str) -> bool:
        return bool(self.rev_parse(d, oid + "^{commit}"))

    # -- writes ----------------------------------------------------------------------------------------------------------------

    def rebase(self, d: str, onto: str, update_refs: bool = True) -> GitOutcome:
        # rebase() lacks quiet mode; rebase_onto() skips Git or raises before it can report dirty/paused refusals.
        opts = [] if update_refs else ["-c", "rebase.updateRefs=false"]
        return self._try(d, *opts, "rebase", "-q", onto)

    def reset(self, d: str, rev: str, mode: Literal["soft", "mixed", "hard"] = "mixed") -> None:
        try:
            self._pool(d).worktree(real_checkout(d)).reset(rev, mode=mode)
        except GitError as err:
            raise pool_error(err) from err

    def tag(self, d: str, name: str, rev: str = "HEAD") -> None:
        self._must(d, "tag", name, rev)

    def delete_branch_at(self, d: str, branch: str, oid: str) -> None:
        try:
            self._pool(d).delete_branch(branch, expected=Sha(oid))
        except GitError as err:
            raise pool_error(err) from err

    def delete_remote_at(self, d: str, remote: str, ref: str, oid: str) -> None:
        try:
            self._must(d, "push", "-q", f"--force-with-lease={ref}:{oid}", remote, ":" + ref)
        except SlotGitError:
            # A replay (or the forge's delete-on-merge) may have removed it already. ls-remote raises on a failed query;
            # only an authoritative empty answer counts as success. A ref recreated meanwhile is never deleted here.
            if self.ls_remote(d, remote, ref):
                raise

    def checkout_force(self, d: str, branch: str, start: str) -> None:
        try:
            self._pool(d).worktree(real_checkout(d)).checkout_force(branch, start)
        except GitError as err:
            raise pool_error(err) from err

    def fetch_ref(self, d: str, source: str, ref: str) -> None:
        self._must(d, "fetch", "-q", source, ref)

    def remote_url(self, d: str, remote: str) -> str:
        return self._ask(d, "remote", "get-url", remote)

    def merge_ff(self, d: str, rev: str) -> None:
        # The path-based porcelain helper cannot carry our injected environment and checkout pin.
        self._must(d, "merge", "-q", "--ff-only", rev)

    def commit_tracked(self, d: str, message: str) -> None:
        # record(tracked) loses complete refusal output and NothingToRecord's original diagnostic.
        self._must(d, "commit", "-q", "-a", "-m", message)

    def pull_rebase(self, d: str, remote: str, branch: str) -> None:
        self._must(d, "pull", "-q", "--rebase", remote, branch)


    def stage(self, d: str, *paths: str) -> None:
        self._must(d, "add", "--", *paths)

    def commit_staged(self, d: str, message: str) -> None:
        # record(staged) truncates hook errors and replaces empty-index diagnostics with a marker.
        self._must(d, "commit", "-q", "-m", message)

    # -- reads of files, config and the work tree --------------------------------------------------------------------------------

    def show(self, d: str, rev: str, path: str) -> str:
        r = self._run(d, "show", f"{rev}:{path}")
        if r.returncode != 0:
            raise classify(r.stderr or r.stdout)
        return r.stdout

    def ls_files(self, d: str, scope: Literal["tracked", "unignored", "ignored"] = "tracked", *spec: str) -> list[str]:
        opts = {"tracked": [], "unignored": ["-co", "--exclude-standard"], "ignored": ["-o", "-i", "--exclude-standard"]}[scope]
        r = self._run(d, "ls-files", "-z", *opts, *(["--", *spec] if spec else []))
        if r.returncode != 0:
            raise classify(r.stderr or r.stdout)
        return [p for p in r.stdout.split("\0") if p]

    def grep(self, d: str, pattern: str, fixed: bool = False, word: bool = False) -> list[GrepHit]:
        r = self._run(d, "grep", "-z", "-n", "-I", *(["-F"] if fixed else ["-E"]), *(["-w"] if word else []), "-e", pattern, "--", ".")
        if r.returncode == 1:
            return []
        if r.returncode != 0:
            raise classify(r.stderr or r.stdout)
        found = []
        for ln in r.stdout.split("\n"):
            path, nul, rest = ln.partition("\0")
            num, nul2, text = rest.partition("\0")
            if nul and nul2 and num.isdigit():
                found.append(GrepHit(path=path, line=int(num), text=text))
        return found

    def config_get(self, d: str, key: str) -> str:
        return self._ask(d, "config", "--get", key, missing=True)

    def config_entries(self, d: str, pattern: str) -> list[ConfigEntry]:
        found = []
        for ln in self._ask(d, "config", "--show-origin", "--get-regexp", pattern, missing=True).splitlines():
            where, _, kv = ln.partition("\t")
            key, _, value = kv.partition(" ")
            found.append(ConfigEntry(where=where, key=key, value=value))
        return found

    def common_dir(self, d: str) -> str:
        try:
            return self._ask(d, "rev-parse", "--path-format=absolute", "--git-common-dir")
        except NotARepo:
            return ""

    def toplevel(self, d: str) -> str:
        try:
            return self._ask(d, "rev-parse", "--show-toplevel")
        except (NotARepo, NotAWorktree):
            return ""

    def tree_of(self, d: str) -> str:
        """The snapshot tree, without declared ignored inputs; checks key those separately in InputKeys."""
        try:
            wt = self._pool(d).worktree(real_checkout(d))
            return str(wt.snapshot("HEAD", inputs=()).tree)
        except GitError as err:
            raise pool_error(err) from err

    def worktree_state(self, d: str) -> bytes | None:
        try:
            return self._pool(d).worktree_state(real_checkout(d))
        except GitError:
            return None

    def diff(self, d: str, a: str, b: str, exclude: list[str] | None = None, stat: bool = False) -> str:
        spec = ["--", ".", *(":(exclude,literal)" + p for p in exclude)] if exclude else []
        return self._read(d, "diff", *(["--stat"] if stat else []), a, b, *spec).strip()

    def add_worktree_force(self, repo: str, path: str, ref: str) -> None:
        try:
            self._pool(repo).add_worktree(Path(path), ref, force=True)
        except GitError as err:
            raise pool_error(err) from err

    def remove_worktree_force(self, repo: str, path: str) -> None:
        with suppress(GitError):
            self._pool(repo).drop_worktree(Path(path), force=True, missing_ok=False)

    def prune_worktrees(self, repo: str) -> None:
        with suppress(GitError):
            self._pool(repo).prune_worktrees()

