"""`tl selftest` itself. Its use by complete() (a good install is moved to, a broken one refused) is tested in test_reload."""

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "skills" / "task-loop"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402, F401
from support.procsim import real_proc  # noqa: E402

# isort: split
import tl  # noqa: E402


class SelfTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(os.path.realpath(self.tmp.name))
        p = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.home / "cfg"), "HOME": str(self.home)})
        p.start()
        self.addCleanup(p.stop)

    @real_proc("the subject is how many real processes the scenario starts")
    def test_the_scenario_through_engine_run_passes_in_a_bounded_number_of_processes(self):
        """`tl selftest` as tl.main(argv) in this process (one scenario run, not a second one in a child). The old gate was "under 10 s",
        which a loaded machine fails. A slow selftest is one that spawns far more processes than the ~140 (git calls, one check) it
        takes now; count them instead of timing them."""
        real, spawned, out = subprocess.Popen, [], io.StringIO()

        class Counting(real):
            def __init__(self, *a, **k):
                spawned.append(a[0] if a else k.get("args"))
                super().__init__(*a, **k)
        with mock.patch.object(subprocess, "Popen", Counting), contextlib.redirect_stdout(out):
            rc = tl.main(["selftest"])
        self.assertEqual(rc, 0, out.getvalue()[-800:])
        self.assertIn("selftest ok", out.getvalue())
        print("selftest:", out.getvalue().strip().splitlines()[-1], f"{len(spawned)} processes (metric only)")
        self.assertFalse((Path.home() / ".config").exists())  # the real config dir was never made
        self.assertGreater(len(spawned), 50)  # the counter sees the engine's git work: a zero would mean it counts nothing
        self.assertLess(len(spawned), 250, [x if isinstance(x, str) else " ".join(map(str, x[:3])) for x in spawned[-10:]])


if __name__ == "__main__":
    unittest.main()
