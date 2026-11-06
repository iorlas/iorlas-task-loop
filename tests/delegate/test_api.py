"""delegate.api: run, status and cancel as a library call; a delegate fault is a failed typed result."""

import os
import threading
import time

import pytest
from delegate import api
from delegate.app import env
from delegate.contracts import history as hist
from delegate.contracts.wire import RunResult
from support.procsim import real_proc

from run_support import RunBase

LIMIT_S = 60  # each test runs a fake CLI and git


class ApiCalls(RunBase):
    def request(self, brief="do the thing\nthe brief", **kw):
        path = self.base / "brief.md"
        path.write_text(brief, encoding="utf-8")
        return api.RunRequest(role="worker", brief_file=str(path), cwd=self.repo, timeout_s=kw.pop("timeout_s", 30), **kw)

    @real_proc("delegate: a worker, git or CLI process")
    def test_run_returns_a_typed_result_and_a_handle(self):
        os.environ["FAKE_MODE"] = "ok"
        handles: list[api.Handle] = []
        res = api.run(self.request(), started=handles.append)
        assert isinstance(res, RunResult)
        assert res.stop is None
        assert res.text.startswith("done:")
        assert len(handles) == 1
        assert handles[0].pid == handles[0].pgid

    @real_proc("delegate: a git process")
    def test_a_fault_is_a_failed_result_not_an_exception(self):
        res = api.run(api.RunRequest(role="worker", brief_file=str(self.base / "missing.md"), cwd=self.repo))
        assert res.stop is not None
        assert res.stop.reason == "crash"
        assert "missing.md" in res.say

    @real_proc("delegate: a worker, git or CLI process")
    def test_cancel_stops_the_worker_of_a_call_running_on_another_thread(self):
        os.environ["FAKE_MODE"] = "hang"
        got: list[api.Handle] = []
        done: list[RunResult] = []
        t = threading.Thread(target=lambda: done.append(api.run(self.request(timeout_s=60), started=got.append)))
        t.start()
        end = time.time() + 20
        while not got and time.time() < end:
            time.sleep(0.05)
        assert got
        stopped = api.cancel(got[0])
        t.join(20)
        assert stopped.stopped
        assert done
        assert done[0].stop is not None


def test_a_request_carries_tool_servers_it_does_not_yet_wire():
    tool = api.ToolServer(name="artifacts", command=["srv"], bead="tl-1", run="r1", stage="build", attempt=2)
    req = api.RunRequest(role="worker", brief_file="b.md", cwd=".", tools=[tool])
    assert req.tools == [tool]
    assert "srv" not in req.to_argv("route.py")


def test_accounts_lists_every_lane_and_set_account_records_the_owners_choice():
    rows = api.accounts()
    assert rows
    lane = rows[0].lane
    api.set_account(lane, False)
    assert next(a for a in api.accounts() if a.lane == lane).enabled is False
    api.set_account(lane, True)
    assert next(a for a in api.accounts() if a.lane == lane).enabled is True


def test_an_unknown_account_is_refused():
    with pytest.raises(ValueError, match="unknown lane"):
        api.set_account("NO_SUCH_LANE", True)


def test_history_lists_the_finished_runs_after_a_time_as_wire_objects():
    env.history_add(hist.RunRow(ts=100.0, run_id="a", role="planner", lane="L", model="m", effort="e", done=True, task="tl-1"))
    env.history_add(hist.CanaryRow(ts=101.0, run_id="c", lane="L", model="m"))
    env.history_add(hist.RunRow(ts=200.0, run_id="b", role="worker", lane="L", model="m", effort="e", done=True))
    assert [(r["run_id"], r["role"], r["task"]) for r in api.history()] == [("a", "planner", "tl-1"), ("b", "worker", "")]
    assert [r["run_id"] for r in api.history(150.0)] == ["b"]
