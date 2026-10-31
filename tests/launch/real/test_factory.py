"""The real Spawner detaches a harmless stand-in from a launcher that exits."""
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

import support.paths

from taskloop.adapters import procs


class DetachedFactory(unittest.TestCase):
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
                self.assertEqual(parent.wait(timeout=5), 0)
                record = json.loads(recorded.read_text())
                self.assertTrue(record["start"])
                child = procs.PidHandle(record["pid"], record["start"])
                child_pid = child.pid
                until = time.monotonic() + 5
                while (not proof.exists() or not proof.stat().st_size) and time.monotonic() < until:
                    time.sleep(0.02)
                facts = json.loads(proof.read_text())
                self.assertEqual(facts["pid"], child_pid)
                self.assertNotEqual(facts["pgid"], parent.pid)
                self.assertEqual(facts["pgid"], child_pid)
                self.assertTrue(facts["null"])
                self.assertFalse(procs.alive(parent.pid))
                self.assertFalse(any(row.pgid == parent.pid for row in (procs.table() or {}).values()))
                self.assertTrue(procs.alive(child_pid))
                self.assertEqual(procs.stop_pid(child.pid, child.start, grace=0.2), ())
                self.assertFalse(procs.alive(child_pid))
            finally:
                if child is None and recorded.exists():
                    record = json.loads(recorded.read_text())
                    if record["start"]:
                        child = procs.PidHandle(record["pid"], record["start"])
                if child is not None:
                    procs.stop_pid(child.pid, child.start, grace=0.2)
                procs.stop_pid(parent.pid, grace=0.2)
