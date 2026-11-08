"""RUNENV: the six names every worker, check and gate command is told about its run. The attempt directory is made here, before the
command starts, so a tool writes its logs and results straight into
<run dir>/attempts/<run>-attempt-R/artifacts/<step>/attempt-N (TL_ARTIFACT_DIR);
keep.py adds the check's own log and its `keep` globs to the same directory afterwards."""

from pathlib import Path
from typing import Protocol

from tlkernel import childenv, factorydb
from tlkernel.checkmatchers import safe_name
from tlkernel.gitport import GateGit
from tlkernel.ids import CheckId
from tlkernel.paths import ConfigDir, RunFiles
from tlkernel.slots import git_probe

from tlgate.keep import attempt_dir


class StepEnvHost(Protocol):
    @property
    def home(self) -> ConfigDir: ...
    @property
    def run_id(self) -> str: ...
    @property
    def run_dir(self) -> Path: ...
    @property
    def wt(self) -> str | Path: ...
    @property
    def git(self) -> GateGit: ...


def step_env(host: StepEnvHost, step: str) -> dict[str, str]:
    """TL_RUN_ID, TL_RUN_DIR, TL_ATTEMPT, TL_ARTIFACT_DIR, TL_WORKTREE and TL_BRANCH for the next attempt of `step`; its folder is made."""
    run_attempt = factorydb.attempt_of(host.home.factory_db(), host.run_id) or 1  # the run's own attempt (a takeover starts the next)
    d = attempt_dir(RunFiles(host.run_dir).artifacts(run_attempt) / safe_name(CheckId(step)))
    wt = str(host.wt)
    return childenv.run_env(run_id=host.run_id, run_dir=host.run_dir, attempt=int(d.name.removeprefix("attempt-")), artifact_dir=d,
                            worktree=wt, branch=git_probe(lambda: host.git.branch(wt), ""))
