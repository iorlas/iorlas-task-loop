"""The delivery judge for a complete Git push request, using the application's typed profile and check evidence."""
from dataclasses import dataclass
from enum import IntEnum

from tlgate import authorization
from tlkernel import profile_at
from tlkernel.config import EngineConfig
from tlkernel.env import Env
from tlkernel.gitport import Git
from tlkernel.ids import CheckId, TreeSha
from tlkernel.locks import LockTimeout
from tlkernel.matchers import secrets_added
from tlkernel.paths import ConfigDir
from tlkernel.ports import Clock
from tlkernel.runkey import BaseSha
from tlkernel.slots import MissingRemote

from taskloop.adapters import landlock, locks
from taskloop.adapters.clock import SystemClock
from taskloop.app.land.profile_change import diff_sha
from taskloop.stores.bundle import Stores

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


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

    @property
    def deleting(self) -> bool:
        return not self.sha.strip("0")


class ProfileChanged(Exception):
    """An owner-only policy change cannot be authorized by check evidence."""


class NoPolicyBase(ValueError):
    """No commit of the base ref anchors the policy: a repo with no origin/main yet."""


def push_tips(stdin: str) -> tuple[PushTip, ...]:
    tips = []
    for line in stdin.splitlines():
        parts = line.split()
        if len(parts) != 4:
            raise ValueError("malformed pre-push ref record")
        tips.append(PushTip(*parts))
    return tuple(tips)


