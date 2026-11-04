"""Complete push transcripts and the whole diagnostic lines shown beside their paths."""
from pathlib import Path
from time import time_ns

from taskloop.adapters.git_base import push_error_line
from taskloop.contracts.paths import ConfigDir, RunFiles


def failure(output: str, run_dir: Path | None, branch: str, config: ConfigDir | None = None) -> str:
    """Keep every attempt separately; commands without a run use the user's land-push folder."""
    stamp = time_ns()
    name = branch.replace("/", "_").replace("\\", "_") or "detached"
    if run_dir is not None:
        path = RunFiles(run_dir).push_log(stamp)
    elif config is not None:
        path = config.land_push(stamp, name)
    else:
        raise ValueError("push evidence needs a run directory or config directory")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(output, encoding="utf-8")
    return f"full push output: {path}\n{push_error_line(output)}"
