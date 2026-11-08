"""HealthLedger: the fold, the breaker, the canary and the 24 Oct / 22 Oct incident replays (golden/health_replay.json, taken from the
pre-D2 fold: every row's admit/refuse decision must be the same). Run: uv run pytest packages/delegate/tests/domain/test_ledger_health.py"""

import json
from dataclasses import replace
from pathlib import Path

from any_breaker import State

from delegate.contracts import codec
from delegate.contracts.history import RefusalRow, ReleaseRow, RunRow
from delegate.contracts.json_types import as_num, as_opt_str
from delegate.contracts.routing import BreakerPolicy
from delegate.contracts.stores import CheckpointStore, HistoryStore
from delegate.domain.health.ledger import STATES, HealthLedger, combine, failure_fields, stale_usage
from delegate.domain.health.matchers import fingerprint
from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[4]

POL = BreakerPolicy()
LEDGER = HealthLedger(POL)
GOLDEN = json.loads((Path(__file__).resolve().parent / "golden" / "health_replay.json").read_text(encoding="utf-8"))


def row(ts, lane="L", model="m", outcome=None, task=None, say="", until=None, **kw):
    """A history row as verbs.cmd_run writes it."""
    fields = failure_fields(outcome, "event", say, until)
    return RunRow(
        ts=ts,
        run_id=kw.pop("run_id", f"r{ts}"),
        role="worker",
        lane=lane,
        model=model,
        effort="high",
        done=outcome is None,
        task=task or f"t{ts}",
        outcome=as_opt_str(fields.get("outcome")),
        fingerprint=as_opt_str(fields.get("fingerprint")),
        say=as_opt_str(fields.get("say")),
        until=as_num(fields.get("until")),
        **kw,
    )


def pair_keys(state):
    """The (lane, model) pairs the fold counts: any_breaker keys of the form `lane|model` (a lane out is keyed by the lane alone)."""
    return {k: v for k, v in state.keys.items() if "|" in k and not k.endswith("|")}


def fold(rows, state=None, pol=POL):
    return HealthLedger(pol).fold(rows, state)


def view(state, lane, model, t, pol=POL):
    return HealthLedger(pol).view(state, lane, model, t)


def golden_row(r):
    return RunRow(
        ts=r["ts"],
        run_id=r["run_id"],
        role=r.get("role") or "worker",
        lane=r["lane"],
        model=r["model"],
        effort="high",
        done=r.get("done", False),
        task=r.get("task") or "",
        outcome=r.get("outcome"),
        fingerprint=r.get("fingerprint"),
        say=r.get("say"),
        until=r.get("until"),
    )


class Replay:
    """The incident histories are the regression fixtures for the thresholds: each row is a launch the engine made at row.ts; the fold
    admits or refuses it. The admit/refuse/canary/state of every row equals the golden taken before the fold moved."""

    def replay(self, name):
        g = GOLDEN[name]
        state, got = State(), []
        for r in g["rows"]:
            v = view(state, g["lane"], g["model"], r["ts"])
            got.append([r["ts"], v.usable, v.canary, v.state])
            if v.usable:
                LEDGER.step(state, golden_row(r))
        assert got == g["decisions"]
        return state, g

    def test_24_oct_grok_spending_limit_stops_after_one_real_launch(self):
        state, g = self.replay("grok_spending_limit_24oct")
        assert len(g["rows"]) == 114
        admitted = sum(1 for d in g["decisions"] if d[1])
        assert admitted < 10
        assert view(state, g["lane"], g["model"], g["rows"][-1]["ts"] + 1).state == g["final"]
        assert g["final"] == "exhausted"

    def test_24_oct_grok_server_errors_of_one_task_bench_nothing_and_network_is_never_counted(self):
        state, g = self.replay("grok_other_24oct")
        assert [r["outcome"] for r in g["rows"]] == (["vendor_blip"] * 3 + ["network"])
        assert all(d[1] for d in g["decisions"])
        assert view(state, g["lane"], g["model"], g["rows"][-1]["ts"] + 1).state == "up"

    def test_22_oct_bad_request_never_benches_a_pair(self):
        state, g = self.replay("bad_request_22oct")
        assert len(g["rows"]) == 53
        assert all(d[1] for d in g["decisions"])  # every one of the 53 was admitted
        assert not (pair_keys(state) or state.outs)

    def test_22_oct_night_whole_history_never_benches(self):
        g = GOLDEN["night_22oct"]
        state, got = State(), []
        for r in sorted(g["rows"], key=lambda r: r["ts"]):
            got.append([r["ts"], view(state, r["lane"], r["model"], r["ts"]).usable])
            LEDGER.step(state, golden_row(r))
        assert got == g["decisions"]
        assert {k: p.rung for k, p in pair_keys(state).items()} == g["pairs"]
        assert sorted(state.outs) == g["lanes"]
        assert not [k for k, p in pair_keys(state).items() if p.rung]


