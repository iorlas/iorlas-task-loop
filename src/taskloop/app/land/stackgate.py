"""The gate of `tl land-stack`: before an item is pushed or merged, every gate step of the base commit's profile (checks with run gate or
both, as the pre-push hook reads them) must have evidence for their full resolved keys on the item's tree and base. A step that is
not green is run once, as `tl check --repo W` in a clean worktree W that has the branch (or a detached HEAD) out at that very oid,
and asked again; with no such worktree the gate makes one (detached at the oid, removed after the run), so the caller never runs a
command by hand. Still not green: it stops with the check's exit code. Each refused step says the first key field that differs
from its newest receipt on the tree and base. A commit with no gate step passes. Its plan_cmd identifies the producer of planned skips."""
import json
import tempfile

from taskloop.app.checks import authorization
from taskloop.app.land.cmds import Cmds, Stop
from taskloop.app.land.profile_change import owner_refusal
from taskloop.contracts import config
from taskloop.contracts.argv import text_of
from taskloop.contracts.env import Env
from taskloop.contracts.ids import CheckId, TreeSha
from taskloop.contracts.ports import Git
from taskloop.contracts.runkey import BaseSha
from taskloop.contracts.slots import NotARepo
from taskloop.stores.bundle import Stores


class StackGate:
    def __init__(self, cmds: Cmds, git: Git, stores: Stores, repo: str, base_ref: str, tl: list[str], env: Env | None = None) -> None:
        self.cmds, self.git, self.stores, self.repo, self.base_ref, self.tl = cmds, git, stores, repo, base_ref, tl
        self.env = env or Env()
        self.why: dict[CheckId, str] = {}  # the last red()'s steps: the first key field that differs from their newest receipt

    def profile(self, oid: str) -> config.EngineConfig | None:
        path = ".task-loop.json"
        entries = self.cmds.port(f"git ls-tree {oid} -- {path}", lambda: self.git.ls_tree(self.repo, oid, path))
        if not entries:
            return None  # no profile at the base commit: no gate step
        text = self.cmds.port(f"git show {oid}:{path}", lambda: self.git.show(self.repo, oid, path))
        try:
            return config.load(json.loads(text)).engine
        except (ValueError, config.ConfigError) as e:
            raise Stop(1, f"cannot read the gate from {oid}:{path}: {e}") from None

    def red(self, engine: config.EngineConfig, tree: str, base: str, wt: str = "") -> list[CheckId]:
        found = authorization.results(self.stores, self.git, wt or self.repo, engine, TreeSha(tree), BaseSha(base), self.env)
        red = [step for step, result in found.items() if result is None]
        self.why = (authorization.explain(self.stores, self.git, wt or self.repo, engine, TreeSha(tree), BaseSha(base), self.env, red)
                    if red else {})
        return red

    def named(self, red: list[CheckId]) -> str:
        """The red steps, each with why its receipt does not count when that is known."""
        return ", ".join(f"{step} ({self.why[step]})" if self.why.get(step) else step for step in red)

    def worktree(self, branch: str, oid: str) -> str:
        """A clean checkout of the branch, or a detached one, at exactly `oid` ('' when there is none): the receipts of `tl check` key
        the gitignored files under a check's inputs as that checkout has them, so the gate judges there, never in another checkout."""
        for co in self.git.checkouts(self.repo):
            if co.branch not in (branch, ""):
                continue
            try:
                if self.git.rev_parse(co.path, "HEAD") == oid and not self.git.dirty(co.path):
                    return co.path
            except NotARepo:  # a worktree git still lists whose directory is gone (a pruned scratch checkout): no worktree for this oid
                continue
        return ""

    def require(self, branch: str, oid: str, *, profile_change: str | None = None, regate: bool = True) -> str:
        if why := owner_refusal(profile_change, self.env):
            raise Stop(2, why)
        base = self.cmds.port(f"git rev-parse --verify {self.base_ref}", lambda: self.git.rev_parse(self.repo, self.base_ref))
        if not base:
            raise Stop(1, f"cannot name the base {self.base_ref}")
        path = ".task-loop.json"
        policy = self.cmds.port(f"git ls-tree {base} -- {path}", lambda: self.git.ls_tree(self.repo, base, path))
        proposed = self.cmds.port(f"git ls-tree {oid} -- {path}", lambda: self.git.ls_tree(self.repo, oid, path))
        if [entry.oid for entry in policy] != [entry.oid for entry in proposed] and profile_change is None:
            raise Stop(1, f"profile_changed: {branch} changes {path}; only the owner may push a profile change "
                          "(git push --no-verify)")
        engine = self.profile(base)
        if engine is None or not engine.gate_checks:
            return base
        tree = self.cmds.port(f"git rev-parse --verify {oid[:12]}^{{tree}}", lambda: self.git.rev_parse(self.repo, f"{oid}^{{tree}}"))
        if not tree or not base:
            raise Stop(1, f"cannot name the tree of {oid[:12]} or the base {self.base_ref} (git rev-parse --verify {oid[:12]}^{{tree}}, "
                          f"git rev-parse --verify {self.base_ref})")
        wt = self.worktree(branch, oid)
        red = self.red(engine, tree, base, wt)
        if not red:
            return base
        made = "" if wt else self.fresh(oid)
        wt = wt or made
        argv = [*self.tl, "check", "--repo", wt]
        if profile_change is not None:
            argv.extend(["--policy-commit", base])
        try:
            ran = self.cmds.run(argv)
            red = self.red(engine, tree, base, wt)
        finally:
            if made:
                self.cmds.row(f"git worktree remove {made}", lambda: self.git.remove_worktree_force(self.repo, made))
        if red:
            now = self.moved_during(branch, oid, wt, base)  # a run that judged inputs that changed under it is not a red
            if now and regate:
                self.cmds.log.note(f"{self.base_ref} moved from {base[:12]} to {now[:12]} while the gate ran: gating again on the new base")
                return self.require(branch, oid, profile_change=profile_change, regate=False)
            raise Stop(ran.exit or 1, f"{branch} ({oid[:12]}) is still not green for {self.named(red)} after "
                                      f"`{text_of(argv)}` (exit {ran.exit})")
        return base

    def moved_during(self, branch: str, oid: str, wt: str, base: str) -> str:
        """After a red run: the worktree's HEAD or the base moved while `tl check` ran (a merge of main into the worktree, another
        lander), so the run judged inputs other than the key read before it. A moved HEAD is another tree: nothing was judged, Stop.
        -> the new base when it moved, else ''."""
        head = self.cmds.port(f"git rev-parse HEAD in {wt}", lambda: self.git.rev_parse(wt, "HEAD")) if wt else oid
        if head != oid:
            raise Stop(1, f"{branch}: the worktree {wt} moved from {oid[:12]} to {head[:12]} while the gate ran; nothing is judged. "
                          "Run it again once nothing else changes that worktree")
        now = self.cmds.port(f"git rev-parse --verify {self.base_ref}", lambda: self.git.rev_parse(self.repo, self.base_ref))
        return now if now and now != base else ""

    def fresh(self, oid: str) -> str:
        """A clean worktree detached at `oid`, made for this gate run: a fresh checkout is what a land gate judges anyway."""
        path = tempfile.mkdtemp(prefix="tl-land-gate-")  # an empty directory: git adds a worktree into it
        self.cmds.port(f"git worktree add --detach {path} {oid[:12]}", lambda: self.git.add_worktree(self.repo, path, oid))
        return path
