"""The real Spawner detaches a harmless stand-in from a launcher that exits."""
import json
import sys
import tempfile
import time
from pathlib import Path

import support.paths
from support.case import Case

from taskloop.adapters import procs


class DetachedFactory(Case):
    def test_child_survives_launchers_process_group_with_null_stdin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            proof, recorded = root / "proof.json", root / "loop.pid"
            standin = (
                "import json, os, stat, sys, time\n"
                "s = os.fstat(0); null = os.stat('/dev/null')\n"
                "with open(sys.argv[1] + '.tmp', 'w') as f:\n"
                " json.dump({'pid': os.getpid(), 'pgid': os.getpgrp(), "
                "'null': stat.S_ISCHR(s.st_mode) and s.st_rdev == null.st_rdev}, f)\n"
                "os.replace(sys.argv[1] + '.tmp', sys.argv[1])\n"
                "time.sleep(60)\n"
            )
            launcher = (
                "import json, sys\n"
                f"sys.path[:0] = {[support.paths.SRC, support.paths.VENDOR]!r}\n"
                "from pathlib import Path\n"
                "from taskloop.adapters import procs\n"
                "from taskloop.adapters.spawner import RealSpawner\n"
                "from taskloop.contracts.env import Env\n"
                f"with open({str(root / 'log')!r}, 'ab') as out:\n"
                f" child = RealSpawner(Env({{}})).start({[sys.executable, '-c', standin, str(proof)]!r}, out=out)\n"
                f"Path({str(recorded)!r}).write_text(json.dumps({{'pid': child.pid, 'start': procs.proc_start(child.pid)}}))\n"
            )
            parent = procs.spawn([sys.executable, "-c", launcher])
            child = None
            try:
                assert parent.wait(timeout=30) == 0
                record = json.loads(recorded.read_text())
                assert record["start"]
                child = procs.PidHandle(record["pid"], record["start"])
                child_pid = child.pid
                until = time.monotonic() + 30
                while (not proof.exists() or not proof.stat().st_size) and time.monotonic() < until:
                    time.sleep(0.02)
                facts = json.loads(proof.read_text())
                assert facts["pid"] == child_pid
                assert facts["pgid"] != parent.pid
                assert facts["pgid"] == child_pid
                assert facts["null"]
                assert not procs.alive(parent.pid)
                assert not any(row.pgid == parent.pid for row in (procs.table() or {}).values())
                assert procs.alive(child_pid)
                assert procs.stop_pid(child.pid, child.start, grace=0.2) == ()
                assert not procs.alive(child_pid)
            finally:
                if child is None and recorded.exists():
                    record = json.loads(recorded.read_text())
                    if record["start"]:
                        child = procs.PidHandle(record["pid"], record["start"])
                if child is not None:
                    procs.stop_pid(child.pid, child.start, grace=0.2)
                procs.stop_pid(parent.pid, grace=0.2)
