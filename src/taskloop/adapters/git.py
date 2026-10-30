"""Git (the port in contracts/ports.py) on the real git binary, pinned to the checkout. git's words are read here and nowhere else:
a failure becomes one of the typed SlotGitErrors (BranchPinned, DirtyTree, RefRace, IndexLocked) or the plain SlotGitError."""
import os
import re
import subprocess
import tempfile
import time
from collections.abc import Callable
from typing import Final, Literal

from taskloop.adapters.childenv import without
from taskloop.adapters.gitenv import git_env, run_git
from taskloop.contracts import env as penv
from taskloop.contracts.gitfacts import ConfigEntry, GrepHit, LogRow, Pick, RebaseOutcome, Ref, StatusRow, TreeEntry
from taskloop.contracts.slots import BranchPinned, Checkout, DirtyTree, IndexLocked, RefRace, SlotGitError

INDEX_LOCK = re.compile(r"index\.lock")
REF_RACE = re.compile(r"incorrect old value|cannot lock ref|unable to update local ref|Unable to create '[^']*\.lock'")
PINNED = re.compile(r"already (?:checked out|used by worktree) at '?([^'\n]*)'?")
DIRTY = re.compile(r"would be overwritten|commit your changes|local changes|unmerged|unresolved|cannot (?:do a )?(?:commit|merge)")
FETCH_TRIES = 5


