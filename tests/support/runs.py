"""A run as the locator finds it: the manifest a test would otherwise leave out. The run id may be any name; the bead is a field."""
from pathlib import Path

from taskloop.contracts.locator import RunBundle, RunLocator
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import RunManifest
from taskloop.contracts.stores import JsonStore


def manifest(cfg: ConfigDir | Path | str, run: str, bead: str, started: float = 0.0, repo: str = "/repo", **fields: object) -> RunBundle:
    """Write runs/<run>/manifest.json (and make the engine folder) -> the run's bundle."""
    cfg = cfg if isinstance(cfg, ConfigDir) else ConfigDir(cfg)
    cfg.run_dir(run).mkdir(parents=True, exist_ok=True)
    cfg.engine_dir().mkdir(parents=True, exist_ok=True)
    m = RunManifest(run=run, repo=repo, bead=bead, started=started, **fields)  # type: ignore[arg-type]
    JsonStore(cfg.run_manifest(run), RunManifest).write(m)
    return RunLocator(cfg).bundle(m)
