"""RealGit's reads: every parser lives in ``real_parse``, every argv here. A read never changes the repository
(``--no-optional-locks`` where git would otherwise refresh the index)."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Final, TypeVar

from git_porcelain import ignore_rules, real_cache, real_env, real_parse
from git_porcelain.api import Diff, Dirty, Health, LogEntry, Relation, RepoIdentity, Sha, Snapshot, Tree, TreeId, WorktreeInfo
from git_porcelain.errors import GitUnavailable
from git_porcelain.real_done import unavailable

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from git_porcelain.real import RealRepo, RealWorktree

__all__ = [
    "branches",
    "diff",
    "dirty",
    "git_dir_of",
    "grep_tracked",
    "head_of",
    "health",
    "history",
    "identity",
    "landed",
    "relate",
    "snapshot",
    "tree",
    "unmerged",
    "worktrees",
]

_T = TypeVar("_T")
_NO_LOCK: Final = "--no-optional-locks"
_CONFIG_KEYS: Final = r"^(core\.(worktree|bare)|extensions\.worktreeconfig)$"


def _rev_memo(repo: RealRepo, key: object, revs: Sequence[str], compute: Callable[[], _T]) -> _T:
    """Memoize an answer about revisions: forever when all are shas, while the ref files are unchanged otherwise."""
    if all(real_cache.is_sha(r) for r in revs):
        return repo.memo(key, compute)
    return real_cache.refs_memo(repo, key, revs, compute)


def head_of(wt: RealWorktree) -> Sha | None:
    """HEAD's commit; None on an unborn branch."""
    done = wt.run("rev-parse", "--verify", "-q", "HEAD", check=False)
    return Sha(done.out.strip()) if done.rc == 0 and done.out.strip() else None


def git_dir_of(wt: RealWorktree) -> Path:
    found = real_env.git_dir(wt.path)
    return found if found is not None else Path(wt.run("rev-parse", "--absolute-git-dir").out.strip())


def unmerged(wt: RealWorktree) -> tuple[str, ...]:
    out = wt.run("diff", "--name-only", "--diff-filter=U", "-z", check=False).out
    return tuple(sorted(p for p in out.split("\0") if p))


# -- Repo -------------------------------------------------------------------------------------------------
def identity(repo: RealRepo) -> RepoIdentity:
    def compute() -> RepoIdentity:
        common = Path(repo.run(repo.path, "rev-parse", "--path-format=absolute", "--git-common-dir").out.strip())
        url = repo.run(repo.path, "remote", "get-url", "origin", check=False).out.strip()
        root = common.parent if common.name == ".git" else common
        return RepoIdentity(root, common, url or None, hashlib.sha1(str(common).encode(), usedforsecurity=False).hexdigest()[:12])

    return repo.memo(("identity",), compute)


def relate(repo: RealRepo, a: str, b: str) -> Relation:
    def compute() -> Relation:
        base = repo.run(repo.path, "merge-base", a, b, check=False)
        if base.rc not in (0, 1):
            raise unavailable(("merge-base", a, b), base)
        counts = repo.run(repo.path, "rev-list", "--left-right", "--count", f"{a}...{b}").out.split()
        return Relation(Sha(base.out.strip()) if base.rc == 0 and base.out.strip() else None, int(counts[0]), int(counts[1]))

    return _rev_memo(repo, ("relate", a, b), (a, b), compute)


def history(
    repo: RealRepo, revs: Sequence[str], not_on: Sequence[str], limit: int | None, patch_equivalent_to: str | None
) -> tuple[LogEntry, ...]:
    if patch_equivalent_to is not None and len(revs) != 1:
        msg = "patch_equivalent_to needs exactly one rev"
        raise ValueError(msg)

    def compute() -> tuple[LogEntry, ...]:
        cap = [] if limit is None else ["-n", str(limit)]
        scope = ["--not", *not_on] if not_on else []
        out = repo.run(repo.path, "log", "--format=%H%x1f%ct%x1f%s%x1f%b%x1e", *cap, *revs, *scope, "--").out
        rows = real_parse.parse_log(out)
        if patch_equivalent_to is None:
            return tuple(LogEntry(sha, ts, subject, body, None) for sha, ts, subject, body in rows)
        cherry = repo.run(repo.path, "cherry", patch_equivalent_to, revs[0]).out.splitlines()
        pending = {line[2:].strip() for line in cherry if line.startswith("+ ")}
        return tuple(LogEntry(sha, ts, subject, body, sha not in pending) for sha, ts, subject, body in rows)

    key = ("history", tuple(revs), tuple(not_on), limit, patch_equivalent_to)
    return _rev_memo(repo, key, [*revs, *not_on, *([patch_equivalent_to] if patch_equivalent_to else [])], compute)


