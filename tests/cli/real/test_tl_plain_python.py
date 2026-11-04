"""skills/task-loop/tl.py under a Python without its dependencies (plain python3, no site-packages) says in one line to run it
through uv or the shim, instead of a ModuleNotFoundError traceback."""
import subprocess
import sys
from pathlib import Path

from support.case import Case

TL = Path(__file__).resolve().parents[3] / "skills" / "task-loop" / "tl.py"


class PlainPython(Case):
    def test_without_msgspec_it_names_uv_and_the_shim_in_one_line(self) -> None:
        p = subprocess.run([sys.executable, "-S", str(TL), "actor"], capture_output=True, text=True, timeout=60, check=False)
        assert (p.returncode, p.stdout) == (1, "")
        assert len(p.stderr.strip().splitlines()) == 1, p.stderr
        assert "uv run --script" in p.stderr
        assert "bin/tl" in p.stderr
