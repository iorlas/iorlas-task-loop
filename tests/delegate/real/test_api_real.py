"""delegate.api: run, status and cancel as a library call; a delegate fault is a failed typed result."""

import os
import threading
import time

from delegate import api
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








