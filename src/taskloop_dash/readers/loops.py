"""Where a repo's loop files live: the name they share."""

import hashlib
from pathlib import Path


def loop_key(repo: str) -> str:
    """The name the loop files of a repo share (its folder and a hash of its path)."""
    return f"{Path(repo).name}-{hashlib.sha1(repo.encode()).hexdigest()[:8]}"
