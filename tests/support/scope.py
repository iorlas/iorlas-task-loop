"""Which pieces a run exercises: delegate's tests run only when the change touches delegate (or what it is built on), or when asked for.

`delegate_wanted(args, cwd)`: True when a path argument is inside tests/delegate, when TL_DELEGATE_TESTS=1, or when the change against
the merge base with origin/main touches DELEGATE_PATHS. False when it does not. A tree whose base cannot be found (no git, no
origin/main) cannot say what changed: True, so nothing is skipped by accident."""
import os
import subprocess
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# tests/conftest.py: tests/delegate/real/test_worker_home.py guards the worker homes it sets up
DELEGATE_PATHS = ("src/delegate/", "tests/delegate/", "skills/task-loop/_vendor/", "dev/vendor.json", "tests/conftest.py")


def git(*argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(ROOT), *argv], capture_output=True, text=True, check=False)


def changed_paths() -> set[str] | None:
    """The files the change touches against the merge base with origin/main (committed, modified and untracked); None when unknown."""
    try:
        base = git("merge-base", "HEAD", "origin/main")
    except OSError:
        return None
    if base.returncode != 0:
        return None
    names = set(git("diff", "--name-only", base.stdout.strip()).stdout.split())
    return names | set(git("ls-files", "--others", "--exclude-standard").stdout.split())


def targets_delegate(args: Sequence[str], cwd: Path) -> bool:
    inside = ROOT / "tests" / "delegate"
    for arg in args:
        path = (cwd / str(arg).split("::")[0]).resolve()
        if path == inside or inside in path.parents:
            return True
    return False


def delegate_wanted(args: Sequence[str], cwd: Path) -> bool:
    if os.environ.get("TL_DELEGATE_TESTS") == "1" or targets_delegate(args, cwd):
        return True
    names = changed_paths()
    return names is None or any(n.startswith(DELEGATE_PATHS) for n in names)
