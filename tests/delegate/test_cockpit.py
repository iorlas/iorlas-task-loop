"""The lane cockpit: one row per known lane, an emoji for each state, a plain reason, the unlock time, usage windows with their source."""

import copy
import io
import json
import os
import stat
import sys
from pathlib import Path
from unittest.mock import patch

from any_agent.harnesses.opencode import OpenCodeHarness
from delegate.app import cockpit, env, harnesses, onboard, usage
from delegate.domain.lanes.lane import Lane
from delegate.domain.time import spec
from support.tmpdir import TemporaryDirectory

import routing_support as support
from test_route import CFG, T, route

HOUR = 3600


def cfg_all():
    cfg = copy.deepcopy(CFG)
    return cfg


def lane(name, **over):
    c = CFG["lanes"][name]
    ln = Lane(name, c["family"], c["kind"], c.get("shared_with_orchestrator", False))
    for k, v in over.items():
        setattr(ln, k, v)
    return ln


def view(name, ln, st=None, history=(), login=(True, "ok", T), cfg=None, off=None):
    return cockpit.lane_view(name, cfg or cfg_all(), ln, support.doc_of(st or {}), T, history, 0, login, off)


class Emoji:
    def test_ready_with_a_live_window(self):
        ln = lane("OPENAI_SUBSCRIPTION", week=3.0, week_reset=T + 6 * 86400)
        usage.add_window(ln, 3.0, T + 6 * 86400, 10080, "live read (codex app-server)", T - 120)
        v = view("OPENAI_SUBSCRIPTION", ln)
        assert (v["state"], v["emoji"], v["reason"]) == ("ready", "✅", "ready")
        w = v["windows"][0]
        assert (w["name"], w["used_pct"], w["source"], w["age_s"], w["resets_in_s"]) == (
            "weekly",
            3.0,
            "live read (codex app-server)",
            120,
            6 * 86400,
        )
        assert not v["unlock"]["locked"]

    def test_resting_on_a_limit_names_the_unlock_in_local_time_and_duration(self):
        ln = lane("OPENAI_SUBSCRIPTION", out=True, out_until=T + 2 * HOUR + 10 * 60, out_reason="limit", week=99.0)
        v = view("OPENAI_SUBSCRIPTION", ln, {"out": {"OPENAI_SUBSCRIPTION": {"until": ln.out_until, "why": "weekly limit", "at": T}}})
        assert (v["state"], v["emoji"], v["reason"]) == ("resting", "⏳", "weekly limit hit")
        assert v["unlock"]["known"]
        assert v["unlock"]["in_s"] == (2 * HOUR + 600)
        assert ln.out_until is not None
        assert v["unlock"]["text"] == f"{spec.local(ln.out_until)} (in 2h 10m)"

    def test_an_old_state_entry_without_a_typed_reason_is_still_resting_until_its_time(self):
        rec = {
            "until": T + 5 * HOUR,
            "why": "free usage limit still reached at 18:45; opencode hangs 47 min instead of exiting",
            "at": T - HOUR,
        }
        ln = lane("DEEPSEEK_FREE", out=True, out_until=rec["until"], out_reason="error", notes=[rec["why"]])
        v = view("DEEPSEEK_FREE", ln, {"out": {"DEEPSEEK_FREE": rec}})
        assert (v["state"], v["reason"]) == ("resting", "free usage limit reached")
        assert v["unlock"]["at"] == rec["until"]

    def test_limit_without_a_reset_time_says_unknown_and_why(self):
        ln = lane("OPENAI_SUBSCRIPTION", out=True, out_until=None, out_reason="limit")
        v = view("OPENAI_SUBSCRIPTION", ln)
        assert v["state"] == "resting"
        assert (v["unlock"]["locked"], v["unlock"]["known"], v["unlock"]["why"]) == (True, False, "the vendor gave no reset time")

    def test_logged_out_by_the_real_check_even_with_no_limit_recorded(self):
        v = view("OPENAI_SUBSCRIPTION", lane("OPENAI_SUBSCRIPTION", week=1.0), login=(False, "Not logged in", T))
        assert (v["state"], v["emoji"], v["reason"]) == ("logged_out", "🔑", "logged out: run `codex login`")
        assert not v["unlock"]["known"]
        assert "log in" in v["unlock"]["why"]

    def test_logged_out_from_a_drifted_lane(self):
        ln = lane("GROK_SUBSCRIPTION", out=True, out_reason="logged_out", notes=["enabled but not ready (login or key gone?)"])
        v = view("GROK_SUBSCRIPTION", ln, login=(None, "", None))
        assert (v["state"], v["emoji"]) == ("logged_out", "🔑")

    def test_spending_limit_old_entry_without_a_reason(self):
        rec = {
            "until": T + 3 * HOUR,
            "why": "spending-limit: out of credits (personal-team-blocked); top up then report --event ok",
            "at": T - 60,
        }
        ln = lane("GROK_SUBSCRIPTION", out=True, out_until=rec["until"], out_reason="error", notes=[rec["why"]])
        v = view("GROK_SUBSCRIPTION", ln, {"out": {"GROK_SUBSCRIPTION": {"until": rec["until"], "why": rec["why"], "at": rec["at"]}}})
        assert (v["state"], v["emoji"]) == ("spend", "💸")
        assert v["unlock"]["known"]

    def test_codex_spend_control_is_a_spend_limit_without_a_timer(self):
        ln = lane("OPENAI_SUBSCRIPTION", out=True, out_until=None, out_reason="limit", spend_blocked=True)
        v = view("OPENAI_SUBSCRIPTION", ln)
        assert v["state"] == "spend"
        assert "no timer" in v["unlock"]["why"]

    def test_hung_and_benched_is_slow_with_its_end_time(self):
        ln = lane("GROK_SUBSCRIPTION", out=True, out_until=T + 1800, out_reason="hung")
        v = view(
            "GROK_SUBSCRIPTION",
            ln,
            {"out": {"GROK_SUBSCRIPTION": {"until": T + 1800, "why": "hung: no output within 120s", "at": T, "reason": "hung"}}},
        )
        assert (v["state"], v["emoji"]) == ("slow", "🐢")
        assert v["unlock"]["in_s"] == 1800

    def test_a_recent_hang_with_no_good_run_since_is_slow_but_not_locked(self):
        hist = [
            {"lane": "GROK_SUBSCRIPTION", "done": True, "outcome": None, "ts": T - 5 * HOUR},
            {"lane": "GROK_SUBSCRIPTION", "outcome": "hung", "ts": T - 600},
        ]
        v = view("GROK_SUBSCRIPTION", lane("GROK_SUBSCRIPTION"), history=hist)
        assert (v["state"], v["emoji"], v["unlock"]["locked"]) == ("slow", "🐢", False)
        hist.append({"lane": "GROK_SUBSCRIPTION", "done": True, "outcome": None, "ts": T - 60})
        assert view("GROK_SUBSCRIPTION", lane("GROK_SUBSCRIPTION"), history=hist)["state"] == "ready"

    def test_disabled_and_not_configured(self):
        cfg = copy.deepcopy(CFG)
        for name, text in (("DEEPSEEK_FREE", "disabled: `route.py config set profile.lanes.DEEPSEEK_FREE enabled` turns it on"),):
            v = view(name, None, cfg=cfg, off=cockpit.off_reason(name, cfg, (True, "", T)))
            assert (v["state"], v["emoji"], v["reason"]) == ("off", "⛔", text)
            assert v["model"] == "deepseek-v4.1-flash-free high"  # still shows what it would use
        with patch.object(env, "profile_lanes", return_value={}):
            assert (
                cockpit.off_reason("OPENAI_SUBSCRIPTION", cfg_all(), (None, "", None))
                == "not configured: `route.py doctor` says what it needs"
            )
            assert (
                cockpit.off_reason("OPENAI_SUBSCRIPTION", cfg_all(), (False, "", None)) == "not configured: logged out, run `codex login`"
            )
        with patch.object(env, "profile_lanes", return_value={"GROK_SUBSCRIPTION": "declined"}):
            assert "declined" in cockpit.off_reason("GROK_SUBSCRIPTION", cfg_all(), (True, "", None))

    def test_unknown_when_a_metered_lane_has_no_reading(self):
        v = view("CLAUDE_SUBSCRIPTION", lane("CLAUDE_SUBSCRIPTION", shared=True))
        assert (v["state"], v["emoji"]) == ("unknown", "❓")
        assert (
            view("CLAUDE_SUBSCRIPTION", lane("CLAUDE_SUBSCRIPTION", week=1.0, shared=True), login=(None, "claude CLI not installed", None))[
                "state"
            ]
            == "unknown"
        )

    def test_a_vendor_without_a_meter_is_ready_not_unknown(self):
        v = view("GROK_SUBSCRIPTION", lane("GROK_SUBSCRIPTION"))
        assert v["state"] == "ready"
        assert not v["meter"]

    def test_low_tokens_over_the_gate_but_under_the_ceiling_stays_ready_with_a_warning(self):
        ln = lane("OPENAI_SUBSCRIPTION", week=96.0)
        usage.add_window(ln, 96.0, T + 86400, 10080, "live read", T)
        v = view("OPENAI_SUBSCRIPTION", ln)
        assert v["state"] == "ready"
        assert v["low_tokens"][0]["over"] == "gate"
        assert "low tokens: weekly 96% is over the lane gate 95%" in v["reason"]

    def test_over_the_hard_ceiling_rests_until_that_window_resets(self):
        ln = lane("OPENAI_SUBSCRIPTION", week=99.0, week_reset=T + 3 * HOUR)
        usage.add_window(ln, 99.0, T + 3 * HOUR, 10080, "live read", T)
        v = view("OPENAI_SUBSCRIPTION", ln)
        assert (v["state"], v["low_tokens"][0]["over"]) == ("resting", "ceiling")
        assert v["unlock"]["in_s"] == (3 * HOUR)

    def test_every_state_has_its_own_emoji(self):
        assert len(set(cockpit.EMOJI.values())) == 7
        assert set(cockpit.EMOJI) == {"ready", "resting", "logged_out", "spend", "slow", "off", "unknown"}


