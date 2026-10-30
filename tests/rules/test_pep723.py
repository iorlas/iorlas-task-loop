"""The scripts that import taskloop.contracts carry a PEP 723 header, and every header declares what pyproject.toml's dependencies do."""
import re
import sys
import tomllib
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ("skills/task-loop/tl.py", "hooks/hook.py", "dev/release.py", "dev/suite.py", "dev/race.py", "dev/dash_fixtures.py")
HEADER = re.compile(r"^# /// script\n((?:#.*\n)+?)# ///$", re.M)


def declared(script: str) -> list[str]:
    block = HEADER.search((ROOT / script).read_text(encoding="utf-8"))
    assert block, f"{script}: no PEP 723 header"
    meta = tomllib.loads("\n".join(line[2:] if line.startswith("# ") else line[1:] for line in block.group(1).splitlines()))
    return meta["dependencies"]


class Headers(unittest.TestCase):
    def test_every_script_declares_the_projects_dependencies(self):
        want = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["dependencies"]
        self.assertTrue(want)
        for script in SCRIPTS:
            with self.subTest(script):
                self.assertEqual(declared(script), want)

    def test_every_script_that_runs_with_uv_names_uv_in_its_shebang(self):
        for script in SCRIPTS:
            with self.subTest(script):
                self.assertEqual((ROOT / script).read_text(encoding="utf-8").splitlines()[0], "#!/usr/bin/env -S uv run --script")


if __name__ == "__main__":
    unittest.main()