class Breaker(Case):
    def test_three_identical_failures_from_two_tasks_bench_the_pair_15_minutes(self):
        s = fold([row(1000 + 60 * i, outcome="vendor_blip", say="Server error.", task="a" if i < 2 else "b") for i in range(3)])
        v = view(s, "L", "m", 1121)
        assert (v.state, v.usable, v.kind, v.source, v.rung) == ("broken", False, "vendor_blip", "breaker", 1)
        assert v.until == (1120 + 15 * 60)
        assert v.evidence == "Server error."
        assert len(v.last_failures) == 3

    def test_one_task_failing_three_times_benches_nothing(self):
        s = fold([row(1000 + 60 * i, outcome="vendor_blip", say="Server error.", task="same") for i in range(5)])
        assert view(s, "L", "m", 1400).usable

    def test_different_fingerprints_do_not_add_up(self):
        s = fold(
            [
                row(1000, outcome="vendor_blip", say="boom A", task="a"),
                row(1060, outcome="vendor_blip", say="other text", task="b"),
                row(1120, outcome="vendor_blip", say="third thing", task="c"),
            ]
        )
        assert view(s, "L", "m", 1130).usable

    def test_numbers_ids_and_times_in_the_text_do_not_make_failures_different(self):
        a = fingerprint("vendor_blip", "event", "Request 4821 failed at 2026-10-24T02:31:53Z id 3f2a9c1b77")
        b = fingerprint("vendor_blip", "event", "Request 77 failed at 2026-10-24T09:00:00Z id aa00bb11cc")
        assert a == b

    def test_failures_outside_the_window_do_not_count(self):
        s = fold(
            [
                row(1000, outcome="vendor_blip", say="x", task="a"),
                row(1000 + 11 * 60, outcome="vendor_blip", say="x", task="b"),
                row(1000 + 22 * 60, outcome="vendor_blip", say="x", task="c"),
            ]
        )
        assert view(s, "L", "m", 1000 + 23 * 60).usable

    def test_a_done_resets_the_streak_and_the_ladder(self):
        s = fold(
            [
                row(1000, outcome="vendor_blip", say="x", task="a"),
                row(1010, outcome="vendor_blip", say="x", task="b"),
                row(1020, outcome=None),
                row(1030, outcome="vendor_blip", say="x", task="c"),
            ]
        )
        assert view(s, "L", "m", 1040).usable

    def test_ladder_is_15_30_60_then_stays_at_60_and_a_passing_canary_resets_it(self):
        s = State()
        for i in range(3):
            LEDGER.step(s, row(1000 + i, outcome="worker_failed", say="x", task=f"t{i}"))
        fail_at, minutes = 1002, []
        for _ in range(4):
            v = view(s, "L", "m", fail_at + 1)
            assert (v.state, v.usable) == ("broken", False)
            assert v.until is not None
            minutes.append(round((v.until - fail_at) / 60))
            fail_at = v.until + 1  # the bench ends: the next launch is the canary...
            assert (view(s, "L", "m", fail_at).usable, view(s, "L", "m", fail_at).canary) == (True, True)
            LEDGER.step(s, row(fail_at, outcome="worker_failed", say="x", task="canary"))  # ...and it fails: next rung at once
        assert minutes == [15, 30, 60, 60]
        after = view(s, "L", "m", fail_at + 1).until
        assert after is not None
        t = after + 1
        LEDGER.step(s, row(t, outcome=None))  # a canary that passes
        v = view(s, "L", "m", t + 1)
        assert (v.state, v.rung, v.canary) == ("up", 0, False)

    def test_hung_twice_in_30_minutes_benches_the_pair(self):
        s = fold([row(1000, outcome="hung"), row(1000 + 20 * 60, outcome="hung")])
        assert view(s, "L", "m", 1000 + 21 * 60).kind == "hung"
        s = fold([row(1000, outcome="hung"), row(1000 + 40 * 60, outcome="hung")])
        assert view(s, "L", "m", 1000 + 41 * 60).usable

    def test_never_counted_reasons_leave_every_pair_up(self):
        never = [
            "bad_request",
            "network",
            "killed",
            "timeout",
            "secrets",
            "schema_invalid",
            "held",
            "busy",
            "caller",
            "lock",
            "setup",
            "crash",
        ]
        s = fold([row(1000 + i, outcome=never[i % len(never)], say="same", task=f"t{i}") for i in range(60)])
        assert view(s, "L", "m", 1100).usable
        assert not (pair_keys(s) or s.outs)

    def test_refusals_are_not_facts(self):
        s = fold([RefusalRow(ts=1000 + i, outcome="vendor_blip", role="worker", lane="L", model="m", say="x") for i in range(9)])
        assert view(s, "L", "m", 1100).usable

    def test_pairs_are_independent(self):
        s = fold([row(1000 + i, model="a", outcome="worker_failed", say="x", task=f"t{i}") for i in range(3)])
        assert not view(s, "L", "a", 1010).usable
        assert view(s, "L", "b", 1010).usable

    def test_n_and_window_are_config_values(self):
        pol = BreakerPolicy(n=2)
        s = fold([row(1000, outcome="worker_failed", say="x", task="a"), row(1001, outcome="worker_failed", say="x", task="b")], pol=pol)
        assert view(s, "L", "m", 1002, pol).usable  # worker_failed also needs 3 distinct tasks
        s = fold([row(1000, outcome="vendor_blip", say="x", task="a"), row(1001, outcome="vendor_blip", say="x", task="b")], pol=pol)
        assert not view(s, "L", "m", 1002, pol).usable

    def test_breaker_applies_to_grok_deepseek_and_zai_pairs(self):
        for lane, model in (
            ("GROK_SUBSCRIPTION", "grok-4.7"),
            ("DEEPSEEK_FREE", "deepseek-v4.1-flash-free"),
            ("ZAI_CODING_SUBSCRIPTION", "glm-5.3"),
        ):
            with self.subTest(lane=lane):
                s = fold([row(1000 + i, lane, model, "vendor_blip", say="Server error.", task=f"t{i}") for i in range(3)])
                assert not view(s, lane, model, 1010).usable


