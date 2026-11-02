"""The delivery judge for a complete Git push request, using the application's typed profile and check evidence."""
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

from taskloop.adapters.clock import SystemClock
from taskloop.app.checks import authorization
from taskloop.app.checks.execution import Runs
from taskloop.app.land.profile_change import diff_sha
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.env import Env
from taskloop.contracts.ids import TreeSha
from taskloop.contracts.ports import Clock, Git
from taskloop.contracts.runkey import BaseSha
from taskloop.stores.bundle import Stores


class PushStatus(IntEnum):
    ALLOWED = 0
    REFUSED = 1
    UNAVAILABLE = 2


@dataclass(frozen=True)
class PushDecision:
    status: PushStatus
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class PushTip:
    ref: str
    sha: str
    remote_ref: str
    remote_sha: str


class ProfileChanged(Exception):
    """An owner-only policy change cannot be authorized by check evidence."""


def push_tips(stdin: str) -> tuple[PushTip, ...]:
    tips = []
    for line in stdin.splitlines():
        parts = line.split()
        if len(parts) != 4:
            raise ValueError("malformed pre-push ref record")
        if parts[1].strip("0"):
            tips.append(PushTip(*parts))
    return tuple(tips)


class PushJudge:
    def __init__(self, repo: str, stores: Stores, git: Git, check: Callable[[EngineConfig], int], env: Env, spawner: Runs | None,
                 clock: Clock | None = None) -> None:
        self.repo, self.stores, self.git, self.check = repo, stores, git, check
        self.env, self.spawner = env, spawner
        self.clock = clock or SystemClock()
        self.unproven: list[str] = []

    def owner_approved(self, tip: str, base: str) -> bool:
        rows = self.stores.profile_changes.read_from().items
        now = self.clock.now()
        candidates = [item.rec for item in rows if item.rec.tip == tip and 0 <= now - item.rec.t <= 600]
        if not candidates:
            return False
        digest = diff_sha(self.git, self.repo, base, tip)
        return any(row.diff_sha == digest for row in candidates)

    def policy_commit(self, tip: PushTip) -> str:
        target = self.git.symbolic_ref(self.repo, "refs/remotes/origin/HEAD")
        base_ref = target.removeprefix("refs/remotes/") if target else "origin/main"
        remote_ref = "refs/heads/" + base_ref.removeprefix("origin/")
        commit = (tip.remote_sha if tip.remote_ref == remote_ref and tip.remote_sha.strip("0")
                  else self.git.merge_base(self.repo, tip.sha, base_ref))
        if not commit:
            raise ValueError(f"cannot resolve the policy commit for {tip.ref} against {base_ref}")
        return commit

    def policy_profile(self, tip: PushTip) -> EngineConfig | None:
        commit = self.policy_commit(tip)
        tree = TreeSha(self.git.rev_parse(self.repo, commit + "^{tree}"))
        if not tree:
            raise ValueError(f"cannot name the policy tree of {commit}")
        path = ".task-loop.json"
        policy = self.git.ls_tree(self.repo, tree, path)
        tip_tree = self.git.rev_parse(self.repo, tip.sha + "^{tree}")
        if not tip_tree:
            raise ValueError(f"cannot name the tree of {tip.sha}")
        proposed = self.git.ls_tree(self.repo, tip_tree, path)
        if ([entry.oid for entry in policy] != [entry.oid for entry in proposed]
                and not self.owner_approved(tip.sha, commit)):
            raise ProfileChanged(f"profile_changed: {tip.ref} changes {path}; only the owner may push a profile change "
                                 "(git push --no-verify)")
        return authorization.profile(self.git, self.repo, tree) if policy else None

    def base_for(self, tip: PushTip, cfg: EngineConfig) -> str:
        if tip.remote_ref == "refs/heads/" + cfg.base.split("/", 1)[-1] and tip.remote_sha.strip("0"):
            return tip.remote_sha
        return self.git.rev_parse(self.repo, cfg.base)

    def green(self, cfg: EngineConfig, tree: TreeSha, base: str) -> bool:
        if not tree or not base:
            self.unproven = [step.id for step in cfg.gate_checks]
            return False
        found = authorization.results(self.stores, self.git, self.repo, cfg, tree, BaseSha(base), self.env,
                                      spawner=self.spawner)
        self.unproven = [step.id for step in cfg.gate_checks if found.get(step.id) is None]
        return not self.unproven

    def green_or_checked(self, tip: PushTip, cfg: EngineConfig | None) -> bool:
        tree = TreeSha(self.git.rev_parse(self.repo, tip.sha + "^{tree}"))
        if not tree:
            raise ValueError(f"cannot name the tree of {tip.sha}")
        if cfg is None or not cfg.gate_checks:
            return True
        base = self.base_for(tip, cfg)
        if self.green(cfg, tree, base):
            return True
        if tip.sha != self.git.rev_parse(self.repo, "HEAD") or self.git.dirty(self.repo):
            return False
        if (Path(self.repo) / ".task-loop.json").read_bytes() != self.git.show(self.repo, tip.sha, ".task-loop.json").encode("utf-8"):
            raise ValueError("worktree .task-loop.json differs from the judged profile")
        if self.check(cfg) != 0:
            return False
        if (self.git.rev_parse(self.repo, "HEAD") != tip.sha or self.git.dirty(self.repo)
                or self.git.rev_parse(self.repo, tip.sha + "^{tree}") != tree or self.base_for(tip, cfg) != base):
            raise ValueError("tree, checkout or base changed during push checks")
        return self.green(cfg, tree, base)

    def judge(self, tips: tuple[PushTip, ...]) -> PushDecision:
        try:
            policies = [self.policy_profile(tip) for tip in tips]
        except ProfileChanged as err:
            return PushDecision(PushStatus.REFUSED, (str(err),))
        stamped: set[str] = set()
        named: dict[str, str] = {}
        for tip, cfg in zip(tips, policies, strict=True):
            self.unproven = []
            if self.green_or_checked(tip, cfg):
                stamped.add(tip.sha)
            elif self.unproven:
                named[tip.sha] = " for " + ", ".join(f"{s} (no receipt for this tree and base)" for s in self.unproven)
        refused = tuple(
            f"{tip.ref} ({tip.sha[:12]}) is not green{named.get(tip.sha, '')}; run `tl check` in its worktree, then push"
            for tip in tips if tip.sha not in stamped
            and not any(self.git.is_ancestor(self.repo, tip.sha, top) for top in stamped))
        return PushDecision(PushStatus.REFUSED if refused else PushStatus.ALLOWED, refused)


def judge_push(repo: str, stdin: str, stores: Stores, git: Git, check: Callable[[EngineConfig], int], *,
               env: Env, spawner: Runs | None = None, clock: Clock | None = None) -> PushDecision:
    """Only this application boundary interprets the request. Failed observations never authorize transport."""
    try:
        tips = push_tips(stdin)
        return PushJudge(repo, stores, git, check, env, spawner, clock).judge(tips)
    except Exception as err:
        return PushDecision(PushStatus.UNAVAILABLE, (f"delivery judge unavailable: {err}",))
