"""Owner holds: record, back_at, stale asks."""

import copy
import io
import json
import sys
import time
from pathlib import Path
from unittest import mock

import hermetic  # noqa: F401  (a home of its own for every test)
import routing_support as support
from support.procsim import real_proc
from test_route import CFG, T, lanes, route

from delegate.app import env
from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory


class Holds(Case):
    """delegate-dns: an owner hold {lane, roles, set_by, set_at, until (mandatory), reason}."""

    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(env, "config_dir", return_value=Path(self.tmp.name))
        p.start()
        self.addCleanup(p.stop)

    def main(self, *argv):
        real, sys.stdout = sys.stdout, io.StringIO()
        try:
            code = route.main(list(argv))
            return code, json.loads(sys.stdout.getvalue())
        finally:
            sys.stdout = real



    @real_proc("delegate: a worker, git or CLI process")
    def test_a_hold_stops_its_roles_until_it_ends_and_the_trace_says_who(self):
        h = support.add_hold("OPENAI_SUBSCRIPTION", "+2h", "weekly budget", ["worker", "light"], t=T)
        assert (h.set_by, h.until, h.roles) == ("owner", T + 7200, ["light", "worker"])
        st = env.load_state()
        d = support.decide(
            "worker", copy.deepcopy(CFG), lanes(), st, T, {"authored_by": None, "failed": [], "premium": None, "allow_degraded": False}
        )
        assert d["lane"] != "OPENAI_SUBSCRIPTION"
        assert any(x.startswith("OPENAI_SUBSCRIPTION: rejected, held: owner until") and "weekly budget" in x for x in d["trace"]), d[
            "trace"
        ]
        p = support.decide(
            "planner", copy.deepcopy(CFG), lanes(), st, T, {"authored_by": None, "failed": [], "premium": None, "allow_degraded": False}
        )
        assert p["lane"] == "OPENAI_SUBSCRIPTION"  # the hold names roles
        later = support.decide(
            "worker",
            copy.deepcopy(CFG),
            lanes(),
            st,
            T + 7201,
            {"authored_by": None, "failed": [], "premium": None, "allow_degraded": False},
        )
        assert later["lane"] == "OPENAI_SUBSCRIPTION"  # and ends by itself



    @real_proc("delegate: a worker, git or CLI process")
    def test_release_and_status_show_the_holder_and_expiry(self):
        h = support.add_hold("OPENAI_SUBSCRIPTION", "+2d", "budget", ["worker"], "alice")
        with support.fleet_patches(lanes()):
            _, st = self.main("status", "--json")
        row = st["holds"][0]
        assert (row["id"], row["set_by"], row["roles"], row["reason"]) == (h.id, "alice", ["worker"], "budget")
        assert row["until"] > time.time()
        assert self.main("release", h.id)[0] == 0
        assert self.main("holds")[1]["holds"] == []
        assert self.main("release", "nothing")[0] == 1