def branches(repo: RealRepo, prefix: str) -> tuple[tuple[str, Sha], ...]:
    def compute() -> tuple[tuple[str, Sha], ...]:
        out = repo.run(repo.path, "for-each-ref", "--format=%(refname)%00%(objectname)", "refs/heads/").out
        rows = (line.split("\0") for line in out.splitlines() if line)
        return tuple(sorted((name.removeprefix("refs/heads/"), Sha(sha)) for name, sha in rows))

    return tuple(
        row for row in real_cache.validated(repo, ("branches",), real_cache.heads_files(repo), compute) if row[0].startswith(prefix)
    )


def tree(repo: RealRepo, rev: str) -> Tree | None:
    def resolve() -> Sha | None:
        for kind in ("commit", "tree"):
            done = repo.run(repo.path, "rev-parse", "--verify", "-q", f"{rev}^{{{kind}}}", check=False)
            if done.rc == 0 and done.out.strip():
                return Sha(done.out.strip())
        return None

    sha = _rev_memo(repo, ("resolve", rev), (rev,), resolve)
    if sha is None:
        return None

    def build() -> Tree:
        def lister() -> dict[str, tuple[str, Sha]]:
            return real_parse.parse_ls_tree(repo.run(repo.path, "ls-tree", "-r", "-z", sha).out)

        def reader(path: str) -> bytes | None:
            done = repo.run(repo.path, "cat-file", "blob", f"{sha}:{path}", check=False)
            return done.raw if done.rc == 0 else None

        return Tree(sha, lister, reader)

    return repo.memo(("tree", sha), build)


def worktrees(repo: RealRepo, *, with_dirty: bool) -> tuple[WorktreeInfo, ...]:
    def compute() -> tuple[WorktreeInfo, ...]:
        rows = real_parse.parse_worktrees(repo.run(repo.path, "worktree", "list", "--porcelain").out)
        return tuple(WorktreeInfo(path, Sha(head) if head else None, branch, i == 0, None) for i, (path, head, branch) in enumerate(rows))

    found = repo.memo(("worktrees",), compute, forever=False)
    if not with_dirty:
        return found
    return tuple(
        WorktreeInfo(w.path, w.head, w.branch, w.is_main, dirty(repo.worktree(w.path), None, ()).raw if w.path.exists() else None)
        for w in found
    )


# -- Worktree ---------------------------------------------------------------------------------------------
def health(wt: RealWorktree) -> Health:
    asked = wt.run("config", "--show-origin", "--get-regexp", _CONFIG_KEYS, pin=False, check=False)
    if asked.rc > 1 and (found := real_env.git_dir(wt.path)) is not None:
        # a core.worktree that points nowhere makes git die in setup: read the config file itself
        asked = wt.run(
            "config",
            "--file",
            str(real_env.common_of(found) / "config"),
            "--show-origin",
            "--get-regexp",
            _CONFIG_KEYS,
            pin=False,
            check=False,
        )
    cfg = real_parse.parse_config_origin(asked.out, wt.path)
    top = wt.run("rev-parse", "--show-toplevel", pin=False, check=False)
    per_worktree = cfg.get("extensions.worktreeconfig", ("", ""))[0].lower() == "true"
    if "core.worktree" in cfg:
        value, where = cfg["core.worktree"]
        detail = f"core.worktree={value} (set in {where})"
        return Health(ok=False, problem="worktree_redirected", detail=detail, set_in=Path(where), worktree_config=per_worktree)
    if cfg.get("core.bare", ("", ""))[0].lower() == "true":
        where = cfg["core.bare"][1]
        return Health(ok=False, problem="bare", detail=f"core.bare=true (set in {where})", set_in=Path(where), worktree_config=per_worktree)
    seen = top.out.strip() if top.rc == 0 else ""
    if not seen or Path(seen).resolve() != wt.path.resolve():
        detail = f"git's top level is {seen or '(none)'}, not {wt.path}"
        return Health(ok=False, problem="toplevel_mismatch", detail=detail, set_in=None, worktree_config=per_worktree)
    return Health(ok=True, problem=None, detail="", set_in=None, worktree_config=per_worktree)


def snapshot(wt: RealWorktree, base: str) -> Snapshot:
    repo = wt.repo
    text = wt.run(_NO_LOCK, "status", "--porcelain=v2", "--branch", "-z", "--untracked-files=all").out
    state = real_parse.parse_status(text)
    key = real_cache.tree_key(wt.path, text, (*state.tracked, *state.untracked)) if repo.memoize else None
    cached = repo.snapshots.get(str(wt.path))
    if key is not None and cached is not None and cached[0] == key:
        work = TreeId(str(cached[1]))
    else:
        work = _write_tree(wt, has_head=state.head is not None)
        if key is not None:
            repo.snapshots[str(wt.path)] = (key, work)
    names = [f"{base}^{{commit}}"] if state.head is None else ["HEAD^{tree}", f"{base}^{{commit}}"]
    seen = wt.run("rev-parse", *names, check=False)
    lines = seen.out.split()
    if seen.rc != 0 or len(lines) != len(names):
        msg = f"git rev-parse exited {seen.rc}: base {base!r} does not resolve: {seen.tail}"
        raise GitUnavailable(msg)
    base_tip = Sha(lines[-1])
    if state.head is None:
        return Snapshot(work, None, None, state.branch, base_tip, base_tip)
    merged = wt.run("merge-base", base, "HEAD", check=False)
    mb = Sha(merged.out.strip()) if merged.rc == 0 and merged.out.strip() else base_tip
    return Snapshot(work, Sha(state.head), TreeId(lines[0]), state.branch, mb, base_tip)


