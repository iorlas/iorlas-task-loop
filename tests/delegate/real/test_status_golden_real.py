"""route.py status --json --cheap prints exactly the bytes in tests/fixtures/status_cheap.golden.json for the fixture config dir
(state, snapshot, hold, logins).
Runs the real launcher in a subprocess from a copy of delegate and its vendored packages, as the installed copy runs it."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import hermetic  # noqa: F401  (a home of its own for every test)

from tltestkit.procsim import real_proc
from tltestkit.tmpdir import TemporaryDirectory

LIMIT_S = 30  # a cold interpreter compiles a fresh copy of the tree (no __pycache__) before it prints
ROOT = Path(__file__).resolve().parents[3]
FIX = ROOT / "tests" / "delegate" / "fixtures"


class StatusGolden:
    @real_proc("delegate: a worker, git or CLI process")
    def test_cheap_status_is_byte_equal_from_a_copy_of_the_tree(self):
        with TemporaryDirectory() as d:
            tree, cfg = Path(d) / "plugin", Path(d) / "cfg"
            shutil.copytree(FIX / "status_cheap", cfg)
            os.chmod(cfg, 0o700)
            # delegate's code and the shelf packages it vendors (delegate/__init__ puts skills/task-loop/_vendor on sys.path)
            for part in (Path("src") / "delegate", Path("skills") / "task-loop" / "_vendor"):
                shutil.copytree(ROOT / part, tree / part, ignore=shutil.ignore_patterns("__pycache__"))
            env = dict(os.environ, DELEGATE_CONFIG_DIR=str(cfg), DELEGATE_NOW="1800000000")
            r = subprocess.run(
                [sys.executable, str(tree / "src" / "delegate" / "entry.py"), "status", "--json", "--cheap"],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )
        assert r.returncode == 0, r.stderr
        assert r.stdout == (FIX / "status_cheap.golden.json").read_text(encoding="utf-8")