class PushJudge:
    def __init__(self, repo: str, stores: Stores, git: Git, env: Env, clock: Clock | None = None, *, guard_main: bool = False,
                 land_lock_held: bool = False) -> None:
        self.repo, self.stores, self.git = repo, stores, git
        self.guard_main, self.land_lock_held = guard_main, land_lock_held
        self.env = env
        self.clock = clock or SystemClock()
        self.unproven: list[CheckId] = []

    def owner_approved(self, tip: str, base: str) -> bool:
        rows = self.stores.profile_changes.read_from().items
        now = self.clock.now()
        candidates = [item.rec for item in rows if item.rec.tip == tip and 0 <= now - item.rec.t <= 600]
        if not candidates:
            return False
        digest = diff_sha(self.git, self.repo, base, tip)
        return any(row.diff_sha == digest for row in candidates)

    def base_ref(self, cfg: EngineConfig | None = None) -> str:
        if cfg is not None:
            return cfg.base
        target = self.git.symbolic_ref(self.repo, "refs/remotes/origin/HEAD")
        return target.removeprefix("refs/remotes/") if target else "origin/main"

    def policy_commit(self, tip: PushTip) -> str:
        base_ref = self.base_ref()
        remote_ref = "refs/heads/" + base_ref.removeprefix("origin/")
        commit = (tip.remote_sha if tip.remote_ref == remote_ref and tip.remote_sha.strip("0")
                  else self.git.merge_base(self.repo, tip.sha, base_ref))
        if not commit:
            raise NoPolicyBase(f"cannot resolve the policy commit for {tip.ref} against {base_ref}")
        return commit

    def policy_profile(self, tip: PushTip) -> EngineConfig | None:
        path = profile_at.FILE
        tip_tree = self.git.rev_parse(self.repo, tip.sha + "^{tree}")
        if not tip_tree:
            raise ValueError(f"cannot name the tree of {tip.sha}")
        try:
            commit = self.policy_commit(tip)
        except NoPolicyBase:
            if self.git.ls_tree(self.repo, tip_tree, path):
                raise  # a profile with no base to anchor it is unprovable: refused
            return None  # no profile and no base ref: a repo that is not ours (a first push to a fresh origin)
        tree = TreeSha(self.git.rev_parse(self.repo, commit + "^{tree}"))
        if not tree:
            raise ValueError(f"cannot name the policy tree of {commit}")
        policy = self.git.ls_tree(self.repo, tree, path)
        proposed = self.git.ls_tree(self.repo, tip_tree, path)
        if ([entry.oid for entry in policy] != [entry.oid for entry in proposed]
                and not self.owner_approved(tip.sha, commit)):
            raise ProfileChanged(f"profile_changed: {tip.ref} changes {path}; only the owner may push a profile change "
                                 "(git push --no-verify)")
        return authorization.profile(self.git, self.repo, tree) if policy else None

    def base_for(self, tip: PushTip, cfg: EngineConfig) -> str:
        if tip.remote_ref == "refs/heads/" + cfg.base.removeprefix("origin/") and tip.remote_sha.strip("0"):
            return tip.remote_sha
        return self.git.rev_parse(self.repo, cfg.base)

    def green(self, cfg: EngineConfig, tree: TreeSha, base: str) -> bool:
        if not tree or not base:
            self.unproven = [step.id for step in cfg.gate_checks]
            return False
        found = authorization.results(self.stores, self.git, self.repo, cfg, tree, BaseSha(base), self.env)
        self.unproven = [step.id for step in cfg.gate_checks if found.get(step.id) is None]
        return not self.unproven

    def is_green(self, tip: PushTip, cfg: EngineConfig | None) -> bool:
        """The receipt of the tip's tree and base, read only: the judge never runs the gate (`tl check` / `tl land-stack` do)."""
        tree = TreeSha(self.git.rev_parse(self.repo, tip.sha + "^{tree}"))
        if not tree:
            raise ValueError(f"cannot name the tree of {tip.sha}")
        if cfg is None or not cfg.gate_checks:
            return True
        return self.green(cfg, tree, self.base_for(tip, cfg))

    def credential_leaks(self, deliveries: list[tuple[PushTip, EngineConfig | None]]) -> tuple[str, ...]:
        """One line per delivered tip whose patch against its base adds a credential."""
        out = []
        for tip, cfg in deliveries:
            # no base (a first push to a fresh origin) means all of it is new
            base = (self.base_for(tip, cfg) if cfg else self.git.rev_parse(self.repo, self.base_ref())) or EMPTY_TREE
            kinds = secrets_added(self.git.diff(self.repo, base, tip.sha))
            if kinds:
                out.append(f"{tip.ref} ({tip.sha[:12]}) adds a credential ({', '.join(kinds)}); remove it (and rotate it), then push")
        return tuple(out)

    def judge(self, tips: tuple[PushTip, ...]) -> PushDecision:
        """A deletion has no tree to prove: it is refused when it removes the base branch, and judged no further."""
        base = "refs/heads/" + self.base_ref().removeprefix("origin/")
        gone = tuple(f"{tip.remote_ref} would be deleted; the base branch is never deleted by a push"
                     for tip in tips if tip.deleting and tip.remote_ref == base)
        if gone:
            return PushDecision(PushStatus.REFUSED, gone)
        tips = tuple(tip for tip in tips if not tip.deleting)
        if unmarked := self.unmarked(tips, base):
            return PushDecision(PushStatus.REFUSED, unmarked)
        try:
            policies = [self.policy_profile(tip) for tip in tips]
        except ProfileChanged as err:
            return PushDecision(PushStatus.REFUSED, (str(err),))
        deliveries = [(tip, cfg) for tip, cfg in zip(tips, policies, strict=True)
                      if tip.remote_ref == "refs/heads/" + self.base_ref(cfg).removeprefix("origin/")]
        if not deliveries:
            return PushDecision(PushStatus.ALLOWED)
        rewinds = tuple(
            f"{tip.ref} ({tip.sha[:12]}) rewinds {tip.remote_ref}: {tip.remote_sha[:12]} is not an ancestor of {tip.sha[:12]}; "
            "only a fast-forward may reach the base branch"
            for tip, _cfg in deliveries if tip.remote_sha.strip("0") and not self.git.is_ancestor(self.repo, tip.remote_sha, tip.sha))
        if rewinds:
            return PushDecision(PushStatus.REFUSED, rewinds)
        decision = self.judge_delivery(deliveries)
        leaks = self.credential_leaks(deliveries) if decision.status == PushStatus.ALLOWED else ()
        return PushDecision(PushStatus.REFUSED, leaks) if leaks else decision

    def unmarked(self, tips: tuple[PushTip, ...], base: str) -> tuple[str, ...]:
        """With the guard on (docs/design/merge-queue.md 8.1): a push to the base branch is tl's own (a land push or a release holds
        the repo's land lock while it pushes) or it is refused. Pushes to any other branch never meet this."""
        if not self.guard_main or self.land_lock_held:
            return ()
        return tuple(f"{tip.ref} ({tip.sha[:12]}) goes to {base} outside `tl land` and the release: land it through the PR flow"
                     for tip in tips if tip.remote_ref == base)

    def why(self, tip: PushTip, cfg: EngineConfig | None) -> dict[CheckId, str]:
        """The first differing key field per unproven step; display only, so a failure to explain never changes the verdict."""
        plain = dict.fromkeys(self.unproven, "no green run of this tree and base")
        if cfg is None:
            return plain
        try:
            tree = TreeSha(self.git.rev_parse(self.repo, tip.sha + "^{tree}"))
            found = authorization.explain(self.stores, self.git, self.repo, cfg, tree, BaseSha(self.base_for(tip, cfg)),
                                          self.env, self.unproven)
        except (ValueError, OSError):
            return plain
        return {step: found.get(step, text) for step, text in plain.items()}

    def judge_delivery(self, deliveries: list[tuple[PushTip, EngineConfig | None]]) -> PushDecision:
        stamped: set[str] = set()
        named: dict[str, str] = {}
        for tip, cfg in deliveries:
            self.unproven = []
            if self.is_green(tip, cfg):
                stamped.add(tip.sha)
            elif self.unproven:
                named[tip.sha] = " for " + ", ".join(f"{s} ({w})" for s, w in self.why(tip, cfg).items())
        refused = tuple(
            f"{tip.ref} ({tip.sha[:12]}) is not green{named.get(tip.sha, '')}; run `tl check` in its worktree, then push"
            for tip, _cfg in deliveries if tip.sha not in stamped
            and not any(self.git.is_ancestor(self.repo, tip.sha, top) for top in stamped))
        return PushDecision(PushStatus.REFUSED if refused else PushStatus.ALLOWED, refused)


def land_lock_held(home: ConfigDir, git: Git, repo: str) -> bool:
    """Whether someone holds the repo's land lock now: a land push and a release take it around their push to the base branch."""
    try:
        url = git.remote_url(repo, "origin")
    except MissingRemote:
        url = ""
    try:
        with locks.hold_path(landlock.land_lock_path(home, url or repo), "judge-probe", timeout=0):
            return False
    except LockTimeout:
        return True


def judge_push(repo: str, stdin: str, stores: Stores, git: Git, *, env: Env, clock: Clock | None = None, guard_main: bool = False,
               land_lock_held: bool = False) -> PushDecision:
    """Only this application boundary interprets the request. Failed observations never authorize transport."""
    try:
        tips = push_tips(stdin)
        return PushJudge(repo, stores, git, env, clock, guard_main=guard_main, land_lock_held=land_lock_held).judge(tips)
    except Exception as err:
        return PushDecision(PushStatus.UNAVAILABLE, (f"delivery judge unavailable: {err}",))
