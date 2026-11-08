"""One enable mechanism: `profile.accounts.<ACCOUNT>` in config.json ("enabled" | "declined"). An opt-in account (routing.json `opt_in`)
is off
until the profile enables it; the old `<account>_enabled` settings keys fail loudly; doctor is the post-update smoke check."""

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
from test_route import route

from delegate.app import cockpit, doctor, env, onboard, usage
from delegate.app import decide as dec
from delegate.contracts.routing import CallArgs
from delegate.contracts.state import StateDoc
from delegate.domain.holds.book import HoldBook
from delegate.domain.routing.router import Router
from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

T = 1_000_000_000.0
ACCOUNT = "DEEPSEEK_FREE"


class AccountEnable(Case):
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
        ck: Any = cockpit.cockpit(self.cfg, self.fleet().accounts, StateDoc(), T)
        return next(r for r in ck["accounts"] if r["id"] == ACCOUNT)

    def pick(self):
        accounts = self.fleet().accounts
        d = Router(env.typed_routing(self.cfg), HoldBook({}), {}, T).decide("light", CallArgs(), accounts)
        return d, accounts

    def test_disabled_account_shows_disabled_and_is_never_picked(self):
        assert ACCOUNT not in self.fleet().accounts
        v: Any = self.row()
        assert (v["state"], v["reason"]) == ("off", f"disabled: `route.py config set profile.accounts.{ACCOUNT} enabled` turns it on")
        d, _ = self.pick()
        assert d.as_dict().get("account") != ACCOUNT

    def test_enabling_it_in_the_profile_makes_it_pickable_behind_the_breaker(self):
        doctor.config_set(f"profile.accounts.{ACCOUNT}", "enabled")
        d, accounts = self.pick()
        assert ACCOUNT in accounts
        assert d.as_dict()["account"] == ACCOUNT
        assert accounts[ACCOUNT].hview  # the (account, model) breaker is applied to it like to any account
        doctor.config_set(f"profile.accounts.{ACCOUNT}", "declined")
        assert ACCOUNT not in self.fleet().accounts

    def test_the_old_enable_key_fails_loudly_with_the_exact_fix(self):
        old = "deepseek_free_enabled"
        Path(self.tmp.name, "config.json").write_text(json.dumps({old: True}), encoding="utf-8")
        with pytest.raises(SystemExit) as cm:
            env.load_routing()
        msg = str(cm.value)
        for want in (old, "config.json", "delete", f"route.py config set profile.accounts.{ACCOUNT} enabled"):
            assert want in msg

    def test_config_set_rejects_a_bad_profile_value(self):
        for key, val in ((f"profile.accounts.{ACCOUNT}", "true"), ("profile.accounts", "enabled")):
            with pytest.raises(SystemExit):
                doctor.config_set(key, val)

    def doctor_run(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = route.main(["doctor", *args])
        return code, buf.getvalue()

    def test_doctor_smoke_check_passes_on_a_clean_profile(self):
        doctor.config_set(f"profile.accounts.{ACCOUNT}", "enabled")
        code, _ = self.doctor_run()
        assert code == 0

    def test_doctor_smoke_check_fails_for_an_enabled_account_whose_cli_is_gone(self):
        doctor.config_set(f"profile.accounts.{ACCOUNT}", "enabled")
        with mock.patch.object(OpenCodeHarness, "find_exe", return_value=None):
            code, out = self.doctor_run("--json")
        assert code == 1
        notes = [n for n in json.loads(out)["notes"] if n["id"] == "enabled_not_ready"]
        assert [n["account"] for n in notes] == [ACCOUNT]

    def test_doctor_smoke_check_fails_for_a_profile_that_does_not_parse_or_names_nothing_known(self):
        for profile in ({"accounts": {"NOPE": "enabled"}}, {"accounts": {ACCOUNT: "yes"}}, {"accounts": "enabled"}):
            Path(self.tmp.name, "config.json").write_text(json.dumps({"profile": profile}), encoding="utf-8")
            code, out = self.doctor_run("--json")
            assert code == 1, profile
            assert any(n["id"] == "bad_profile" for n in json.loads(out)["notes"]), profile
