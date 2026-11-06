"""A run as the locator finds it: the manifest a test would otherwise leave out. The run id may be any name; the bead is a field."""
from pathlib import Path

from taskloop.contracts.locator import RunBundle, RunLocator
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import RunManifest
from taskloop.contracts.runrows import RunRows


def manifest(cfg: ConfigDir | Path | str, run: str, bead: str, started: float = 0.0, repo: str = "/repo", **fields: object) -> RunBundle:
    """Write authoritative run state (and make the engine folder) -> the run's bundle."""
    cfg = cfg if isinstance(cfg, ConfigDir) else ConfigDir(cfg)
    cfg.run_dir(run).mkdir(parents=True, exist_ok=True)
    m = RunManifest(run=run, repo=repo, bead=bead, started=started, **fields)  # type: ignore[arg-type]
    RunRows(cfg).put(m)
    return RunLocator(cfg).bundle(m)