class LaneFacts:
    def test_vendor_time_ends_a_limit_and_then_one_canary(self):
        s = fold([row(1000, outcome="rate_limited", say="limit", until=5000.0)])
        v = view(s, "L", "any-model", 2000)
        assert (v.state, v.usable, v.source, v.until) == ("exhausted", False, "vendor", 5000.0)
        v = view(s, "L", "any-model", 5001)
        assert (v.state, v.usable, v.canary) == ("up", True, True)

    def test_limit_without_a_time_is_a_guess_of_15_minutes(self):
        v = view(fold([row(1000, outcome="rate_limited", say="limit")]), "L", "m", 1001)
        assert (v.source, v.until) == ("guess", 1000 + 900)

    def test_credit_probe_after_6_hours_and_logged_out(self):
        s = fold(
            [
                row(1000, lane="C", outcome="credit_exhausted", say="out of credits"),
                row(1000, lane="O", outcome="logged_out", say="not logged in"),
            ]
        )
        assert view(s, "C", "m", 1000 + 6 * 3600 - 1).state == "exhausted"
        assert view(s, "O", "m", 1001).state == "logged_out"
        assert view(s, "C", "m", 1000 + 6 * 3600 + 1).usable

    def test_a_done_on_the_lane_ends_its_limit_and_a_release_row_too(self):
        s = fold([row(1000, outcome="rate_limited", say="x", until=9e9), row(1100, model="other", outcome=None)])
        assert view(s, "L", "m", 1200).usable
        s = fold([row(1000, outcome="rate_limited", say="x", until=9e9), ReleaseRow(ts=1100, lane="L")])
        assert view(s, "L", "m", 1200).usable

    def test_a_lane_limit_and_a_bench_that_both_ended_still_make_the_next_launch_a_canary(self):
        s = fold(
            [row(1000, outcome="rate_limited", say="x", until=1500.0)]
            + [row(1100 + i, outcome="worker_failed", say="y", task=f"t{i}") for i in range(3)]
        )
        v = view(s, "L", "m", 1300)
        assert (v.state, v.usable, v.canary) == ("exhausted", False, False)
        s2 = fold([row(1000, outcome="rate_limited", say="x", until=1500.0), row(1400, outcome="worker_failed", say="y", task="a")])
        assert view(s2, "L", "m", 1600).canary

    def test_combine_picks_the_most_severe_state(self):
        up = view(State(), "L", "m", 1)
        assert combine(up) == "up"
        assert combine(up, busy=True) == "busy"
        assert combine(up, held=True, busy=True) == "held"
        ex = view(fold([row(1, outcome="rate_limited", say="x", until=99.0)]), "L", "m", 2)
        assert combine(ex, busy=True) == "exhausted"
        assert set(STATES) == {"up", "busy", "exhausted", "logged_out", "held", "broken"}

    def test_usage_older_than_6_hours_is_unknown_not_a_gate(self):
        assert stale_usage(1000, 1000 + 5 * 3600, POL) is None
        assert stale_usage(1000, 1000 + 7 * 3600, POL) == 7.0
        assert stale_usage(None, 1e9, POL) is None


