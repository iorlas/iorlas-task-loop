"""skills/task-loop/tl.py under a Python without its dependencies (plain python3, no site-packages) says in one line to run it
through uv or the shim, instead of a ModuleNotFoundError traceback."""
import subprocess
import sys
import unittest
from pathlib import Path

TL = Path(__file__).resolve().parents[3] / "skills" / "task-loop" / "tl.py"


class PlainPython(unittest.TestCase):
    def test_without_msgspec_it_names_uv_and_the_shim_in_one_line(self) -> None:
        p = subprocess.run([sys.executable, "-S", str(TL), "actor"], capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual((p.returncode, p.stdout), (1, ""))
        self.assertEqual(len(p.stderr.strip().splitlines()), 1, p.stderr)
        self.assertIn("uv run --script", p.stderr)
        self.assertIn("bin/tl", p.stderr)


if __name__ == "__main__":
    unittest.main()
