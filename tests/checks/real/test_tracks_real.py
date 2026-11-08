"""GATETRACKS (tl-7k8.2) with real processes: a red track stops the other track's whole process tree and no process that is not the
gate's own, and each track's output stays whole in its own log."""
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from support.check_host import CheckHostCase

from tltestkit.procsim import real_proc
from tltestkit.shellkit import POSIX_CHECK, PY, shq
from tltestkit.waits import until

# isort: split
from tlgate.domain.specs import gate_items


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class RealTracks(CheckHostCase):
    def script(self, name: str, body: str) -> str:
        path = Path(self.tmp.name) / name
        path.write_text(body)
        return shlex.join(["sh", str(path)])

    @POSIX_CHECK
    @real_proc("a track's cancel must end its real process tree and touch no other process")
    def test_a_red_track_stops_the_other_tracks_tree_and_nothing_else(self):
        pids = Path(self.tmp.name) / "child.pid"
        bystander = subprocess.Popen(["sleep", "61"], start_new_session=True)  # not the gate's: a kill by pattern would take it
        self.addCleanup(lambda: (bystander.kill(), bystander.wait()))
        slow = self.script("slow.sh", f"sleep 62 &\necho $! > {shlex.quote(str(pids))}\nwait\n")
        red = self.script("red.sh", f"while [ ! -s {shlex.quote(str(pids))} ]; do sleep 0.05; done\necho boom\nexit 1\n")
        eng = self.checks_engine(checks=[{"id": "slow", "cmd": slow, "run": "gate", "track": "heavy"},
                                         {"id": "red", "cmd": red, "run": "gate", "track": "light"}])
        t0 = time.time()
        run = eng.checker.run_items(gate_items(eng.cfg))
        assert time.time() - t0 < 15  # the child sleeps 62 s: the cancel, not its end, ended the track
        child = int(pids.read_text())
        assert until(lambda: not alive(child), limit=5), "the cancelled track's child outlived the cancel"
        assert bystander.poll() is None, "a process the gate did not start was signalled"
        done = {str(c.id): c for c in run.results}
        assert (done["red"].status, done["slow"].status, done["slow"].cancelled) == ("failed", "skipped", True)

    @POSIX_CHECK
    @real_proc("two real tracks write at once: each log must hold only its own lines, whole")
    def test_each_tracks_output_is_whole_in_its_own_log(self):
        lines = 400
        def printer(tag: str) -> str:
            code = f"import time\nfor i in range({lines}):\n    print('{tag}-%d' % i, flush=True)\n    time.sleep(0.001)\n"
            return PY + " -c " + shq(code)

        eng = self.checks_engine(checks=[{"id": "a", "cmd": printer("A"), "run": "gate", "track": "one"},
                                         {"id": "b", "cmd": printer("B"), "run": "gate", "track": "two"}])
        run = eng.checker.run_items(gate_items(eng.cfg))
        assert [c.status for c in run.results] == ["passed", "passed"]
        for res, tag in zip(run.results, "AB", strict=True):
            got = (Path(eng.run_dir) / res.log).read_text().split()
            assert got == [f"{tag}-{i}" for i in range(lines)], res.id
