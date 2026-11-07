"""Check rounds that cost less: per-check input cache, cheap-first order, duplicate runs, wall limits."""
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.check_host import CheckHostCase
from support.waits import until

from tltestkit import procsim
from tltestkit.procsim import real_proc
from tltestkit.shellkit import POSIX_CHECK, PY, shq


class SpeedTest(CheckHostCase):
    wt: Path
    tmp: Any


    def bump(self, name="count"):
        n = Path(self.tmp.name) / name
        return procsim.fake(f"bump {name}", procsim.appends(n)), n

    def sh_counter(self, code=0):
        """The unity-tests command: counts its runs in a file, prints 'Passed: 12', exits `code`."""
        n = Path(self.tmp.name) / "unity-runs"
        return procsim.fake(f"unity-run {code}", procsim.appends(n, code=int(code), out="Passed: 12")), n

    def notes(self, eng):
        return [json.loads(ln).get("text", "") for ln in eng.log_path.read_text().splitlines() if '"kind": "note"' in ln]


class WallLimit(SpeedTest):
    def alive(self, mark):
        return subprocess.run(["pgrep", "-f", "sleep " + mark], capture_output=True, text=True, check=False).stdout.strip()

    @POSIX_CHECK
    @real_proc("a wall-limit kill reaches a descendant that left the process group (setsid): only a real tree shows it")
    def test_a_timeout_keeps_the_output_and_kills_a_setsid_descendant(self):
        mark = f"72.{os.getpid()}"
        code = (f"import os,subprocess,sys,time\nprint('before', flush=True)\nsubprocess.Popen(['sleep','{mark}'], "
                f"start_new_session=True)\ntime.sleep(30)")
        eng = self.checks_engine(checks=[{"id": "t", "cmd": PY + " -c " + shq(code), "group": "tests", "wall_min": 0.01}])
        res = eng.run_checks({"checks": [], "files": []}, "s")
        assert res[0].exit == 124
        assert "before" in (Path(eng.run_dir) / res[0].log).read_text()
        assert until(lambda: self.alive(mark) == "", limit=5), "the setsid descendant outlived the check"
