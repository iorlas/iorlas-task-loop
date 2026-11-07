"""Delivery queries resolve the judged profile and require its complete check identities."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path

from tlkernel import check_files, config, profile_at
from tlkernel.checks import CheckResult
from tlkernel.env import Env
from tlkernel.gitport import GateGit
from tlkernel.ids import CheckId, TreeSha
from tlkernel.runkey import BaseSha

from tlgate import keydiff
from tlgate.cache import InputKeys, RunMemo, plan_digest
from tlgate.domain.specs import gate_items, repo_check
from tlgate.execution import keyed_env
from tlgate.ports import GateStores


def profile(git: GateGit, wt: str, tree: TreeSha) -> config.EngineConfig:
    """The profile of the judged tree, rather than an unrelated checkout's profile."""
    found = profile_at.profile_at(git, wt, tree)
    if found is None:
        raise ValueError(f"the judged tree {tree} has no {profile_at.FILE}")
    return found.engine


def memo_for(stores: GateStores, git: GateGit, wt: str, cfg: config.EngineConfig, tree: TreeSha, base: BaseSha, env: Env) -> RunMemo:
    """The memo a delivery asks: the judged tree's inputs as `wt` holds them (its gitignored files under `inputs` too), the shared
    receipt environment."""
    memo = RunMemo(stores, check_files.repo_key(git, wt), InputKeys(git, wt, tree, pins=cfg.pin_files), base, keyed_env(env),
                   executor=cfg.executor.host)
    memo.checks = {c.id: repo_check(c, cfg) for c in cfg.checks}
    return memo


def results(stores: GateStores, git: GateGit, wt: str, cfg: config.EngineConfig, tree: TreeSha, base: BaseSha,
            env: Env, step: CheckId | None = None) -> dict[CheckId, CheckResult | None]:
    checks = gate_items(cfg) if step is None else [repo_check(c, cfg) for c in cfg.checks if c.id == step]
    memo = memo_for(stores, git, wt, cfg, tree, base, env)
    return {c.id: memo.result(c, plan_digest(cfg.plan_cmd)) for c in checks}


def explain(stores: GateStores, git: GateGit, wt: str, cfg: config.EngineConfig, tree: TreeSha, base: BaseSha, env: Env,
            steps: list[CheckId]) -> dict[CheckId, str]:
    """{step: the first key field where its expected key and its newest receipt on this tree and base part}; display only."""
    memo = memo_for(stores, git, wt, cfg, tree, base, env)
    return {c.id: keydiff.why_red(memo, c, plan_digest(cfg.plan_cmd)) for c in gate_items(cfg) if c.id in steps}


def profile_of(repo: str, load_profile: Callable[[object], config.RepoProfile]) -> config.EngineConfig:
    """The engine block of the worktree's own .task-loop.json (what a person edited, committed or not)."""
    path = Path(repo) / profile_at.FILE
    try:
        data = profile_at.raw_in(repo)
    except (OSError, ValueError) as e:
        raise SystemExit(f"tl check: cannot read {path}: {e}") from None
    if data is None:
        raise SystemExit(f"tl check: cannot read {path}: no such file")
    return load_profile(data).engine


def policy_of(repo: str, git: GateGit, commit: str) -> config.EngineConfig:
    """Delivery checks use the committed base registry; ordinary tl check uses the worktree."""
    return profile(git, repo, TreeSha(commit))


def with_base(cfg: config.EngineConfig, commit: str | None) -> config.EngineConfig:
    """`tl check --base-commit SHA`: the run's base (what receipts are keyed at, and what the changed files are measured against) is that
    commit, not the base branch. The merge queue gates Q(N) at Q(N-1) (docs/design/merge-queue.md 3.5). No commit: `cfg` as it is."""
    return cfg.replace(base=commit) if commit else cfg


def selected_profile(policy: config.EngineConfig | None, commit: str | None,
                     working: Callable[[], config.EngineConfig],
                     committed: Callable[[str], config.EngineConfig]) -> config.EngineConfig:
    """An explicitly bound policy wins over the committed or working registry."""
    return policy if policy is not None else committed(commit) if commit else working()


def checkout(staged: bool, index: Callable[[], AbstractContextManager[tuple[str | Path, list[str] | None]]],
             working: AbstractContextManager[tuple[str | Path, list[str] | None]],
             ) -> AbstractContextManager[tuple[str | Path, list[str] | None]]:
    """Choose the index snapshot only when staged files were requested."""
    return index() if staged else working
