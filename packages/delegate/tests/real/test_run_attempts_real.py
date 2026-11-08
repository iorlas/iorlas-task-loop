"""`attempts` in the answer: the launches one call made, in order (tl-7i9k.45); absent when the call made one."""

from unittest import mock

import routing_support as support
from run_support import RunBase
from test_route import lanes

from delegate.app import launch, net
from tltestkit.procsim import real_proc

GOOD = {"data": {"a": 1}, "text": '{"a":1}', "outcome": None}
BAD = {"data": None, "text": "prose", "outcome": None}


class RunAttempts(RunBase):
    def schema(self):
        path = self.base / "schema.json"
        path.write_text('{"type":"object","required":["a"]}')
        return str(path)

    def worker(self, *legs):
        """launch_worker answers each call with the next leg; a lane is its ref so a re-ask can resume."""
        legs = list(legs)

        def one(d, *args):
            leg = dict(legs.pop(0))
            return {"ref": d["lane"], "tokens": {"in": 10, "cached": 2, "out": 3}, "cost": 0.25, **leg}

        return mock.patch.object(launch, "launch_worker", side_effect=one)

    def kinds(self, result):
        return [(a["kind"], a["outcome"]) for a in result.get("attempts", [])]

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_plain_run_reports_no_attempts(self):
        with support.fleet_patches(lanes()), self.worker(GOOD):
            _, result = self.run_it("--schema", self.schema())
        assert "attempts" not in result

    @real_proc("delegate: a worker, git or CLI process")
    def test_the_schema_reask_is_a_second_attempt(self):
        with support.fleet_patches(lanes()), self.worker(BAD, GOOD):
            _, result = self.run_it("--schema", self.schema())
        assert self.kinds(result) == [("first", "schema_invalid"), ("schema_reask", None)]
        first = result["attempts"][0]
        assert (first["lane"], first["tokens"]) == (result["lane"], {"in": 10, "cached": 2, "out": 3})
        assert isinstance(first["secs"], float)

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_network_drop_before_the_session_is_rerun_as_the_second_attempt(self):
        drop = {"outcome": "network", "started": False, "data": None, "text": ""}
        with support.fleet_patches(lanes()), self.worker(drop, GOOD), mock.patch.object(net, "net_up", return_value=True):
            _, result = self.run_it()
        assert self.kinds(result) == [("first", "network"), ("network_rerun", None)]

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_reroute_after_the_failed_reask_lists_every_launch(self):
        with support.fleet_patches(lanes()), self.worker(BAD, BAD, GOOD):
            _, result = self.run_it("--schema", self.schema())
        assert self.kinds(result) == [("first", "schema_invalid"), ("schema_reask", "schema_invalid"), ("reroute", None)]
        assert result["attempts"][2]["lane"] == result["lane"] != result["attempts"][0]["lane"]
