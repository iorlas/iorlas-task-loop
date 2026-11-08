"""Account state shared by two processes (leases, resume refs, the history ledger): every write of both survives, none is lost to a race."""

import os
import subprocess
import sys
import time
from pathlib import Path

from run_support import RunBase
from test_route import ROOT

from delegate.app import env
from tltestkit.procsim import real_proc

LIMIT_S = 60  # two interpreters, each makes 20 locked state writes
N = 20

CHILD = f"""
import sys, time
from pathlib import Path
from delegate.app import env
from delegate.app.lease import RunLease
from delegate.contracts import history as hist
from delegate.contracts.state import RefRecord, StateDoc

who, done = sys.argv[1], Path(sys.argv[2])
for i in range({N}):
    rid = f"{{who}}-{{i}}"
    assert RunLease(rid, "worker", f"task-{{rid}}", "L", "m", None, False, 60).claim() is None
    def keep(s: StateDoc, rid=rid) -> None:
        s.refs[rid] = RefRecord(account="L", model="m", effort="e", mode="x")
    env.update_state(keep)
    env.history_add(hist.CanaryRow(ts=env.now(), run_id=rid, account="L", model="m"))
(done / who).write_text("1")
while len(list(done.iterdir())) < 2:  # stay alive: a lease of a dead pid is reaped by the next claim
    time.sleep(0.05)
"""


class TwoProcessState(RunBase):
    @real_proc("delegate: two interpreters share one state dir")
    def test_both_processes_writes_all_survive(self):
        done = self.base / "done"
        done.mkdir()
        child_env = dict(
            os.environ,
            PYTHONPATH=os.pathsep.join(
                [
                    str(ROOT / "packages" / "delegate" / "src"),
                    str(ROOT / "skills" / "task-loop" / "_vendor"),
                ]
            ),
        )
        procs = [subprocess.Popen([sys.executable, "-c", CHILD, who, str(done)], env=child_env) for who in ("a", "b")]
        end = time.time() + 50
        for p in procs:
            p.wait(max(1.0, end - time.time()))
        assert [p.returncode for p in procs] == [0, 0]
        st = env.load_state()
        want = {f"{w}-{i}" for w in "ab" for i in range(N)}
        assert set(st.leases) == want
        assert set(st.refs) == want
        ledger = Path(env.history_path()).read_text(encoding="utf-8")
        assert all(f'"{rid}"' in ledger for rid in want)
