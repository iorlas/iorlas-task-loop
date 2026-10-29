"""`tl selftest` itself. Its use by complete() (a good install is moved to, a broken one refused) is tested in test_reload."""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "skills" / "task-loop"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402, F401

# isort: split
from taskloop.app.launch import selftest  # noqa: E402


class SelfTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(os.path.realpath(self.tmp.name))
        p = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.home / "cfg"), "HOME": str(self.home)})
        p.start()
        self.addCleanup(p.stop)

    def test_the_scenario_through_engine_run_passes(self):
        r = subprocess.run(
            [sys.executable, str(SRC / "tl.py"), "selftest"], capture_output=True, text=True, timeout=300, cwd=self.home, check=False
        )
        self.assertEqual(r.returncode, 0, r.stdout[-800:] + r.stderr[-800:])
        self.assertIn("selftest ok", r.stdout)
        print("selftest duration (metric only):", r.stdout.strip().splitlines()[-1])
        self.assertFalse((Path.home() / ".config").exists())  # the real config dir was never made

    def test_the_scenario_spawns_a_bounded_number_of_processes(self):
        """The old gate was "under 10 s", which a loaded machine fails. A slow selftest is one that spawns far more
        processes than the ~140 (git calls, one check) it takes now; count them instead of timing them."""
        real, spawned = subprocess.Popen, []

        class Counting(real):
            def __init__(self, *a, **k):
                spawned.append(a[0] if a else k.get("args"))
                super().__init__(*a, **k)
        t = time.monotonic()
        with mock.patch.object(subprocess, "Popen", Counting):
            why = selftest.selftest()
        print(f"selftest in-process: {len(spawned)} processes, {time.monotonic() - t:.1f} s (metric only)")
        self.assertIsNone(why)
        self.assertGreater(len(spawned), 50)  # the counter sees the engine's git work: a zero would mean it counts nothing
        self.assertLess(len(spawned), 250, [x if isinstance(x, str) else " ".join(map(str, x[:3])) for x in spawned[-10:]])


if __name__ == "__main__":
    unittest.main()
