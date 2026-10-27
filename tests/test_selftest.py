"""`tl selftest` and complete()'s use of it (tl-7y6.5.11): an install that imports but cannot plan a bead is refused."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "skills" / "task-loop"
sys.path.insert(0, str(SRC))
import loop  # noqa: E402
import tl  # noqa: E402


class Moved(Exception):
    pass


class SelfTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(os.path.realpath(self.tmp.name))
        self.cfg = self.home / "cfg"
        self.cache = self.home / "cache"
        p = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.cfg), "APPDATA": str(self.cfg), "HOME": str(self.home),
                                         "USERPROFILE": str(self.home)})
        p.start()
        self.addCleanup(p.stop)
        self.execs = []

        def execv(exe, argv):
            self.execs.append(argv)
            raise Moved()
        for p in (mock.patch.object(os, "execv", side_effect=execv), mock.patch.object(tl, "HERE", self.install("0.1.0"))):
            p.start()
            self.addCleanup(p.stop)

    def install(self, ver, plant=None):
        """A copy of this checkout's skill as an installed version; `plant` (old, new) edits its engine.py."""
        d = self.cache / ver / "skills" / "task-loop"
        shutil.copytree(SRC, d, ignore=shutil.ignore_patterns("__pycache__", "dash"))
        (d.parents[1] / ".claude-plugin").mkdir()
        (d.parents[1] / ".claude-plugin" / "plugin.json").write_text("{}")
        if plant:
            f = d / "engine.py"
            text = f.read_text(encoding="utf-8")
            self.assertIn(plant[0], text)
            f.write_text(text.replace(plant[0], plant[1], 1), encoding="utf-8")
        return d

    def bad_versions(self):
        f = self.cfg / "task-loop" / "bad-versions.json"
        return json.loads(f.read_text()) if f.exists() else {}

    def test_the_scenario_through_engine_run_passes(self):
        r = subprocess.run([sys.executable, str(SRC / "tl.py"), "selftest"], capture_output=True, text=True, timeout=300, cwd=self.home)
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
        with mock.patch.object(subprocess, "Popen", Counting), mock.patch.object(loop, "say"):
            why = loop.selftest()
        print("selftest in-process: %d processes, %.1f s (metric only)" % (len(spawned), time.monotonic() - t))
        self.assertIsNone(why)
        self.assertGreater(len(spawned), 50)  # the counter sees the engine's git work: a zero would mean it counts nothing
        self.assertLess(len(spawned), 250, [x if isinstance(x, str) else " ".join(map(str, x[:3])) for x in spawned[-10:]])

    def test_a_good_install_is_complete_and_moved_to(self):
        self.install("0.2.0")
        self.assertIsNone(loop.complete(self.cache / "0.2.0"))
        self.assertEqual(self.bad_versions(), {})

    def test_an_install_that_imports_but_cannot_plan_is_refused_and_recorded(self):
        d = self.cache / "0.2.0"
        self.install("0.2.0", plant=("    def plan(self, again=False):\n", "    def plan(self, again=False):\n"
                                                                            "        raise RuntimeError('planted: cannot plan')\n"))
        r = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import tl, loop, engine",
                            str(d / "skills" / "task-loop")], capture_output=True)
        self.assertEqual(r.returncode, 0)  # it imports fine
        state = {"warned": []}
        a = mock.Mock(pin=False, argv=["loop", "--repo", str(self.home)])
        out = []
        with mock.patch.object(loop, "say", side_effect=out.append):
            loop.maybe_move(a, str(self.home), state)
        self.assertEqual(self.execs, [])  # never exec'd into it
        self.assertEqual(state["warned"], ["0.2.0"])
        self.assertTrue(any("not moving to 0.2.0: selftest failed" in x and "planted" in x for x in out), out)
        bad = self.bad_versions()
        self.assertEqual(list(bad), ["0.2.0"])
        self.assertIn("planted: cannot plan", bad["0.2.0"]["why"])
        self.assertEqual(bad["0.2.0"]["seen_by"], "0.1.0")

    def test_a_good_newer_install_is_still_moved_to(self):
        self.install("0.2.0")
        a = mock.Mock(pin=False, argv=["loop", "--repo", str(self.home)])
        with self.assertRaises(Moved), mock.patch.object(loop, "say"), mock.patch.object(loop, "stop_mode", return_value=""), \
                mock.patch.object(loop.STOP_NOW, "is_set", return_value=False), \
                mock.patch.object(loop, "START_CWD", [None]):
            loop.maybe_move(a, str(self.home), {"warned": []})
        self.assertIn("0.2.0", self.execs[0][1])


if __name__ == "__main__":
    unittest.main()
