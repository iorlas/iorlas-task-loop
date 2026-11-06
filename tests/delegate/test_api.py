"""delegate.api: run, status and cancel as a library call; a delegate fault is a failed typed result."""


import os

import pytest
from delegate import api
from delegate.app import env
from delegate.contracts import history as hist
from delegate.contracts.state import Lease
from stream_proc import proc_start

LIMIT_S = 60  # each test runs a fake CLI and git




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


def test_agents_lists_the_runs_whose_process_still_lives():
    me = os.getpid()
    live = Lease(lane="L", pid=me, pid_start=proc_start(me), start=1.0, expires=2.0, task="tl-1", role="worker")
    dead = Lease(lane="L", pid=2**22 + 1, pid_start="gone", start=1.0, expires=2.0, task="tl-2", role="worker")
    env.update_state(lambda st: st.leases.update({"r1": live, "r2": dead}))
    assert [(a.run_id, a.task, a.role) for a in api.agents()] == [("r1", "tl-1", "worker")]
