"""The gate of `tl land-stack`: before an item is pushed or merged, every gate step of the repo's profile (engine.checks with run gate or
both, as the pre-push hook reads them) must be green for the item's tree and the base, asked of the result store (`is_green`, the
function `tl green` answers with). A step that is not green is run once, as `tl check --repo W` in a clean worktree W that has the
branch out at that very oid, and asked again; with no such worktree the delivery stops naming the command to run. Still not green:
it stops with the check's exit code. A repo with no gate step passes."""
import json
from pathlib import Path

from taskloop.app.checks.cache import repo_green
from taskloop.app.land.cmds import Cmds, Stop
from taskloop.contracts import config
from taskloop.contracts.argv import text_of
from taskloop.contracts.ids import CheckId, TreeSha
from taskloop.contracts.ports import Git
from taskloop.contracts.runkey import BaseSha
from taskloop.stores.bundle import Stores


class StackGate:
    def __init__(self, cmds: Cmds, git: Git, stores: Stores, repo: str, base_ref: str, tl: list[str]) -> None:
        self.cmds, self.git, self.stores, self.repo, self.base_ref, self.tl = cmds, git, stores, repo, base_ref, tl

    def steps(self) -> list[CheckId]:
        path = Path(self.repo) / ".task-loop.json"
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return []  # no profile: no gate step
        try:
            return [CheckId(str(k.id)) for k in config.load(json.loads(text)).engine.gate_checks]
        except (ValueError, config.ConfigError) as e:
            raise Stop(1, f"cannot read the gate from {path}: {e}") from None

    def red(self, steps: list[CheckId], tree: str, base: str) -> list[CheckId]:
        return [s for s in steps if not repo_green(self.stores, self.git, self.repo, s, TreeSha(tree), BaseSha(base))]

    def worktree(self, branch: str, oid: str) -> str:
        """A clean checkout of the branch at exactly `oid` ('' when there is none)."""
        for co in self.git.checkouts(self.repo):
            if co.branch == branch and self.git.rev_parse(co.path, "HEAD") == oid and not self.git.dirty(co.path):
                return co.path
        return ""

    def require(self, branch: str, oid: str) -> None:
        steps = self.steps()
        if not steps:
            return
        tree = self.cmds.port(f"git rev-parse --verify {oid[:12]}^{{tree}}", lambda: self.git.rev_parse(self.repo, f"{oid}^{{tree}}"))
        base = self.cmds.port(f"git rev-parse --verify {self.base_ref}", lambda: self.git.rev_parse(self.repo, self.base_ref))
        if not tree or not base:
            raise Stop(1, f"cannot name the tree of {oid[:12]} or the base {self.base_ref} (git rev-parse --verify {oid[:12]}^{{tree}}, "
                          f"git rev-parse --verify {self.base_ref})")
        red = self.red(steps, tree, base)
        if not red:
            return
        wt = self.worktree(branch, oid)
        argv = [*self.tl, "check", "--repo", wt or "<a clean worktree of the branch>"]
        names = ", ".join(red)
        if not wt:
            raise Stop(1, f"{branch} ({oid[:12]}) is not green for {names} and no clean worktree has it out: run `{text_of(argv)}` there, "
                          "then land again")
        ran = self.cmds.run(argv)
        if self.red(steps, tree, base):
            raise Stop(ran.exit or 1, f"{branch} ({oid[:12]}) is still not green for {', '.join(self.red(steps, tree, base))} after "
                                      f"`{text_of(argv)}` (exit {ran.exit})")
