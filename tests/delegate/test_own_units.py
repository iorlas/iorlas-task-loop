"""delegate-own, unit side: the process-lister guard, the typed contract, the answer's `worker` field. No process is started."""

import json

import hermetic  # noqa: F401
from any_agent.procs import StopReport, Survivor
from test_route import ROOT

from delegate.adapters import procs
from delegate.app import env
from delegate.app.lease import RunLease
from delegate.contracts import wire


class OsProc:
    def test_no_module_runs_a_process_lister(self):
        for f in (ROOT / "packages" / "delegate" / "src" / "delegate").rglob("*.py"):
            src = f.read_text(encoding="utf-8")
            for bad in ('["ps"', '"lsof"', '"tasklist"', "pgrep", "pkill"):
                assert bad not in src, f"{f.name} runs a process lister ({bad}): the worker's own record (adapters/procs.py) is the source"


class Contract:
    def test_request_flags_are_flags_of_run(self):
        req = wire.RunRequest(
            role="writer",
            brief_file="b.md",
            cwd="/w",
            schema_file="s.json",
            resume="r1",
            authored_by="x",
            timeout_s=60,
            idle_s=30,
            parent="p",
            task="t",
            title="T",
            call_id="c1",
            live_file="/l.jsonl",
        )
        flags = {a for a in req.to_argv("route.py") if a.startswith("--")}
        assert flags <= set(json.loads((ROOT / "packages/delegate/src/delegate/data/contract.json").read_text())["run_args"])
        assert "--idle" in flags
        assert req.env() == {"DELEGATE_LIVE_FILE": "/l.jsonl"}
        assert "--resume" not in wire.RunRequest(role="w", brief_file="b", cwd="/w").to_argv("route.py")


class WorkerField:
    def test_end_by_outcome(self):
        stop = [StopReport()]
        assert [procs.worker_end(stop, o).end for o in (None, "timeout", "hung", "worker_failed")] == ["ok", "timeout", "error", "error"]
        assert not procs.worker_end([], None).stopped

    def test_a_survivor_beats_every_outcome(self):
        stops = [StopReport(survivors=[Survivor(pid=5, start=None)])]
        assert [procs.worker_end(stops, o).end for o in (None, "timeout")] == ["worker_survived"] * 2

    def test_reason_worker_survived_is_declared_with_facts(self):
        r = json.loads((ROOT / "packages/delegate/src/delegate/data/contract.json").read_text())["reasons"]["worker_survived"]
        assert (r["scope"], r["permanence"], r["retry"]) == ("machine", "needs_owner", "none")


class LeaseEnd:
    def claimed(self):
        lease = RunLease("r1", "worker", "tl-1", "OPENAI_SUBSCRIPTION", "m", None, False, 60.0)
        assert lease.claim() is None
        return lease

    def test_a_lease_goes_when_the_worker_tree_is_dead(self):
        self.claimed().finish([StopReport()])
        assert "r1" not in env.load_state().leases

    def test_a_lease_stays_while_a_worker_survived_its_stops(self):
        self.claimed().finish([StopReport(survivors=[Survivor(pid=5, start=None)])])
        assert "r1" in env.load_state().leases
