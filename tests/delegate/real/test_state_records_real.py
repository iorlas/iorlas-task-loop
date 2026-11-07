"""Breaker, reset times, token budget, config location"""

import datetime as dt
import os
import time
from pathlib import Path
from unittest import mock

import hermetic  # noqa: F401  (a home of its own for every test)
from any_agent import reset_parse
from any_agent.classify import Outcome
from support.case import Case
from support.procsim import real_proc
from support.tmpdir import TemporaryDirectory
from test_route import argparse_ns, need, route

from delegate.app import env, launch


class ResetTimes(Case):
    """delegate-eau: vendor reset times are parsed in the zone they were stated in; an unstated end is the refusal time + 15/30/60 min."""

    def setup_method(self):
        self.tz = os.environ.get("TZ")
        if hasattr(time, "tzset"):
            os.environ["TZ"] = "Europe/Berlin"
            time.tzset()
        self.addCleanup(self.restore)

    def restore(self):
        if self.tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = self.tz
        if hasattr(time, "tzset"):
            time.tzset()

    def at(self, text, t=None):
        t = t or dt.datetime(2026, 10, 25, 0, 0, tzinfo=dt.UTC).timestamp()
        return reset_parse.parse_reset(text, t), t

    def found(self, text, t=None):
        """-> ((epoch, zone or ""), t) for a text that does state a reset."""
        (at, zone), t = self.at(text, t)
        return (need(at), zone or ""), t







    @real_proc("delegate: a worker, git or CLI process")
    def test_out_rows_record_source_and_zone_and_report_is_manual(self):
        with TemporaryDirectory() as d, mock.patch.object(env, "config_dir", return_value=Path(d)):
            end = (dt.datetime.now(dt.UTC) + dt.timedelta(days=5)).replace(
                second=0, microsecond=0
            )  # inside the 40 days a stated reset may be off
            launch.settler().apply(
                {},
                Outcome("rate_limited", f"will reset at {end:%Y-%m-%d %H:%M:%S} UTC", "event"),
                {"lane": "L1", "limit_reset": None},
                time.time(),
                "codex",
                argparse_ns("worker", timeout=0),
            )
            rec = env.load_state().out["L1"]
            assert (rec.source, rec.zone) == ("vendor", "UTC")
            assert rec.until == end.timestamp()
            for want_n in (0, 1, 2):  # three guesses in a row climb the ladder
                launch.settler().apply(
                    {},
                    Outcome("rate_limited", "slow down", "event"),
                    {"lane": "L2"},
                    1_800_000_000.0,
                    "codex",
                    argparse_ns("worker", timeout=0),
                )
                rec = env.load_state().out["L2"]
                assert (rec.source, rec.guess_n, round((rec.until - 1_800_000_000.0) / 60)) == ("guess", want_n, (15, 30, 60)[want_n])
            route.main(["report", "--lane", "OPENAI_SUBSCRIPTION", "--event", "out", "--until", str(int(time.time()) + 600)])
            assert env.load_state().out["OPENAI_SUBSCRIPTION"].source == "manual"