class Fold:
    def rows(self):
        return [
            row(
                1000 + 100 * i,
                outcome="vendor_blip" if i % 7 < 3 else ("rate_limited" if i % 11 == 0 else None),
                say="Server error.",
                task=f"t{i % 4}",
                until=3000.0 + 100 * i,
            )
            for i in range(40)
        ]

    def dump(self, s):
        return json.dumps(s.to_dict(), sort_keys=True)

    def test_replay_is_deterministic_and_order_independent(self):
        rows = self.rows()
        assert self.dump(fold(rows)) == self.dump(fold(list(reversed(rows))))

    def test_checkpoint_plus_tail_equals_full_fold(self):
        rows = self.rows()
        for cut in (5, 17, 33):
            cp = State.from_dict(json.loads(self.dump(fold(rows[:cut]))))  # a checkpoint went through a file
            assert self.dump(fold(rows, cp)) == self.dump(fold(rows))  # rows at or before the checkpoint are skipped

    def test_history_skips_corrupt_and_stale_lines(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "history.jsonl"
            h = HistoryStore(p)
            h.add(row(1000, outcome="worker_failed", say="x"))
            with open(p, "a", encoding="utf-8") as f:
                f.write(
                    "{not json\n\n[1,2]\n" + json.dumps({"ts": 5, "run_id": "old", "done": True}) + "\n"
                )  # the old shape has no kind: dropped
            h.add(row(1001, outcome="worker_failed", say="x"))
            assert [r.ts for r in h.rows()] == [1000, 1001]
            assert HistoryStore(Path(d) / "missing.jsonl").rows() == []
            assert [r.ts for r in h.rows(since=1000)] == [1001]

    def test_checkpoint_file_is_only_a_cache(self):
        with TemporaryDirectory() as d:
            store = CheckpointStore(Path(d) / "cp.json")
            s = fold(self.rows())
            store.save(s, POL)
            assert store.load(POL) == s
            assert store.load(BreakerPolicy(n=9)) is None  # another policy: refold
            (Path(d) / "cp.json").write_text("{garbage", encoding="utf-8")
            assert store.load(POL) is None
            store.save(s, POL)
            doc = json.loads((Path(d) / "cp.json").read_text(encoding="utf-8"))
            doc["state"] = {"v": 1, "ts": 99999.0, "pairs": {}, "lanes": {}}  # the shape before any_breaker: absent, never a stale ts
            (Path(d) / "cp.json").write_text(json.dumps(doc), encoding="utf-8")
            assert store.load(POL) is None

    def test_a_run_row_carries_v_fingerprint_say(self):
        f = failure_fields("vendor_blip", "event", "Server error. " + "x" * 400, None)
        assert (f["outcome"], len(as_opt_str(f["fingerprint"]) or ""), len(as_opt_str(f["say"]) or "")) == ("vendor_blip", 12, 240)
        assert failure_fields(None, "", "") == {}
        assert codec.to_json(row(1, outcome="hung", say="x"))["v"] == 1
        assert replace(POL, n=2).n == 2
