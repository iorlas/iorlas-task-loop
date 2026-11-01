"""The delivery judge for a complete Git push request, using the application's typed profile and check evidence."""
import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path

from taskloop.adapters import check_files
from taskloop.app.checks.cache import green_result, plan_digest
from taskloop.contracts import config
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.ids import TreeSha
from taskloop.contracts.ports import Git
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


def push_tips(stdin: str) -> tuple[PushTip, ...]:
    tips = []
    for line in stdin.splitlines():
        parts = line.split()
        if len(parts) != 4:
            raise ValueError("malformed pre-push ref record")
        if parts[1].strip("0"):
            tips.append(PushTip(*parts))
    return tuple(tips)


def push_profile(repo: str) -> EngineConfig:
    """A missing profile has defaults; an existing unreadable or invalid profile never grants permission."""
    try:
        text = (Path(repo) / ".task-loop.json").read_text(encoding="utf-8")
    except FileNotFoundError:
        text = "{}"
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("the push profile must be an object")
    return config.load(data).engine


class PushJudge:
    def __init__(self, repo: str, cfg: EngineConfig, stores: Stores, git: Git, check: Callable[[], int]) -> None:
        self.repo, self.cfg, self.stores, self.git, self.check = repo, cfg, stores, git, check
        self.repo_key = check_files.repo_key(git, repo)

    def base_for(self, tip: PushTip) -> str:
        if tip.remote_ref == "refs/heads/" + self.cfg.base.split("/", 1)[-1] and tip.remote_sha.strip("0"):
            return tip.remote_sha
        return self.git.rev_parse(self.repo, self.cfg.base)

    def green(self, tip: PushTip, base: str) -> bool:
        tree = self.git.rev_parse(self.repo, tip.sha + "^{tree}")
        return bool(tree and base) and all(
            green_result(self.stores, self.repo_key, step.id, TreeSha(tree), BaseSha(base), plan_digest(self.cfg.plan_cmd)) is not None
            for step in self.cfg.gate_checks)

    def green_or_checked(self, tip: PushTip, base: str) -> bool:
        if self.green(tip, base):
            return True
        if tip.sha != self.git.rev_parse(self.repo, "HEAD") or self.git.dirty(self.repo):
            return False
        if self.check() != 0:
            return False
        if push_profile(self.repo) != self.cfg or self.base_for(tip) != base:
            raise ValueError("profile or base changed during push checks")
        return self.green(tip, base)

    def judge(self, tips: tuple[PushTip, ...]) -> PushDecision:
        bases = [(tip, self.base_for(tip)) for tip in tips]
        stamped = {tip.sha for tip, base in bases if self.green_or_checked(tip, base)}
        refused = tuple(
            f"{tip.ref} ({tip.sha[:12]}) is not green; run `tl check` in its worktree, then push"
            for tip in tips if tip.sha not in stamped
            and not any(self.git.is_ancestor(self.repo, tip.sha, top) for top in stamped))
        return PushDecision(PushStatus.REFUSED if refused else PushStatus.ALLOWED, refused)


def judge_push(repo: str, stdin: str, stores: Stores, git: Git, check: Callable[[], int]) -> PushDecision:
    """Only this application boundary interprets the request. Failed observations never authorize transport."""
    try:
        tips = push_tips(stdin)
        cfg = push_profile(repo)
        if not tips or not cfg.gate_checks:
            return PushDecision(PushStatus.ALLOWED)
        return PushJudge(repo, cfg, stores, git, check).judge(tips)
    except Exception as err:
        return PushDecision(PushStatus.UNAVAILABLE, (f"delivery judge unavailable: {err}",))