def error_line(text: str) -> str:
    """The line of git's stderr that says what went wrong: the first fatal/error one, else the last."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return next((ln for ln in lines if ln.startswith(("fatal:", "error:"))), lines[-1] if lines else "no message from git")


def classify(stderr: str) -> SlotGitError:
    tail = error_line(stderr)
    if INDEX_LOCK.search(stderr):
        return IndexLocked(tail)
    if m := PINNED.search(stderr):
        return BranchPinned(tail, m.group(1).strip())
    if REF_RACE.search(stderr):
        return RefRace(tail)
    if DIRTY.search(stderr):
        return DirtyTree(tail)
    return SlotGitError(tail)


class RealGit:
    """`pinned=False` reads git as the ambient environment has it (no GIT_DIR/GIT_WORK_TREE/GIT_COMMON_DIR), as a worker's or a check's git
    would see the folder: for the questions whether the pin itself is right (core.worktree, core.bare in the shared config)."""

    def __init__(self, sleep: Callable[[float], None] = time.sleep, pinned: bool = True) -> None:
        self.sleep = sleep
        self.pinned = pinned

    def _run(self, d: str, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        if not self.pinned:
            env = without(penv.snapshot().vars, "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR")
            return subprocess.run(["git", "-C", d, *args], env=env, check=False, capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", input=stdin)
        return run_git(d, *args, capture_output=True, text=True, encoding="utf-8", errors="replace", input=stdin)

    def _must(self, d: str, *args: str) -> str:
        r = self._run(d, *args)
        if r.returncode != 0:
            raise classify(r.stderr or r.stdout)
        return r.stdout.strip()

    def _ask(self, d: str, *args: str) -> str:
        r = self._run(d, *args)
        return r.stdout.strip() if r.returncode == 0 else ""

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
        return bool(self._ask(d, "status", "--porcelain"))

    def branch(self, d: str) -> str:
        return self._ask(d, "symbolic-ref", "--short", "-q", "HEAD")

    def commit_all(self, d: str, branch: str, message: str) -> None:
        if not self.branch(d):
            self._must(d, "checkout", "-b", branch)
        self._must(d, "add", "-A")
        self._must(d, "commit", "-q", "--no-verify", "-m", message)

    def has_branch(self, d: str, branch: str) -> bool:
        return bool(self._ask(d, "rev-parse", "--verify", "-q", "refs/heads/" + branch))

    def checkout(self, d: str, branch: str) -> None:
        self._must(d, "checkout", branch)

    def checkout_new(self, d: str, branch: str, start: str) -> None:
        self._must(d, "checkout", "-b", branch, start)

    def checkout_detached(self, d: str, ref: str) -> None:
        self._must(d, "checkout", "--detach", ref)

    def clean(self, d: str, keep: list[str], ignored: bool = False) -> None:
        self._run(d, "clean", "-fdxq" if ignored else "-fdq", *[x for k in keep for x in ("-e", k)])

    def checkouts(self, d: str) -> list[Checkout]:
        out = self._ask(d, "worktree", "list", "--porcelain")
        found = []
        for i, block in enumerate(out.split("\n\n")):
            lines = block.splitlines()
            path = next((ln[9:] for ln in lines if ln.startswith("worktree ")), "")
            branch = next((ln[18:] for ln in lines if ln.startswith("branch refs/heads/")), "")
            if path:
                found.append(Checkout(path=path, branch=branch, main=i == 0))
        return found

    def remove_worktree(self, repo: str, path: str) -> bool:
        return self._run(repo, "worktree", "remove", path).returncode == 0

    def remove_worktree_why(self, repo: str, path: str) -> str:
        r = self._run(repo, "worktree", "remove", path)
        return "" if r.returncode == 0 else (r.stderr.strip().splitlines() or ["git worktree remove failed"])[-1]

    def add_worktree(self, repo: str, path: str, ref: str) -> None:
        self._must(repo, "worktree", "add", "--detach", path, ref)

    def init_bare(self, d: str, branch: str) -> None:
        self._must(os.path.dirname(d) or ".", "init", "-q", "--bare", "-b", branch, d)

    def clone(self, src: str, dst: str) -> None:
        self._must(os.path.dirname(dst) or ".", "clone", "-q", src, dst)

    def push(self, d: str, remote: str, refspec: str) -> None:
        self._must(d, "push", "-q", remote, refspec)

    # -- reads that return rows ------------------------------------------------------------------------------------------------

    def for_each_ref(self, d: str, *prefixes: str) -> list[Ref]:
        out = self._must(d, "for-each-ref", "--format=%(objectname) %(refname)", *prefixes)
        return [Ref(name=name, oid=oid) for oid, _, name in (ln.partition(" ") for ln in out.splitlines())]

    def ls_remote(self, d: str, remote: str, *patterns: str) -> list[Ref]:
        out = self._must(d, "ls-remote", remote, *patterns)
        return [Ref(name=name, oid=oid) for oid, _, name in (ln.partition("\t") for ln in out.splitlines())]

    def cherry(self, d: str, upstream: str, head: str) -> list[Pick]:
        out = self._must(d, "cherry", upstream, head)
        return [Pick(oid=ln[2:], upstream=ln[0] == "-") for ln in out.splitlines() if ln[:2] in ("+ ", "- ")]

    def merged(self, d: str, into: str) -> list[Ref]:
        out = self._must(d, "branch", "--merged", into, "--format=%(objectname) %(refname:short)")
        rows = [ln.partition(" ") for ln in out.splitlines()]
        return [Ref(name=name, oid=oid) for oid, _, name in rows if not name.startswith("(")]

    def merge_base(self, d: str, a: str, b: str) -> str:
        return self._ask(d, "merge-base", a, b)

    def is_ancestor(self, d: str, a: str, b: str) -> bool:
        return self._run(d, "merge-base", "--is-ancestor", a, b).returncode == 0

    def rev_parse(self, d: str, rev: str) -> str:
        return self._ask(d, "rev-parse", "--verify", "-q", rev)

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

    def status(self, d: str) -> list[StatusRow]:
        r = self._run(d, "status", "--porcelain", "-z")
        if r.returncode:
            raise classify(r.stderr or r.stdout)
        fields = r.stdout.split("\0")
        found: list[StatusRow] = []
        i = 0
        while i < len(fields):
            f = fields[i]
            i += 1
            if len(f) > 3:
                found.append(StatusRow(path=f[3:], index=f[0], work=f[1]))
                if f[0] in "RC":
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
        return self._ask(d, "rev-parse", "--absolute-git-dir")

    def has_commit(self, d: str, oid: str) -> bool:
        return bool(self._ask(d, "rev-parse", "--verify", "-q", oid + "^{commit}"))

    # -- writes ----------------------------------------------------------------------------------------------------------------

    def rebase(self, d: str, onto: str, update_refs: bool = True) -> RebaseOutcome:
        opts = [] if update_refs else ["-c", "rebase.updateRefs=false"]
        r = self._run(d, *opts, "rebase", "-q", onto)
        return RebaseOutcome(ok=r.returncode == 0, output=(r.stdout + r.stderr).strip())

    def reset(self, d: str, rev: str, mode: Literal["soft", "mixed", "hard"] = "mixed") -> None:
        self._must(d, "reset", "-q", "--" + mode, rev)

    def tag(self, d: str, name: str, rev: str = "HEAD") -> None:
        self._must(d, "tag", name, rev)

    def delete_branch_at(self, d: str, branch: str, oid: str) -> None:
        self._must(d, "update-ref", "-d", "refs/heads/" + branch, oid)

    def delete_remote_at(self, d: str, remote: str, ref: str, oid: str) -> None:
        self._must(d, "push", "-q", f"--force-with-lease={ref}:{oid}", remote, ":" + ref)

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
        return self._ask(d, "config", "--get", key)

    def config_entries(self, d: str, pattern: str) -> list[ConfigEntry]:
        found = []
        for ln in self._ask(d, "config", "--show-origin", "--get-regexp", pattern).splitlines():
            where, _, kv = ln.partition("\t")
            key, _, value = kv.partition(" ")
            found.append(ConfigEntry(where=where, key=key, value=value))
        return found

    def common_dir(self, d: str) -> str:
        return self._ask(d, "rev-parse", "--path-format=absolute", "--git-common-dir")

    def toplevel(self, d: str) -> str:
        return self._ask(d, "rev-parse", "--show-toplevel")

    def tree_of(self, d: str) -> str:
        """HEAD's tree plus every change and untracked file, written from a throwaway index in a temp folder."""
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(git_env(d), GIT_INDEX_FILE=os.path.join(tmp, "index"))
            out = ""
            for args in (["read-tree", "HEAD"], ["add", "-A"], ["write-tree"]):
                r = subprocess.run(["git", *args], cwd=d, env=env, capture_output=True, text=True, check=False)
                if r.returncode != 0:
                    raise SlotGitError(f"git {args[0]} failed ({r.returncode}): {(r.stderr or '').strip()[:300]}")
                out = r.stdout.strip()
        return out

    def worktree_state(self, d: str) -> bytes | None:
        r = subprocess.run(["git", "--no-optional-locks", "status", "--porcelain=v2", "--branch", "-z", "--untracked-files=all"],
                           cwd=d, env=git_env(d), capture_output=True, check=False)
        return r.stdout if r.returncode == 0 else None

    def diff(self, d: str, a: str, b: str, exclude: list[str] | None = None, stat: bool = False) -> str:
        spec = ["--", ".", *(":(exclude,literal)" + p for p in exclude)] if exclude else []
        r = self._run(d, "diff", *(["--stat"] if stat else []), a, b, *spec)
        return r.stdout.strip() if r.returncode == 0 else ""

    def add_worktree_force(self, repo: str, path: str, ref: str) -> None:
        self._must(repo, "worktree", "add", "--detach", "--force", path, ref)

    def remove_worktree_force(self, repo: str, path: str) -> None:
        self._run(repo, "worktree", "remove", "--force", path)

    def prune_worktrees(self, repo: str) -> None:
        self._run(repo, "worktree", "prune")


REAL: Final = RealGit()  # the default of a function that takes the port as an argument (a test passes its own)
