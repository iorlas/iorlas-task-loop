"""Breaker, reset times, token budget, config location"""

import datetime as dt
import inspect
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

import pytest
import stream_proc
from any_agent import reset_parse
from any_agent.classify import Outcome
from any_agent.harnesses.codex import CodexHarness
from any_agent.protocol import LaunchSpec
from any_agent.supervisor import RunHooks, Supervisor
from delegate.app import env, harnesses, launch, usage
from delegate.app.fleet import apply_health
from delegate.app.publish import LiveSink
from delegate.contracts import codec, stores
from delegate.contracts import history as hist
from delegate.domain.health import ledger as health_ledger
from delegate.domain.lanes.lane import Lane
from support.case import Case
from support.procsim import real_proc

import hermetic  # noqa: F401  (a home of its own for every test)
import routing_support as support
from run_support import short_limits
from test_route import CFG, T, argparse_ns, lanes, need, no_reader, route


class Breaker(Case):
    """delegate-rdt / -y3f: the pair breaker is wired into the decision for every lane, and DeepSeek/ZAI/Grok run under the watchdog."""

    def lanes_with(self, hist_rows):
        lanes_ = lanes()
        grok = Lane("GROK_SUBSCRIPTION", "xai", "subscription")
        lanes_[grok.name] = grok
        led = health_ledger.HealthLedger(env.settings_of(CFG).breaker)
        st = led.fold(hist_rows)
        for lane in lanes_.values():
            apply_health(lane, env.typed_routing(CFG).models, led, st, T + 1)
        return lanes_

    def rows(self, lane, model, n=3, outcome="worker_failed") -> list[hist.HistoryRow]:
        return [
            hist.RunRow(
                ts=T + i,
                run_id=f"r{i}",
                task=f"t{i}",
                role="worker",
                lane=lane,
                model=model,
                effort="high",
                done=False,
                outcome=outcome,
                fingerprint=health_ledger.fingerprint(outcome, "event", "boom"),
                say="boom",
                until=None,
            )
            for i in range(n)
        ]

    def test_a_benched_pair_falls_through_to_the_next_step_and_only_that_pair(self):
        ls = self.lanes_with(self.rows("OPENAI_SUBSCRIPTION", "gpt-6.1-sol"))
        assert "gpt-6.1-sol" in ls["OPENAI_SUBSCRIPTION"].benched
        d = support.decide("worker", CFG, ls, {}, T + 1, {"authored_by": None, "premium": None, "allow_degraded": False})
        assert d["model"] != "gpt-6.1-sol"
        S = env.settings_of(CFG)
        ok, why = ls["OPENAI_SUBSCRIPTION"].usable(S, True, "gpt-6.1-sol")
        assert not ok
        assert "benched" in why
        assert ls["OPENAI_SUBSCRIPTION"].usable(S, True, "gpt-6-luna")[0]
        assert ls["OPENAI_SUBSCRIPTION"].usable(S, True)[0]

    def test_all_pairs_benched_stops_with_the_bench_ends_listed(self):
        ls = self.lanes_with(
            self.rows("OPENAI_SUBSCRIPTION", "gpt-6.1-sol")
            + self.rows("CLAUDE_SUBSCRIPTION", "sonnet-5.5")
            + self.rows("CLAUDE_SUBSCRIPTION", "opus-5.5")
            + self.rows("GROK_SUBSCRIPTION", "grok-4.7")
        )
        d = support.decide("worker", CFG, ls, {}, T + 1, {"authored_by": None, "premium": None, "allow_degraded": False})
        assert d["action"] == "stop"
        assert "OPENAI_SUBSCRIPTION/gpt-6.1-sol" in d["resets"]

    def test_every_opencode_lane_runs_under_the_watchdog_and_the_breaker(self):
        lanes_ = [n for n, c in CFG["lanes"].items() if c["runner"] == "opencode"]
        assert sorted(lanes_) == ["DEEPSEEK_FREE", "GROK_SUBSCRIPTION", "ZAI_CODING_SUBSCRIPTION"]
        lim = harnesses.LIMITS["opencode"]
        assert (lim.first_event_s, lim.silence_s >= 900) == (120, True)
        for name in lanes_:
            fam = CFG["lanes"][name]["family"]
            models = [m for m, v in CFG["models"].items() if v["family"] == fam]
            assert models, name
            for model in models:
                with self.subTest(lane=name, model=model):
                    lane = Lane(name, fam, "subscription")
                    led = health_ledger.HealthLedger(env.settings_of(CFG).breaker)
                    apply_health(lane, env.typed_routing(CFG).models, led, led.fold(self.rows(name, model, outcome="vendor_blip")), T + 1)
                    assert not lane.usable(env.settings_of(CFG), True, model)[0]
        assert "run_prepared(" in inspect.getsource(launch.launch_worker)  # every prepared harness uses the same supervisor
        assert "Supervisor(" in inspect.getsource(launch.run_prepared)

    def test_history_rotation_survives_a_corrupt_line(self):
        def canary(ts, rid):
            return json.dumps(codec.to_json(hist.CanaryRow(ts=ts, run_id=rid, lane="L", model="m")))

        with (
            tempfile.TemporaryDirectory() as d,
            mock.patch.object(env, "config_dir", return_value=Path(d)),
            mock.patch.object(stores, "HISTORY_MAX", 100),
        ):
            p = env.history_path()
            p.write_text(
                "{broken\n" + canary(1.0, "old") + "\n" + canary(time.time(), "keep") + "\n" * 1 + "x" * 200 + "\n", encoding="utf-8"
            )
            env.history_add(hist.CanaryRow(ts=time.time(), run_id="new", lane="L", model="m"))
            ids = [json.loads(x)["run_id"] for x in p.read_text().splitlines()]
            assert ids == ["keep", "new"]


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

    @pytest.mark.skipif(not hasattr(time, "tzset"), reason="needs time.tzset")
    def test_will_reset_at_is_read_in_the_local_zone(self):
        (at, zone), _ = self.found("Usage limit reached. Your limit will reset at 2026-10-25 14:49:00.")
        assert dt.datetime.fromtimestamp(at).strftime("%Y-%m-%d %H:%M:%S") == "2026-10-25 14:49:00"
        assert zone.startswith("local")

    def test_a_stated_zone_is_kept(self):
        (at, zone), _ = self.found("resets at 2026-10-25T08:19:00Z")
        assert (dt.datetime.fromtimestamp(at, dt.UTC).strftime("%H:%M"), zone) == ("08:19", "UTC")
        (at, zone), _ = self.found("will reset at 2026-10-25 14:49:00 +08:00")
        assert (dt.datetime.fromtimestamp(at, dt.UTC).strftime("%H:%M"), zone) == ("06:49", "+08:00")

    def test_retry_after_seconds_and_http_date(self):
        (at, _), t = self.found("429 Too Many Requests, Retry-After: 120")
        assert at == t + 120
        (at, _), t = self.found(
            "HTTP 429 retry-after: Sun, 25 Oct 2026 12:00:00 GMT", dt.datetime(2026, 10, 25, 10, 0, tzinfo=dt.UTC).timestamp()
        )
        assert dt.datetime.fromtimestamp(at, dt.UTC).strftime("%H:%M") == "12:00"

    def test_in_n_hours_and_try_again_at(self):
        (at, _), t = self.found("You can try again in 5 hours.")
        assert at == t + 5 * 3600
        (at, _), t = self.found("limit reached, resets in 2 hours 30 minutes")
        assert at == t + 9000
        (at, _), t = self.found("try again at 5:50 AM")
        assert dt.datetime.fromtimestamp(at).strftime("%H:%M") == "05:50"

    def test_a_log_lines_own_timestamp_is_not_a_reset_time_and_unknown_text_is_not_parsed(self):
        line = 'timestamp=2026-10-25T03:02:47.846Z level=ERROR message="stream error" providerID=zai-coding-plan'
        assert self.at(line)[0] == (None, None)
        assert self.at("the batch run is queued behind a rate limit")[0] == (None, None)
        assert self.at("reset at 2026-10-24 14:49:00")[0] == (None, None)  # already past

    def test_unknown_text_is_refusal_time_plus_15_30_60(self):
        t = 1_800_000_000.0
        got = [reset_parse.limit_until("rate limited", t, {}, None, n) for n in range(4)]
        assert [round((u - t) / 60) for u, _, _ in got] == [15, 30, 60, 60]
        assert {src for _, src, _ in got} == {"guess"}
        assert reset_parse.limit_until("rate limited", t, {"limit_reset": t + 7200})[1:] == ("guess", None)
        assert reset_parse.limit_until("rate limited", t, {}, lambda: t + 999)[:2] == (t + 999, "vendor")

    @real_proc("delegate: a worker, git or CLI process")
    def test_out_rows_record_source_and_zone_and_report_is_manual(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(env, "config_dir", return_value=Path(d)):
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


class TokenBudget(Case):
    """The orchestrator pays for these files and outputs on every session / delegation.
    Budgets are characters (about 4 per token); ratchet them down, never up."""

    ROOT = Path(__file__).resolve().parents[2] / "skills" / "delegate"

    def test_agent_step_answer_is_small(self):
        saved = {k: os.environ.get(k) for k in ("XDG_CONFIG_HOME", "DELEGATE_CONFIG_DIR", "HOME", "CLAUDE_CODE_ENTRYPOINT")}
        with tempfile.TemporaryDirectory() as d:
            os.environ["XDG_CONFIG_HOME"] = os.environ["DELEGATE_CONFIG_DIR"] = os.environ["HOME"] = d
            os.environ["CLAUDE_CODE_ENTRYPOINT"] = "cli"
            real = dict(usage.READERS)
            usage.READERS.update(dict.fromkeys(real, no_reader))
            out, sys.stdout = sys.stdout, io.StringIO()
            try:
                route.main(["run", "planner"])  # fresh machine: the Claude sub-agent step
                answer = sys.stdout.getvalue()
            finally:
                sys.stdout = out
                usage.READERS.update(real)
                for k, v in saved.items():
                    os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        assert len(answer.replace(os.getcwd(), "")) <= 700, (
            answer
        )  # raised from 600 on 2026-10-20: the secrets rule in brief_prefix; the checkout's path is not ours to budget


class ConfigLocation(Case):
    """Settings, state and the key live in task-loop's folder (<config>/task-loop/delegate); the retired plugin's data is adopted once."""

    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved_here = env.DATA_DIR
        self.saved = {
            k: os.environ.get(k) for k in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "APPDATA", "DELEGATE_CONFIG_DIR", "CLAUDE_PLUGIN_DATA")
        }
        for k in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME", "APPDATA"):
            os.environ[k] = self.tmp.name
        os.environ.pop("DELEGATE_CONFIG_DIR", None)
        os.environ["CLAUDE_PLUGIN_DATA"] = str(Path(self.tmp.name) / "someone-elses-data")  # must be ignored

    def teardown_method(self):
        env.DATA_DIR = self.saved_here
        for k, v in self.saved.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
        self.tmp.cleanup()

    def test_without_an_override_the_state_lives_in_task_loops_folder(self):
        os.environ.pop("DELEGATE_CONFIG_DIR", None)
        os.environ["XDG_CONFIG_HOME"] = str(Path(self.tmp.name) / "xdg")
        want = Path(self.tmp.name) / "xdg" / "task-loop" / "delegate"
        assert env.config_dir() == want
        assert want.is_dir()

    def test_the_retired_plugins_data_is_adopted_once(self):
        os.environ.pop("DELEGATE_CONFIG_DIR", None)
        os.environ["XDG_CONFIG_HOME"] = str(Path(self.tmp.name) / "xdg")
        os.environ["HOME"] = self.tmp.name
        old = Path(self.tmp.name) / ".claude" / "plugins" / "data" / env.LEGACY_DATA
        old.mkdir(parents=True)
        (old / "config.json").write_text('{"profile": {"lanes": {}}}')
        got = env.config_dir()
        assert (got / "config.json").read_text() == '{"profile": {"lanes": {}}}'
        (old / "config.json").write_text("changed later")
        assert (env.config_dir() / "config.json").read_text() == '{"profile": {"lanes": {}}}'

    def test_explicit_override_wins(self):
        os.environ["DELEGATE_CONFIG_DIR"] = str(Path(self.tmp.name) / "mine")
        assert env.config_dir() == Path(self.tmp.name) / "mine"


