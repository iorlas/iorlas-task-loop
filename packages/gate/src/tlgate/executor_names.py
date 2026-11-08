"""Safe repository names for the executor's mirrored directory layout."""

from pathlib import Path

from tlkernel import check_files, reponame
from tlkernel.gitport import GateGit


def executor_repo(git: GateGit, wt: str) -> str:
    """Use the origin or folder name, falling back to the cache key for unsafe names."""
    common = git.common_dir(wt)
    root = Path(common).parent if common else Path(wt)
    name = reponame.repo_name(str(root))
    segments = name.split("/")
    if all(
        segment
        and segment not in {".", ".."}
        and segment[0].isascii()
        and segment[0].isalnum()
        and all(c.isascii() and (c.isalnum() or c in "._-") for c in segment)
        for segment in segments
    ):
        return name
    return str(check_files.repo_key(git, wt))
