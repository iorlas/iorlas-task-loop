"""The repos index as the code reads it (contracts/snapshots.py ReposIndex, the `repos` row of factory.db): each repo under its folder
name, or `parent/name` when two share one."""
from pathlib import Path

from tlkernel.paths import ConfigDir
from tlkernel.rowstores import ReposStore
from tlkernel.snapshots import RepoEntry, ReposIndex


def write_repos(file: Path | str, *repos: object) -> None:
    """Register `repos` in the config dir the (nominal) `file` sits in."""
    body: dict[str, RepoEntry] = {}
    for r in repos:
        path = Path(str(r))
        name = path.name if path.name not in body else f"{path.parent.name}/{path.name}"
        body[name] = RepoEntry(path=str(r), added=0.0)
    ReposStore(ConfigDir(Path(file).parent)).write(ReposIndex(repos=body))
