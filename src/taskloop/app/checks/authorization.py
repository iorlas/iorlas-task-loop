"""Delivery queries resolve the judged profile and require its complete check identities."""
import json

from taskloop.adapters import check_files
from taskloop.app.checks import keydiff
from taskloop.app.checks.cache import InputKeys, RunMemo, plan_digest
from taskloop.app.checks.execution import ReadyExecution, Runs, keyed_env, resolve_container
from taskloop.contracts import config
from taskloop.contracts.checks import CheckResult
from taskloop.contracts.env import Env
from taskloop.contracts.ids import CheckId, TreeSha
from taskloop.contracts.ports import Git
from taskloop.contracts.runkey import BaseSha
from taskloop.domain.checks.specs import gate_items, repo_check
from taskloop.stores.bundle import Stores


def profile(git: Git, wt: str, tree: TreeSha) -> config.EngineConfig:
    """The profile of the judged tree, rather than an unrelated checkout's profile."""
    data = json.loads(git.show(wt, tree, ".task-loop.json"))
    if not isinstance(data, dict):
        raise ValueError("the judged profile must be an object")
    return config.load(data).engine


def memo_for(stores: Stores, git: Git, wt: str, cfg: config.EngineConfig, tree: TreeSha, base: BaseSha, env: Env,
             spawner: Runs | None = None) -> RunMemo:
    """The memo a delivery asks: the judged tree's inputs as `wt` holds them (its gitignored files under `inputs` too), the shared
    receipt environment, the container identity resolved only when `wt` has the judged sources out."""
    memo = RunMemo(stores, check_files.repo_key(git, wt), InputKeys(git, wt, tree), base, keyed_env(env))
    memo.checks = {c.id: repo_check(c, cfg) for c in cfg.checks}
    source_matches = (cfg.container is None or not cfg.container.dockerfile
                      or git.rev_parse(wt, "HEAD^{tree}") == tree)
    if any(c.container for c in memo.checks.values()) and spawner is not None and source_matches:
        execution = resolve_container(cfg.container, wt, spawner)
        if isinstance(execution, ReadyExecution):
            memo.executions.update({c.id: execution.identity for c in memo.checks.values() if c.container})
    return memo


def results(stores: Stores, git: Git, wt: str, cfg: config.EngineConfig, tree: TreeSha, base: BaseSha,
            env: Env, step: CheckId | None = None, spawner: Runs | None = None) -> dict[CheckId, CheckResult | None]:
    checks = gate_items(cfg) if step is None else [repo_check(c, cfg) for c in cfg.checks if c.id == step]
    memo = memo_for(stores, git, wt, cfg, tree, base, env, spawner)
    return {c.id: memo.result(c, plan_digest(cfg.plan_cmd)) for c in checks}


def explain(stores: Stores, git: Git, wt: str, cfg: config.EngineConfig, tree: TreeSha, base: BaseSha, env: Env,
            steps: list[CheckId], spawner: Runs | None = None) -> dict[CheckId, str]:
    """{step: the first key field where its expected key and its newest receipt on this tree and base part}; display only."""
    memo = memo_for(stores, git, wt, cfg, tree, base, env, spawner)
    return {c.id: keydiff.why_red(memo, c, plan_digest(cfg.plan_cmd)) for c in gate_items(cfg) if c.id in steps}
