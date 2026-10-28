"""Looking at an install of task-loop from outside: does it import, does its selftest pass. Each runs the install's own code
in a child python, so a broken copy fails here and not in the loop that would move to it."""
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

IMPORT = "import sys; sys.path.insert(0, sys.argv[1]); sys.path.insert(0, sys.argv[2]); [__import__(m) for m in sys.argv[3:]]"


def import_fails(here: Path, src: Path, modules: Sequence[str], wait: float) -> str | None:
    """None when every module imports from the install at `here`, else why not."""
    try:
        r = subprocess.run([sys.executable, "-I", "-c", IMPORT, str(here), str(src), *modules], stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=wait, check=False)
    except subprocess.TimeoutExpired:
        return f"importing {', '.join(modules)} did not finish in {wait:g} s"
    except OSError as e:
        return f"python did not start: {e}"
    return None if r.returncode == 0 else f"importing {', '.join(modules)} exited {r.returncode}"


def selftest_fails(here: Path, wait: float) -> str | None:
    """None when `tl.py selftest` of the install at `here` passes, else the tail of what it said."""
    try:
        r = subprocess.run([sys.executable, str(here / "tl.py"), "selftest"], stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", timeout=wait, cwd=here, check=False)
    except subprocess.TimeoutExpired:
        return f"did not finish in {wait:g} s"
    except OSError as e:
        return f"python did not start: {e}"
    if r.returncode == 0:
        return None
    return f"exit {r.returncode}: {((r.stderr or '') + (r.stdout or '')).strip()[-300:]}"
