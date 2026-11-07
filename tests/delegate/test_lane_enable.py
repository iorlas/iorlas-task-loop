"""One enable mechanism: `profile.lanes.<LANE>` in config.json ("enabled" | "declined"). An opt-in lane (routing.json `opt_in`) is off
until the profile enables it; the old `<lane>_enabled` settings keys fail loudly; doctor is the post-update smoke check."""

import io
import json
import shutil
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from unittest import mock

import hermetic  # noqa: F401  (a home of its own for every test)
import pytest
from any_agent.harnesses.opencode import OpenCodeHarness
from support.case import Case
from support.tmpdir import TemporaryDirectory
from test_route import route

from delegate.app import cockpit, doctor, env, onboard, usage
from delegate.app import decide as dec
from delegate.contracts.routing import CallArgs
from delegate.contracts.state import StateDoc
from delegate.domain.holds.book import HoldBook
from delegate.domain.routing.router import Router

T = 1_000_000_000.0
LANE = "DEEPSEEK_FREE"


class LaneEnable(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        patches = [
            mock.patch.dict("os.environ", {"DELEGATE_CONFIG_DIR": self.tmp.name}),
            mock.patch.object(OpenCodeHarness, "find_exe", return_value="opencode"),
            mock.patch.object(OpenCodeHarness, "supported", return_value=True),
            mock.patch.object(onboard.sys, "platform", "darwin"),
            mock.patch.object(shutil, "which", lambda n: None),
            mock.patch.dict(usage.READERS, {k: (lambda *a: None) for k in usage.READERS}),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)
        self.cfg = env.load_routing()

    def fleet(self):
        return dec.fleet_builder(self.cfg).build(StateDoc(), T)

    def row(self):
        ck: Any = cockpit.cockpit(self.cfg, self.fleet().lanes, StateDoc(), T)
        return next(r for r in ck["lanes"] if r["id"] == LANE)

    def pick(self):
        lanes = self.fleet().lanes
        d = Router(env.typed_routing(self.cfg), HoldBook({}), {}, T).decide("light", CallArgs(), lanes)
        return d, lanes

    def test_disabled_lane_shows_disabled_and_is_never_picked(self):
        assert LANE not in self.fleet().lanes
        v: Any = self.row()
        assert (v["state"], v["reason"]) == ("off", f"disabled: `route.py config set profile.lanes.{LANE} enabled` turns it on")
        d, _ = self.pick()
        assert d.as_dict().get("lane") != LANE

    def test_enabling_it_in_the_profile_makes_it_pickable_behind_the_breaker(self):
        doctor.config_set(f"profile.lanes.{LANE}", "enabled")
        d, lanes = self.pick()
        assert LANE in lanes
        assert d.as_dict()["lane"] == LANE
        assert lanes[LANE].hview  # the (lane, model) breaker is applied to it like to any lane
        doctor.config_set(f"profile.lanes.{LANE}", "declined")
        assert LANE not in self.fleet().lanes

    def test_the_old_enable_key_fails_loudly_with_the_exact_fix(self):
        old = "deepseek_free_enabled"
        Path(self.tmp.name, "config.json").write_text(json.dumps({old: True}), encoding="utf-8")
        with pytest.raises(SystemExit) as cm:
            env.load_routing()
        msg = str(cm.value)
        for want in (old, "config.json", "delete", f"route.py config set profile.lanes.{LANE} enabled"):
            assert want in msg

    def test_config_set_rejects_a_bad_profile_value(self):
        for key, val in ((f"profile.lanes.{LANE}", "true"), ("profile.lanes", "enabled")):
            with pytest.raises(SystemExit):
                doctor.config_set(key, val)

    def doctor_run(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = route.main(["doctor", *args])
        return code, buf.getvalue()

    def test_doctor_smoke_check_passes_on_a_clean_profile(self):
        doctor.config_set(f"profile.lanes.{LANE}", "enabled")
        code, _ = self.doctor_run()
        assert code == 0

    def test_doctor_smoke_check_fails_for_an_enabled_lane_whose_cli_is_gone(self):
        doctor.config_set(f"profile.lanes.{LANE}", "enabled")
        with mock.patch.object(OpenCodeHarness, "find_exe", return_value=None):
            code, out = self.doctor_run("--json")
        assert code == 1
        notes = [n for n in json.loads(out)["notes"] if n["id"] == "enabled_not_ready"]
        assert [n["lane"] for n in notes] == [LANE]

    def test_doctor_smoke_check_fails_for_a_profile_that_does_not_parse_or_names_nothing_known(self):
        for profile in ({"lanes": {"NOPE": "enabled"}}, {"lanes": {LANE: "yes"}}, {"lanes": "enabled"}):
            Path(self.tmp.name, "config.json").write_text(json.dumps({"profile": profile}), encoding="utf-8")
            code, out = self.doctor_run("--json")
            assert code == 1, profile
            assert any(n["id"] == "bad_profile" for n in json.loads(out)["notes"]), profile
