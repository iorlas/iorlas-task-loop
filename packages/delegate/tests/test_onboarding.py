"""Onboarding, onboarding wizard and its child environment."""

import io
import os
import shutil
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any
from unittest import mock

import hermetic  # noqa: F401  (a home of its own for every test)
from test_route import T, argparse_ns, route

from delegate.app import cockpit, doctor, env, fleet, usage
from delegate.app import decide as dec
from delegate.contracts.state import StateDoc
from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory


def doctor_accounts(cfg: Any) -> list[Any]:
    accounts: Any = doctor.doctor(cfg)["accounts"]
    return accounts


class Onboarding(Case):
    """Run against an empty fake home so nothing depends on the machine's real setup."""

    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.saved = {
            k: os.environ.get(k) for k in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "APPDATA", "DELEGATE_CONFIG_DIR", "CODEX_HOME")
        }
        for k in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "APPDATA", "DELEGATE_CONFIG_DIR"):
            os.environ[k] = self.tmp.name
        os.environ.pop("CODEX_HOME", None)
        self.no_which()
        self.cfg: Any = env.load_routing()

    def no_which(self, found=None):
        """Nothing is installed, bar `found`."""
        p = mock.patch.object(shutil, "which", side_effect=lambda name: found if name == "codex" else None)
        p.start()
        self.addCleanup(p.stop)

    def teardown_method(self):
        for k, v in self.saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def test_doctor_is_a_plain_account_table_and_nothing_blocks(self):
        rows: Any = {r["account"]: r for r in doctor_accounts(self.cfg)}
        assert list(rows) == list(self.cfg["accounts"])
        assert (rows["CLAUDE_SUBSCRIPTION"]["enabled"], rows["CLAUDE_SUBSCRIPTION"]["ready"], rows["CLAUDE_SUBSCRIPTION"]["fix"]) == (
            True,
            True,
            "",
        )
        o = rows["OPENAI_SUBSCRIPTION"]
        assert (o["enabled"], o["ready"]) == (True, False)
        assert "npm install -g @openai/codex" in o["fix"]
        assert not rows["DEEPSEEK_FREE"]["enabled"]  # an opt-in account is off until the profile enables it
        assert "profile.accounts.DEEPSEEK_FREE" in rows["DEEPSEEK_FREE"]["fix"]
        self._make_codex_ready()
        o = {r["account"]: r for r in doctor_accounts(self.cfg)}["OPENAI_SUBSCRIPTION"]
        assert (o["ready"], o["fix"]) == (True, "")
        env.set_profile_account("OPENAI_SUBSCRIPTION", "declined")
        assert not {r["account"]: r for r in doctor_accounts(self.cfg)}["OPENAI_SUBSCRIPTION"]["enabled"]

    def test_the_table_prints_one_line_per_account(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            assert route.main(["doctor"]) == 0
            assert route.main(["init"]) == 0
        lines = buf.getvalue().splitlines()
        assert len(lines) == (2 * (len(self.cfg["accounts"]) + 1))
        assert lines[0].startswith("account") and "enabled" in lines[0] and "ready" in lines[0] and "fix" in lines[0]

    def _gather(self, st=None):
        return self._fleet().accounts

    def _fleet(self):
        real = dict(usage.READERS)
        none_reader: Any = lambda account, S, st_, t, *a: None  # noqa: E731  a reader that reports nothing
        usage.READERS.update(dict.fromkeys(real, none_reader))
        try:
            return dec.fleet_builder(self.cfg).build(env.load_state(), T)
        finally:
            usage.READERS.update(real)

    def _make_codex_ready(self):
        self.no_which("/x/codex")
        home = Path(os.environ["HOME"]) / ".codex"
        home.mkdir(parents=True, exist_ok=True)
        (home / "auth.json").write_text("{}")

    def test_fresh_machine_is_sub_agent_only_with_no_nag(self):
        ls = self._gather()
        assert list(ls) == ["CLAUDE_SUBSCRIPTION"]
        assert env.profile_accounts() == {}
        assert fleet.drift_warnings(env.states(), ls, env.load_state(), T) == []

    def test_ready_account_is_enabled_once_and_remembered(self):
        self._make_codex_ready()
        assert "OPENAI_SUBSCRIPTION" in self._gather()
        assert "OPENAI_SUBSCRIPTION" not in env.profile_accounts()  # a read writes nothing; `run` applies Fleet.enables
        assert self._fleet().enables == ["OPENAI_SUBSCRIPTION"]
        env.set_profile_account("OPENAI_SUBSCRIPTION", "enabled")  # what `run` does with Fleet.enables
        assert env.profile_accounts()["OPENAI_SUBSCRIPTION"] == "enabled"

    def test_declined_account_stays_out_even_when_ready(self):
        self._make_codex_ready()
        env.set_profile_account("OPENAI_SUBSCRIPTION", "declined")
        assert "OPENAI_SUBSCRIPTION" not in self._gather()

    def test_enabled_but_no_longer_ready_is_out_and_warns_once_a_day(self):
        env.set_profile_account("OPENAI_SUBSCRIPTION", "enabled")  # nothing on this fake machine
        ls = self._gather()
        assert ls["OPENAI_SUBSCRIPTION"].out
        assert len(fleet.drift_warnings(env.states(), ls, env.load_state(), T)) == 1
        assert fleet.drift_warnings(env.states(), ls, env.load_state(), T + 60) == []

    def test_usage_is_requested_only_on_desktop(self):
        ls = self._gather()
        saved = os.environ.get("CLAUDE_CODE_ENTRYPOINT")
        try:
            os.environ["CLAUDE_CODE_ENTRYPOINT"] = "claude-desktop"
            assert [n["what"] for n in cockpit.needs_input(ls)] == ["claude_usage"]
            os.environ["CLAUDE_CODE_ENTRYPOINT"] = "cli"
            assert cockpit.needs_input(ls) == []
            os.environ.pop("CLAUDE_CODE_ENTRYPOINT")
            assert cockpit.needs_input(ls) == []
        finally:
            if saved is not None:
                os.environ["CLAUDE_CODE_ENTRYPOINT"] = saved

    def test_unset_accounts_are_offered_once_and_never_block(self):
        a = argparse_ns("worker")
        saved = os.environ.get("CLAUDE_CODE_ENTRYPOINT")
        os.environ["CLAUDE_CODE_ENTRYPOINT"] = "cli"  # a Claude session: the Agent tool is available
        try:
            d1 = dec.decision(a, self.cfg, apply=True)[0]
            assert d1["action"] == "run"
            assert "OPENAI_SUBSCRIPTION" in d1["notice"]
            assert "notice" not in dec.decision(a, self.cfg, apply=True)[0]  # said once
        finally:
            os.environ.pop("CLAUDE_CODE_ENTRYPOINT", None) if saved is None else os.environ.__setitem__("CLAUDE_CODE_ENTRYPOINT", saved)

    def test_next_and_status_write_no_config(self):
        a = argparse_ns("worker")
        path = Path(env.config_store().path)
        before = path.read_bytes() if path.exists() else None
        dec.decision(a, self.cfg)
        dec.fleet_builder(self.cfg).build(StateDoc(), 1e9)
        assert (path.read_bytes() if path.exists() else None) == before

    def test_config_set_and_show(self):
        doctor.config_set("burn.minutes", "60")
        doctor.config_set("claude_weekly_reset", "Sun 17:00")
        cfg: Any = env.load_routing()
        assert cfg["settings"]["burn"]["minutes"] == 60
        assert cfg["settings"]["claude_weekly_reset"] == "Sun 17:00"
        assert cfg["settings"]["burn"]["min_left_percent"] == 10  # untouched defaults survive the merge