class Fmt:
    def test_fmt_in(self):
        assert [spec.fmt_in(s) for s in (20, 45 * 60, 2 * HOUR + 600, 6 * 86400 + 21 * HOUR)] == ["<1m", "45m", "2h 10m", "6d 21h"]


class Readers:
    def test_the_claude_reader_marks_its_source(self):
        with TemporaryDirectory() as d, patch.dict(os.environ, {"DELEGATE_CONFIG_DIR": d}):
            c = lane("CLAUDE_SUBSCRIPTION", shared=True)
            with patch.object(usage, "claude_logged_out", return_value=False), patch.object(env, "update_state"):
                usage.read_claude_subscription(
                    c,
                    env.settings_of(CFG),
                    support.doc_of({}),
                    T,
                    {
                        "plan": {
                            "windows": [
                                {"label": "5 hour", "percentUsed": 12, "resetsAt": T + HOUR},
                                {"label": "All weekly", "percentUsed": 40, "resetsAt": T + 86400},
                            ]
                        }
                    },
                )
            assert [(w["name"], w["used"], w["source"]) for w in c.windows] == [
                ("5-hour", 12.0, "manual mark (get_usage passed in)"),
                ("weekly", 40.0, "manual mark (get_usage passed in)"),
            ]


class LoginCheck:
    def fake(self, d, name, body):
        p = Path(d) / name
        p.write_text("#!/bin/sh\n" + body + "\n")
        p.chmod(p.stat().st_mode | stat.S_IEXEC)


    def test_opencode_logins_are_read_from_its_auth_file(self):
        with (
            TemporaryDirectory() as d,
            patch.dict(os.environ, {"XDG_DATA_HOME": d}),
            patch.object(OpenCodeHarness, "find_exe", return_value="opencode"),
        ):
            (Path(d) / "opencode").mkdir()
            auth = Path(d) / "opencode" / "auth.json"
            auth.write_text(json.dumps({"xai": {"type": "oauth"}}))
            assert harnesses.probe_login("GROK_SUBSCRIPTION")[0]
            assert not harnesses.probe_login("ZAI_CODING_SUBSCRIPTION")[0]
            auth.write_text(json.dumps({"zai-coding-plan": {"type": "api", "key": "k"}}))
            assert harnesses.probe_login("ZAI_CODING_SUBSCRIPTION")[0]
            assert not harnesses.probe_login("GROK_SUBSCRIPTION")[0]


