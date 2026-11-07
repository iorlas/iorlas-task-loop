"""The gate of `tl land-stack`: before an item is pushed or merged, every gate step of the base commit's profile (checks with run gate or
both, as the pre-push hook reads them) must have evidence for their full resolved keys on the item's tree and base. A step that is
not green is run once, as `tl check --repo W` in a clean worktree W that has the branch (or a detached HEAD) out at that very oid,
and asked again; with no such worktree the gate makes one (detached at the oid, removed after the run), so the caller never runs a
command by hand. Still not green: it stops with the check's exit code. Each refused step says the first key field that differs
from its newest receipt on the tree and base. A commit with no gate step passes. Its plan_cmd identifies the producer of planned skips."""
import threading

from tlgate.api import authorization
from tlkernel import config, profile_at, scratch
from tlkernel.argv import text_of
from tlkernel.env import Env
from tlkernel.envvars import EnvVar
from tlkernel.gitport import Git
from tlkernel.ids import CheckId, TreeSha
from tlkernel.runkey import BaseSha
from tlkernel.slots import NotARepo

from taskloop.app.land.carry import Carry
from taskloop.app.land.cmds import Cmds, Stop
from taskloop.app.land.gate import owner_refusal
from taskloop.stores.bundle import Stores


class StackGate:
    def __init__(self, cmds: Cmds, git: Git, stores: Stores, repo: str, base_ref: str, tl: list[str], env: Env | None = None) -> None:
        self.cmds, self.git, self.stores, self.repo, self.base_ref, self.tl = cmds, git, stores, repo, base_ref, tl
        self.env = env or Env()
        self.ledger_env = self.env.with_(EnvVar.TL_GREEN_LEDGER, "1")  # the gate's own run skips test files already green (dev/runtests.py)
        self.ledger = {EnvVar.TL_GREEN_LEDGER.value: "1"}
        self.why: dict[CheckId, str] = {}  # the last red()'s steps: the first key field that differs from their newest receipt

    def profile(self, oid: str) -> config.EngineConfig | None:
        try:
            found = self.cmds.port(f"git show {oid}:{profile_at.FILE}", lambda: profile_at.profile_at(self.git, self.repo, oid))
        except (ValueError, config.ConfigError) as e:
            raise Stop(1, f"cannot read the gate from {oid}:{profile_at.FILE}: {e}") from None
        return found.engine if found else None  # no profile at the base commit: no gate step

    def red(self, engine: config.EngineConfig, tree: str, base: str, wt: str = "", env: Env | None = None) -> list[CheckId]:
        """The steps with no green receipt under `env` (the plain key by default; `ledger_env` is the key of a ledger-assisted run)."""
        env = env or self.env
        found = authorization.results(self.stores, self.git, wt or self.repo, engine, TreeSha(tree), BaseSha(base), env)
        red = [step for step, result in found.items() if result is None]
        self.why = (authorization.explain(self.stores, self.git, wt or self.repo, engine, TreeSha(tree), BaseSha(base), env, red)
                    if red else {})
        return red

    def unproven(self, engine: config.EngineConfig, tree: str, base: str, wt: str = "") -> list[CheckId]:
        """The steps with neither a full receipt nor a ledger-assisted one (the gate's own kind) on this tree and base."""
        return self.red(engine, tree, base, wt) and self.red(engine, tree, base, wt, env=self.ledger_env)

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

    def require(self, branch: str, oid: str, *, profile_change: str | None = None, regate: bool = True, base_override: str = "") -> str:
        """`base_override`: the merge queue gates Q(N) at Q(N-1) (merge-queue.md 3.5), not at the base branch; main moving is then the
        queue's business, so no closure carry and no regate."""
        if why := owner_refusal(profile_change, self.env):
            raise Stop(2, why)
        base = base_override or self.cmds.port(f"git rev-parse --verify {self.base_ref}",
                                               lambda: self.git.rev_parse(self.repo, self.base_ref))
        if not base:
            raise Stop(1, f"cannot name the base {self.base_ref}")
        path = profile_at.FILE
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
        red = self.unproven(engine, tree, base, wt)
        if not red:
            return base
        made = "" if wt else self.fresh(oid)
        wt = wt or made
        argv = [*self.tl, "check", "--repo", wt, *(["--policy-commit", base] if profile_change is not None else []),
                *(["--base-commit", base] if base_override else [])]
        try:
            carry = Carry(self.cmds, self.git, self.stores, self.repo, self.env)
            if not base_override and sum(carry.carried(engine, step, oid, tree, base, wt) for step in red):  # a pass on an earlier base
                red = self.unproven(engine, tree, base, wt)
            ran = self.cmds.run(argv, extra=self.ledger) if red else None
            red = self.unproven(engine, tree, base, wt) if ran else red
            now = self.moved_during(branch, oid, wt, base, queued=bool(base_override)) if red else ""  # while the checkout still exists
        finally:
            if made:
                self.cmds.row(f"git worktree remove {made}", lambda: self.git.remove_worktree_force(self.repo, made))
        if red:
            if now and regate:  # a run that judged inputs that changed under it is not a red
                self.cmds.log.note(f"{self.base_ref} moved from {base[:12]} to {now[:12]} while the gate ran: gating again on the new base")
                return self.require(branch, oid, profile_change=profile_change, regate=False)
            raise Stop(ran.exit if ran and ran.exit else 1, f"{branch} ({oid[:12]}) is still not green for {self.named(red)} after "
                                                      f"`{text_of(argv)}` (exit {ran.exit if ran else 'not run'})")
        return base

    def needs_run(self, oid: str) -> bool:
        """True when a gate step of the base's profile has no evidence for this oid yet: a `tl check` would be run for it (a read only;
        a profile change or a missing base is `require`'s to refuse)."""
        base = self.cmds.port(f"git rev-parse --verify {self.base_ref}", lambda: self.git.rev_parse(self.repo, self.base_ref))
        engine = self.profile(base) if base else None
        if engine is None or not engine.gate_checks:
            return False
        tree = self.cmds.port(f"git rev-parse --verify {oid[:12]}^{{tree}}", lambda: self.git.rev_parse(self.repo, f"{oid}^{{tree}}"))
        return bool(tree) and bool(self.unproven(engine, tree, base))

    def warm(self, oid: str, git_lock: threading.Lock) -> int:
        """Run `tl check` for the oid in a fresh worktree, the one `require` would make, so its receipts exist when `require` asks. Runs in
        a worker thread: only the spawner runs outside `git_lock` and nothing here writes a log row; -> the check's exit code."""
        with git_lock:
            path = self.fresh(oid)
        try:
            return self.cmds.spawner.run([*self.tl, "check", "--repo", path], cwd=path, extra=self.ledger).exit
        finally:
            with git_lock:
                self.cmds.row(f"git worktree remove {path}", lambda: self.git.remove_worktree_force(self.repo, path))

    def moved_during(self, branch: str, oid: str, wt: str, base: str, *, queued: bool = False) -> str:
        """After a red run: the worktree's HEAD or the base moved while `tl check` ran (a merge of main into the worktree, another
        lander), so the run judged inputs other than the key read before it. A moved HEAD is another tree: nothing was judged, Stop.
        -> the new base when it moved, else ''. A queued gate has no moving base: only the HEAD is compared."""
        head = self.cmds.port(f"git rev-parse HEAD in {wt}", lambda: self.git.rev_parse(wt, "HEAD")) if wt else oid
        if head != oid:
            raise Stop(1, f"{branch}: the worktree {wt} moved from {oid[:12]} to {head[:12]} while the gate ran; nothing is judged. "
                          "Run it again once nothing else changes that worktree")
        if queued:
            return ""
        now = self.cmds.port(f"git rev-parse --verify {self.base_ref}", lambda: self.git.rev_parse(self.repo, self.base_ref))
        return now if now and now != base else ""

    def fresh(self, oid: str) -> str:
        """A clean worktree detached at `oid`, made for this gate run: a fresh checkout is what a land gate judges anyway."""
        path = str(scratch.scratch_dir(self.env.vars, "tl-land-gate-"))  # an empty directory: git adds a worktree into it
        self.cmds.port(f"git worktree add --detach {path} {oid[:12]}", lambda: self.git.add_worktree(self.repo, path, oid))
        return path

    def judge_queue(self, q: str, parent: str, git_lock: threading.Lock) -> bool:
        """The gate of one queue entry (a worker thread, like `warm`): `tl check --base-commit parent` on a fresh worktree at Q(N), then
        whether every gate step has its receipt at that tree and base. A profile change does not ride the queue: it needs the owner."""
        with git_lock:
            engine = self.profile(parent)
            if engine is None or not engine.gate_checks:
                return True
            path = profile_at.FILE
            if self.git.ls_tree(self.repo, parent, path) != self.git.ls_tree(self.repo, q, path):
                self.cmds.log.note(f"queue: {q[:12]} changes {path}; only the owner may land a profile change")
                return False
            tree = self.git.rev_parse(self.repo, f"{q}^{{tree}}")
            wt = self.fresh(q)
        try:
            self.cmds.spawner.run([*self.tl, "check", "--repo", wt, "--base-commit", parent], cwd=wt, extra=self.ledger)
            with git_lock:
                return not self.unproven(engine, tree, parent, wt)
        finally:
            with git_lock:
                self.cmds.row(f"git worktree remove {wt}", lambda: self.git.remove_worktree_force(self.repo, wt))

    def carry_queue(self, q: str, parent: str) -> None:
        """Entries ahead landed: main has the tree of `parent`. Each gate step green at Q(N)'s base `parent` now counts at main too
        (`Carry.queue_carried`); what does not carry is run again by the land's own gate."""
        engine = self.profile(parent)
        if engine is None or not engine.gate_checks:
            return
        main = self.cmds.port(f"git rev-parse --verify {self.base_ref}", lambda: self.git.rev_parse(self.repo, self.base_ref))
        tree = self.git.rev_parse(self.repo, f"{q}^{{tree}}")
        wt = self.fresh(q)
        try:
            carry = Carry(self.cmds, self.git, self.stores, self.repo, self.env)
            for step in self.unproven(engine, tree, main, wt):
                carry.queue_carried(engine, step, tree, main, parent, wt)
        finally:
            self.cmds.row(f"git worktree remove {wt}", lambda: self.git.remove_worktree_force(self.repo, wt))
