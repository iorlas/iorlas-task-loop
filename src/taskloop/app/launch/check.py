"""Bind standalone checks to the worktree, runner host and observable stage lifecycle."""
import argparse
from collections.abc import Generator
from contextlib import contextmanager, nullcontext
from pathlib import Path

from tlkernel.checks import CheckRun
from tlkernel.config import EngineConfig
from tlkernel.env import Env
from tlkernel.gitport import Git
from tlkernel.identity import Identity
from tlkernel.procport import Spawner

from taskloop.app.checks import authorization, checklog, runner
from taskloop.app.checks.host import CheckHost
from taskloop.app.launch.check_host import CliHost
from taskloop.app.launch.staged import staged_tree
from taskloop.app.pipeline.stage_run import StageRun, stage_run
from taskloop.app.slots import config as wslots_config

Checker = runner.Checker
with_base = authorization.with_base
policy_of = authorization.policy_of


def profile_of(repo: str) -> EngineConfig:
    return authorization.profile_of(repo, wslots_config.load_profile)


def cmd_check(a: argparse.Namespace, *, who: Identity, env: Env, spawner: Spawner, git: Git,
              policy: EngineConfig | None = None) -> int:
    repo = git.toplevel(a.repo) or str(Path(a.repo).resolve())
    with stage_run(who, repo, f"stage:{a.cmd}") as stage:
        stage.rc = run_check(a, stage, env=env, spawner=spawner, git=git, policy=policy)
        return stage.rc


def run_check(a: argparse.Namespace, stage: StageRun, *, env: Env, spawner: Spawner, git: Git,
              policy: EngineConfig | None = None) -> int:
    repo = stage.bundle.repo

    def profile() -> EngineConfig:
        return authorization.selected_profile(policy, a.policy_commit, lambda: profile_of(repo),
                                              lambda commit: policy_of(repo, git, commit))

    @contextmanager
    def workspace(cfg: EngineConfig, staged: bool) -> Generator[CheckHost]:
        with authorization.checkout(staged, lambda: staged_tree(git, repo), nullcontext((repo, None))) as (wt, names):
            yield CliHost(wt, cfg, stores=stage.stores, bundle=stage.bundle, log=stage.log, env=env,
                          spawner=spawner, git=git, staged=names)

    def save(run: CheckRun) -> None:
        stage.stores.check_run(stage.bundle.run, run.round).write(run)

    return checklog.standalone(a, profile=profile, workspace=workspace, save=save, checker=Checker)
