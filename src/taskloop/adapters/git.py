"""Git (the port in contracts/ports.py) on the real git binary, pinned to the checkout. git's words are read here and nowhere else:
a failure becomes one of the typed SlotGitErrors (BranchPinned, DirtyTree, RefRace, IndexLocked) or the plain SlotGitError."""
import os
from contextlib import suppress
from pathlib import Path
from typing import Literal

from git_porcelain.errors import GitError, WorktreeRemoveRefused
from git_porcelain.real import RealRepo

from taskloop.adapters.git_base import classify
from taskloop.adapters.git_ops import LandGit
from taskloop.adapters.git_pool import UnpinnedRepo, pool_error, pool_read_error
from taskloop.contracts.gitfacts import ConfigEntry, GitOutcome, GrepHit, LogRow, Pick, Ref, StatusRow, TreeEntry
from taskloop.contracts.slots import Checkout, GitReadFailure, MissingRevision, NotARepo, NotAWorktree, RefRace, SlotGitError

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
        gd = self._ask(d, "rev-parse", "--git-dir")
        return bool(gd) and any(os.path.isdir(os.path.join(d, gd, x)) for x in ("rebase-merge", "rebase-apply"))

    def rebase_abort(self, d: str) -> None:
        self._run(d, "rebase", "--abort")

    def dirty(self, d: str) -> bool:
        try:
            return self._pool(d).worktree(Path(d).absolute()).dirty().raw
        except GitError as err:
            raise pool_read_error(err) from err

    def _pool(self, d: str) -> RealRepo:
        repo = RealRepo if self.pinned else UnpinnedRepo
        return repo(Path(d).absolute(), env=self.git_env(d), memoize=False, sleep=self.sleep)

    def branch(self, d: str) -> str:
        return self._ask(d, "symbolic-ref", "--short", "-q", "HEAD", missing=True)

    def symbolic_ref(self, d: str, ref: str) -> str:
        return self._ask(d, "symbolic-ref", "-q", ref, missing=True)

    def commit_all(self, d: str, branch: str, message: str) -> None:
        if not self.branch(d):
            self._must(d, "checkout", "-b", branch)
        self._must(d, "add", "-A")
        self._must(d, "commit", "-q", "--no-verify", "-m", message)

    def has_branch(self, d: str, branch: str) -> bool:
        return bool(self.rev_parse(d, "refs/heads/" + branch))

    def checkout(self, d: str, branch: str) -> None:
        self._must(d, "checkout", branch)

    def checkout_new(self, d: str, branch: str, start: str) -> None:
        self._must(d, "checkout", "-b", branch, start)

    def checkout_detached(self, d: str, ref: str) -> None:
        self._must(d, "checkout", "--detach", ref)

    def clean(self, d: str, keep: list[str], ignored: bool = False) -> None:
        self._run(d, "clean", "-fdxq" if ignored else "-fdq", *[x for k in keep for x in ("-e", k)])

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
        out = self._must(d, "cherry", upstream, head)
        return [Pick(oid=ln[2:], upstream=ln[0] == "-") for ln in out.splitlines() if ln[:2] in ("+ ", "- ")]

    def merged(self, d: str, into: str) -> list[Ref]:
        out = self._read(d, "branch", "--merged", into, "--format=%(objectname) %(refname:short)")
        rows = [ln.partition(" ") for ln in out.splitlines()]
        return [Ref(name=name, oid=oid) for oid, _, name in rows if not name.startswith("(")]

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
        args = ["log", "--format=%H%x00%ct%x00%s", *include, *(["--not", *exclude] if exclude else [])]
        if grep:
            args += ["--fixed-strings", "--grep=" + grep]
        elif limit:
            args += ["-n", str(limit)]
        rows = [ln.split("\0", 2) for ln in self._must(d, *args).splitlines()]
        found = [LogRow(oid=o, time=int(t) if t.isdigit() else 0, subject=s) for o, t, s in rows if grep in s]
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
        opts = [] if update_refs else ["-c", "rebase.updateRefs=false"]
        return self._try(d, *opts, "rebase", "-q", onto)

    def reset(self, d: str, rev: str, mode: Literal["soft", "mixed", "hard"] = "mixed") -> None:
        self._must(d, "reset", "-q", "--" + mode, rev)

    def tag(self, d: str, name: str, rev: str = "HEAD") -> None:
        self._must(d, "tag", name, rev)

    def delete_branch_at(self, d: str, branch: str, oid: str) -> None:
        self._must(d, "update-ref", "-d", "refs/heads/" + branch, oid)

    def delete_remote_at(self, d: str, remote: str, ref: str, oid: str) -> None:
        try:
            self._must(d, "push", "-q", f"--force-with-lease={ref}:{oid}", remote, ":" + ref)
        except SlotGitError:
            # A replay (or the forge's delete-on-merge) may have removed it already. ls-remote raises on a failed query;
            # only an authoritative empty answer counts as success. A ref recreated meanwhile is never deleted here.
            if self.ls_remote(d, remote, ref):
                raise

    def checkout_force(self, d: str, branch: str, start: str) -> None:
        self._must(d, "checkout", "-q", "-f", "-B", branch, start)

    def fetch_ref(self, d: str, source: str, ref: str) -> None:
        self._must(d, "fetch", "-q", source, ref)

    def remote_url(self, d: str, remote: str) -> str:
        return self._ask(d, "remote", "get-url", remote)

    def merge_ff(self, d: str, rev: str) -> None:
        self._must(d, "merge", "-q", "--ff-only", rev)

    def commit_tracked(self, d: str, message: str) -> None:
        self._must(d, "commit", "-q", "-a", "-m", message)

    def pull_rebase(self, d: str, remote: str, branch: str) -> None:
        self._must(d, "pull", "-q", "--rebase", remote, branch)


    def stage(self, d: str, *paths: str) -> None:
        self._must(d, "add", "--", *paths)

    def commit_staged(self, d: str, message: str) -> None:
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
            wt = self._pool(d).worktree(Path(d).absolute())
            return str(wt.snapshot("HEAD", inputs=()).tree)
        except GitError as err:
            raise pool_error(err) from err

    def worktree_state(self, d: str) -> bytes | None:
        try:
            return self._pool(d).worktree_state(Path(d).absolute())
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