def _write_tree(wt: RealWorktree, *, has_head: bool) -> TreeId:
    with tempfile.TemporaryDirectory() as folder:
        env = {"GIT_INDEX_FILE": str(Path(folder) / "index")}
        if has_head:
            wt.run("read-tree", "HEAD", env=env)
        wt.run("add", "-A", env=env)
        return TreeId(wt.run("write-tree", env=env).out.strip())


def diff(wt: RealWorktree, a: str, b: str, *, exclude: tuple[str, ...], cap: int | None) -> Diff:
    def compute() -> Diff:
        scope = ["--", ".", *(f":(exclude,literal){p}" for p in exclude)] if exclude else []
        common = ("--no-color", "--no-ext-diff", "--no-renames", a, b)
        changes = real_parse.parse_diff(wt.run("diff", "--raw", "--numstat", "-z", *common, *scope).out)
        if not changes:
            return Diff((), "", truncated=False)
        if cap == 0:
            return Diff(changes, "", truncated=True)
        patch = wt.run("diff", *common, *scope).out
        if cap is not None and len(patch) > cap:
            return Diff(changes, patch[:cap], truncated=True)
        return Diff(changes, patch, truncated=False)

    return _rev_memo(wt.repo, ("diff", a, b, exclude, cap), (a, b), compute)


def dirty(wt: RealWorktree, base: str | None, ignored_under: tuple[str, ...]) -> Dirty:
    state = real_parse.parse_status(wt.run(_NO_LOCK, "status", "--porcelain=v2", "-z", "--untracked-files=all", "--no-renames").out)
    ignored_by_base = _base_ignored(wt, base, state.untracked) if base is not None and state.untracked else frozenset()
    ignored: tuple[str, ...] = ()
    if ignored_under:
        listed = wt.run("--literal-pathspecs", "ls-files", "-z", "-o", "-i", "--exclude-standard", "--", *ignored_under).out
        ignored = tuple(sorted(p for p in listed.split("\0") if p))
    return Dirty(state.tracked, state.untracked, ignored_by_base, ignored)


def _base_ignored(wt: RealWorktree, base: str, untracked: Sequence[str]) -> frozenset[str]:
    rules = _rev_memo(wt.repo, ("ignore-rules", base), (base,), lambda: _base_rules(wt, base))
    if not rules:
        return frozenset()
    with tempfile.TemporaryDirectory() as folder:
        rules_file = Path(folder) / "rules"
        rules_file.write_text("\n".join(rules) + "\n", encoding="utf-8")
        done = wt.run(
            "-c",
            f"core.excludesFile={rules_file}",
            "check-ignore",
            "--no-index",
            "--stdin",
            "-z",
            stdin="\0".join(untracked) + "\0",
            check=False,
        )
    if done.rc not in (0, 1):
        raise unavailable(("check-ignore",), done)
    return frozenset(p for p in done.out.split("\0") if p)


def _base_rules(wt: RealWorktree, base: str) -> tuple[str, ...]:
    listing = wt.run("ls-tree", "-r", "--name-only", "-z", base).out
    texts: dict[str, str] = {}
    for path in (p for p in listing.split("\0") if ignore_rules.is_ignore_file(p)):
        shown = wt.run("cat-file", "blob", f"{base}:{path}", check=False)
        if shown.rc == 0:
            texts[path] = shown.out
    return tuple(ignore_rules.flatten(texts))


def landed(wt: RealWorktree, base: str, title_suffix: str) -> Sha | None:
    done = wt.run("log", "-1", "--format=%H%x1f%s", check=False)
    if done.rc != 0 or "\x1f" not in done.out:
        return None
    tip, _, subject = done.out.strip("\n").partition("\x1f")
    if not subject.endswith(title_suffix):
        return None
    return Sha(tip) if wt.repo.relate(tip, base).ahead == 0 else None


def grep_tracked(wt: RealWorktree, term: str) -> tuple[str, ...]:
    done = wt.run("grep", "-w", "-I", "-l", "-z", "-F", "-e", term, check=False)
    if done.rc not in (0, 1):
        raise unavailable(("grep",), done)
    return tuple(sorted(p for p in done.out.split("\0") if p))
