"""A question put to git by a test about a repo it set up (the code under test goes through the Git port; a test reads the result here)."""

import subprocess
from pathlib import Path

from taskloop.adapters.childenv import tool_env
from taskloop.adapters.gitrepo import pinned_env
from taskloop.contracts.env import snapshot


def git(*args: str, cwd: str | Path) -> str:
    """The stripped stdout of `git ARGS` in `cwd` pinned to its checkout ("" when it fails)."""
    r = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=tool_env(snapshot().vars, pinned_env(cwd)),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return r.stdout.strip() if r.returncode == 0 else ""