class Command:
    def run_status(self, *argv, state=None, ready=None):
        cfg = cfg_all()
        with TemporaryDirectory() as d, patch.dict(os.environ, {"DELEGATE_CONFIG_DIR": d, "CLAUDE_CODE_ENTRYPOINT": "cli"}):
            (Path(d) / "state.json").write_text(json.dumps({"v": 1, **(state or {})}))
            (Path(d) / "config.json").write_text(json.dumps({"profile": {"lanes": {"DEEPSEEK_FREE": "enabled"}}}))
            ready = ready or dict.fromkeys(cfg["lanes"], True)
            noread = {k: (lambda lane_, S, st_, t, *a: None) for k in usage.READERS}
            logins = {"OPENAI_SUBSCRIPTION": (False, "Not logged in"), "GROK_SUBSCRIPTION": (True, "ok")}
            out, sys.stdout = sys.stdout, io.StringIO()
            try:
                with (
                    patch.object(env, "load_routing", return_value=cfg),
                    patch.dict(usage.READERS, noread),
                    patch.object(onboard, "configured_lanes", return_value=ready),
                    patch.object(harnesses, "probe_login", side_effect=lambda n: logins.get(n, (True, "ok"))),
                    patch.object(env, "now", return_value=T),
                ):
                    route.main(["status", *argv])
                return sys.stdout.getvalue()
            finally:
                sys.stdout = out

    def test_text_is_short_and_names_every_known_lane_even_a_logged_out_one(self):
        text = self.run_status(ready={n: n != "ZAI_CODING_SUBSCRIPTION" for n in CFG["lanes"]})
        lines = text.splitlines()
        assert len(lines) <= 25, text
        for n in CFG["lanes"]:
            assert n in text
        assert "🔑 OPENAI_SUBSCRIPTION" in text  # the real check says logged out although the file is there
        assert "logged out: run `codex login`" in text
        assert "unlock time unknown: waits for you to log in" in text
        assert "⛔ ZAI_CODING_SUBSCRIPTION" in text
        assert "next worker:" in lines[0]

    def test_json_has_the_same_lanes_and_keeps_the_dashboard_keys(self):
        state = {"out": {"DEEPSEEK_FREE": {"until": T + 3 * HOUR, "why": "free usage limit still reached", "at": T - 60}}}
        text = self.run_status(state=state)
        data = json.loads(self.run_status("--json", state=state))
        ck = data["cockpit"]
        ids = [r["id"] for r in ck["lanes"]]
        assert ids == list(CFG["lanes"])
        for n in ids:
            assert n in text
        row = next(r for r in ck["lanes"] if r["id"] == "DEEPSEEK_FREE")
        assert (row["state"], row["unlock"]["in_s"]) == ("resting", 3 * HOUR)
        assert ("unlocks " + row["unlock"]["text"]) in text
        for k in ("lanes", "running", "needs_input"):
            assert k in data
        assert ck["next_worker"]["action"] in ("run", "stop")

