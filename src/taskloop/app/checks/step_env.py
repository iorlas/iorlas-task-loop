"""RUNENV: the six names every worker, check and gate command is told about its run. The attempt directory is made here, before the
command starts, so a tool writes its logs and results straight into <run dir>/artifacts/<step>/attempt-N (TL_ARTIFACT_DIR);
keep.py adds the check's own log and its `keep` globs to the same directory afterwards."""
from pathlib import Path

from taskloop.adapters import childenv
from taskloop.app.checks.host import CheckHost
from taskloop.app.checks.keep import attempt_dir
from taskloop.contracts.ids import CheckId
from taskloop.domain.checks.matchers import safe_name


def step_env(host: CheckHost, step: str) -> dict[str, str]:
    """TL_RUN_ID, TL_RUN_DIR, TL_ATTEMPT, TL_ARTIFACT_DIR, TL_WORKTREE and TL_BRANCH for the next attempt of `step`; its folder is made."""
    d = attempt_dir(Path(host.run_dir) / "artifacts" / safe_name(CheckId(step)))
    wt = str(host.wt)
    return childenv.run_env(run_id=host.run_id, run_dir=host.run_dir, attempt=int(d.name.removeprefix("attempt-")), artifact_dir=d,
                            worktree=wt, branch=host.git.branch(wt))
