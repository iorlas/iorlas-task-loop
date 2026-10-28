import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TL = ROOT / "skills" / "task-loop" / "tl.py"
PY = sys.executable


NO_FCNTL = unittest.skipIf(os.name == "nt", "the lock is fcntl; tl has none on Windows (documented no-op)")


class LandLockTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = self.tmp.name
        self.env = dict(os.environ, XDG_CONFIG_HOME=str(Path(self.tmp.name) / "cfg"))
        subprocess.run(["git", "init", "-q", self.repo], check=True)

    def run_ll(self, *args):
        return subprocess.run([PY, str(TL), "land-lock", "--repo", self.repo] + list(args), env=self.env,
                              capture_output=True, text=True, timeout=30)

    def holder(self, secs, ready):
        self.release = Path(ready).with_name("release")  # the test touches it when the holder has served its purpose
        code = ("import time,pathlib;pathlib.Path(%r).write_text('x');end=time.time()+%s\n"
                "while time.time()<end and not pathlib.Path(%r).exists(): time.sleep(0.01)") % (str(ready), secs, str(self.release))
        p = subprocess.Popen([PY, str(TL), "land-lock", "--repo", self.repo, "--", PY, "-c", code], env=self.env,
                             stdout=subprocess.PIPE, text=True)
        self.addCleanup(p.wait)
        end = time.time() + 10
        while not Path(ready).exists() and time.time() < end:
            time.sleep(0.02)
        self.assertTrue(Path(ready).exists())
        return p

    def test_exit_code_passes_through(self):
        r = self.run_ll("--", PY, "-c", "import sys; print('hi'); sys.exit(3)")
        self.assertEqual(r.returncode, 3)
        self.assertIn("hi", r.stdout)
        self.assertEqual(self.run_ll("--", PY, "-c", "pass").returncode, 0)

    @NO_FCNTL
    def test_second_waits_while_first_holds(self):
        p = self.holder(1.5, Path(self.tmp.name) / "ready")
        t = time.time()
        r = self.run_ll("--", PY, "-c", "print('ran')")
        self.assertEqual(r.returncode, 0)
        self.assertGreater(time.time() - t, 0.5)
        self.assertIn("waiting for the land lock (held by", r.stdout)
        self.assertIn("ran", r.stdout)
        p.wait()

    def test_released_after_failing_command(self):
        self.assertEqual(self.run_ll("--", PY, "-c", "raise SystemExit(7)").returncode, 7)
        r = self.run_ll("--", PY, "-c", "pass")
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("waiting", r.stdout)  # a lock still held would print "waiting"; no timing needed

    @NO_FCNTL
    def test_wait_min_times_out_with_75(self):
        p = self.holder(3, Path(self.tmp.name) / "ready")
        r = self.run_ll("--wait-min", "0.01", "--", PY, "-c", "print('never')")
        self.assertEqual(r.returncode, 75)
        self.assertNotIn("never", r.stdout)
        self.assertIn("land lock", r.stderr)
        self.release.touch()
        p.wait()


if __name__ == "__main__":
    unittest.main()