class WatchdogProc(Case):
    """delegate-go0 on a real child process (python, so it runs on Windows too): a dead stream is stopped through stop_tree,
    a chatty one is not."""

    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(env, "config_dir", return_value=Path(self.tmp.name))
        p.start()
        self.addCleanup(p.stop)

    def run_child(self, code, **limits):
        with short_limits("codex", **limits):
            sup = Supervisor(CodexHarness(), RunHooks(), LiveSink("codex", ""), limits=harnesses.LIMITS["codex"])
        with mock.patch.object(stream_proc, "stop_tree", wraps=stream_proc.stop_tree) as st:
            t0 = time.time()
            out = sup.run(LaunchSpec(argv=[sys.executable, "-c", code], env=dict(os.environ), cwd=self.tmp.name, stdin=""), 0)
        return out.rc, {"why": out.watch.why, "kind": out.watch.kind}, st, time.time() - t0

    @real_proc("delegate: a worker, git or CLI process")
    def test_dead_stream_is_stopped_through_stop_tree(self):
        rc, state, st, _secs = self.run_child("import time;print('started',flush=True);time.sleep(60)", first_event_s=5, silence_s=1)
        assert (state["why"], state["kind"]) == ("hung", "silence")
        assert st.called
        assert rc != 0

    @real_proc("delegate: a worker, git or CLI process")
    def test_a_child_that_prints_nothing_is_hung_on_the_first_event_deadline(self):
        _rc, state, _st, _secs = self.run_child("import time;time.sleep(60)", first_event_s=1, silence_s=60)
        assert (state["why"], state["kind"]) == ("hung", "first_event")

    @real_proc("delegate: a worker, git or CLI process")
    def test_stderr_deltas_keep_a_quiet_stdout_alive(self):
        code = "import sys,time\nfor i in range(8):\n sys.stderr.write('thinking\\n');sys.stderr.flush();time.sleep(0.4)"
        rc, state, st, _secs = self.run_child(code, first_event_s=5, silence_s=1)
        assert (rc, state["why"], st.called) == (0, None, False)
