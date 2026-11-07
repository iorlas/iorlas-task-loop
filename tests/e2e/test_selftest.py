"""`tl selftest` itself. Its use by complete() (a good install is moved to, a broken one refused) is tested in test_reload."""

import contextlib
import io
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "skills" / "task-loop"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# isort: split
import tl  # noqa: E402


class SelfTest(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(os.path.realpath(self.tmp.name))
        p = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.home / "cfg"), "HOME": str(self.home)})
        p.start()
        self.addCleanup(p.stop)

    def test_the_scenario_through_engine_run_passes_in_a_bounded_number_of_processes(self):
        """`tl selftest` as tl.main(argv) in this process (one scenario run, not a second one in a child). The old gate was "under 10 s",
        which a loaded machine fails. A slow selftest is one that spawns far more processes than the ~140 (git calls, one check) it
        takes now; count them instead of timing them."""
        real, spawned, out, err = subprocess.Popen, [], io.StringIO(), io.StringIO()

        class Counting(real):
            def __init__(self, *a, **k):
                spawned.append(a[0] if a else k.get("args"))
                super().__init__(*a, **k)
        with mock.patch.object(subprocess, "Popen", Counting), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = tl.main(["selftest"])
        assert rc == 0, out.getvalue()[-800:] + err.getvalue()[-800:]  # a failure says why on stderr
        assert "selftest ok" in out.getvalue()
        print("selftest:", out.getvalue().strip().splitlines()[-1], f"{len(spawned)} processes (metric only)")
        assert not (Path.home() / ".config").exists()  # the real config dir was never made
        assert len(spawned) > 50  # the counter sees the engine's git work: a zero would mean it counts nothing
        assert len(spawned) < 250, [x if isinstance(x, str) else " ".join(map(str, x[:3])) for x in spawned[-10:]]
