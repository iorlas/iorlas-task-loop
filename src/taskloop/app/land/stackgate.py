"""The gate of `tl land-stack`: before an item is pushed or merged, every gate step of the judged commit's profile (checks with run gate or
both, as the pre-push hook reads them) must have evidence for their full resolved keys on the item's tree and base. A step that is
not green is run once, as `tl check --repo W` in a clean worktree W that has the
branch out at that very oid, and asked again; with no such worktree the delivery stops naming the command to run. Still not green:
it stops with the check's exit code. A commit with no gate step passes. Its plan_cmd identifies the producer of planned skips."""
import json

from taskloop.app.checks import authorization
from taskloop.app.land.cmds import Cmds, Stop
from taskloop.contracts import config
from taskloop.contracts.argv import text_of
from taskloop.contracts.env import Env
from taskloop.contracts.ids import CheckId, TreeSha
from taskloop.contracts.ports import Git
from taskloop.contracts.runkey import BaseSha
from taskloop.stores.bundle import Stores


class StackGate:
    def __init__(self, cmds: Cmds, git: Git, stores: Stores, repo: str, base_ref: str, tl: list[str], env: Env | None = None) -> None:
        self.cmds, self.git, self.stores, self.repo, self.base_ref, self.tl = cmds, git, stores, repo, base_ref, tl
        self.env = env or Env()

    def profile(self, oid: str) -> config.EngineConfig | None:
        path = ".task-loop.json"
        entries = self.cmds.port(f"git ls-tree {oid} -- {path}", lambda: self.git.ls_tree(self.repo, oid, path))
        if not entries:
            return None  # no profile at the judged commit: no gate step
        text = self.cmds.port(f"git show {oid}:{path}", lambda: self.git.show(self.repo, oid, path))
        try:
            return config.load(json.loads(text)).engine
        except (ValueError, config.ConfigError) as e:
            raise Stop(1, f"cannot read the gate from {oid}:{path}: {e}") from None

    def red(self, engine: config.EngineConfig, tree: str, base: str, wt: str = "") -> list[CheckId]:
        found = authorization.results(self.stores, self.git, wt or self.repo, engine, TreeSha(tree), BaseSha(base), self.env,
                                      spawner=self.cmds.spawner)
        return [step for step, result in found.items() if result is None]

    def worktree(self, branch: str, oid: str) -> str:
        """A clean checkout of the branch at exactly `oid` ('' when there is none)."""
        for co in self.git.checkouts(self.repo):
            if co.branch == branch and self.git.rev_parse(co.path, "HEAD") == oid and not self.git.dirty(co.path):
                return co.path
        return ""

    def require(self, branch: str, oid: str) -> None:
        engine = self.profile(oid)
        if engine is None or not engine.gate_checks:
            return
        tree = self.cmds.port(f"git rev-parse --verify {oid[:12]}^{{tree}}", lambda: self.git.rev_parse(self.repo, f"{oid}^{{tree}}"))
        base = self.cmds.port(f"git rev-parse --verify {self.base_ref}", lambda: self.git.rev_parse(self.repo, self.base_ref))
        if not tree or not base:
            raise Stop(1, f"cannot name the tree of {oid[:12]} or the base {self.base_ref} (git rev-parse --verify {oid[:12]}^{{tree}}, "
                          f"git rev-parse --verify {self.base_ref})")
        wt = self.worktree(branch, oid)
        red = self.red(engine, tree, base, wt)
        if not red:
            return
        argv = [*self.tl, "check", "--repo", wt or "<a clean worktree of the branch>"]
        names = ", ".join(red)
        if not wt:
            raise Stop(1, f"{branch} ({oid[:12]}) is not green for {names} and no clean worktree has it out: run `{text_of(argv)}` there, "
                          "then land again")
        ran = self.cmds.run(argv)
        red = self.red(engine, tree, base, wt)
        if red:
            raise Stop(ran.exit or 1, f"{branch} ({oid[:12]}) is still not green for {', '.join(red)} after "
                                      f"`{text_of(argv)}` (exit {ran.exit})")
