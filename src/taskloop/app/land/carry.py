"""Carry a pass over a base move. A check with `closure_cmd` that passed on this tree at an earlier base has a receipt that no longer
matches (the base is in its key). The pass still holds when the files its result depends on are the same in the branch and in the branch
merged into the moved base: `closure_cmd --base REV` lists them in both (the closure of the tests the diff against REV selects, computed on
the merge, so a new test of main that imports the branch's changed module is in it), and each file's content is compared. Same list, same
bytes: the receipt is stored again under the new key, its `origin` naming the run that made it. Any difference, a conflict, a command that
fails: no carry, the check runs. The caller owns the worktree at the judged oid; the merge is made in a throwaway one."""
import hashlib
import tempfile
from pathlib import Path

from taskloop.app.checks import authorization
from taskloop.app.checks.cache import PassRecord, satisfied
from taskloop.app.land.cmds import Cmds
from taskloop.contracts import config
from taskloop.contracts.env import Env
from taskloop.contracts.ids import TreeSha
from taskloop.contracts.ports import Git
from taskloop.contracts.runkey import BaseSha
from taskloop.domain.checks.specs import repo_check
from taskloop.stores.bundle import Stores

MERGE = ["git", "-c", "user.name=task-loop", "-c", "user.email=task-loop@localhost", "merge", "--no-ff", "--no-edit", "-q"]


def earlier_pass(memo: authorization.RunMemo, check_id: str, expected, repo: str, stores: Stores) -> PassRecord | None:
    """The newest pass whose key differs from `expected` only in the base."""
    docs = stores.results(repo, check_id)
    found = [rec for name in docs.keys() if (rec := docs.of(name).get()) is not None  # noqa: SIM118 (a DocSet is not iterable)
             and rec.result.status == "passed" and satisfied(rec.result) and rec.key.base != expected.base
             and rec.key.replace(base=expected.base) == expected]
    return max(found, key=lambda r: r.ts, default=None)


def digest_of(root: str, paths: list[str]) -> dict[str, str]:
    """{path: sha1 of its bytes, '' when it is gone}."""
    out = {}
    for p in paths:
        f = Path(root, p)
        out[p] = hashlib.sha1(f.read_bytes()).hexdigest() if f.is_file() else ""
    return out


class Carry:
    def __init__(self, cmds: Cmds, git: Git, stores: Stores, repo: str, env: Env) -> None:
        self.cmds, self.git, self.stores, self.repo, self.env = cmds, git, stores, repo, env

    def closure(self, argv: list[str], wt: str, rev: str) -> dict[str, str] | None:
        ran = self.cmds.run([*argv, "--base", rev], cwd=wt)
        if ran.exit:
            return None
        return digest_of(wt, sorted(ln for ln in ran.out.splitlines() if ln.strip()))

    def merged(self, oid: str, base: str) -> str:
        """A throwaway worktree with `oid` merged into `base` ('' when it conflicts)."""
        path = tempfile.mkdtemp(prefix="tl-land-merge-")
        self.cmds.port(f"git worktree add --detach {path} {base[:12]}", lambda: self.git.add_worktree(self.repo, path, base))
        if self.cmds.run([*MERGE, oid], cwd=path).exit:
            self.cmds.run(["git", "merge", "--abort"], cwd=path)
            self.drop(path)
            return ""
        return path

    def drop(self, path: str) -> None:
        self.cmds.row(f"git worktree remove {path}", lambda: self.git.remove_worktree_force(self.repo, path))

    def carried(self, engine: config.EngineConfig, step: str, oid: str, tree: str, base: str, wt: str) -> bool:
        """True when the step's earlier pass now holds under the key of (tree, base) and has been stored under it."""
        spec = next((k for k in engine.checks if k.id == step), None)
        if spec is None or not spec.closure_cmd:
            return False
        memo = authorization.memo_for(self.stores, self.git, wt, engine, TreeSha(tree), BaseSha(base), self.env)
        check = repo_check(spec, engine)
        key = memo.key(check)
        found = earlier_pass(memo, check.id, key, memo.repo, self.stores) if key is not None else None
        if found is None or key is None:
            return False
        merged = self.merged(oid, base)
        if not merged:
            return False
        try:
            mine = self.closure(spec.closure_cmd, wt, self.git.merge_base(self.repo, oid, base) or base)
            theirs = self.closure(spec.closure_cmd, merged, base)
        finally:
            self.drop(merged)
        if mine is None or theirs is None or mine != theirs:
            return False
        memo.run_id = "carry"
        memo.reuse(key, found)
        return True
