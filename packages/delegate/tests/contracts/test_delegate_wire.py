"""contracts: the codec, the goldens (one answer per status, captured before the typed contract existed), the generated
answer_schema, the live-file records. Goldens round-trip byte for byte up to key order."""

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from delegate.app import answer
from delegate.contracts import codec, live, schema, wire
from delegate.contracts.json_types import arr
from tltestkit.case import Case

ROOT = Path(__file__).resolve().parents[4]

GOLDEN = sorted((Path(__file__).resolve().parent / "golden").glob("*.json"))
CONTRACT = json.loads((ROOT / "packages" / "delegate" / "src" / "delegate" / "data" / "contract.json").read_text(encoding="utf-8"))


def canon(x):
    return json.dumps(x, sort_keys=True)


class Goldens(Case):
    def test_every_stop_reason_family_has_a_golden(self):
        names = {p.stem for p in GOLDEN}
        for want in (
            "done",
            "done_transcript",
            "done_warning",
            "agent_handoff",
            "stop_rate_limited",
            "stop_logged_out",
            "stop_network",
            "stop_timeout",
            "stop_hung",
            "stop_killed",
            "stop_secrets",
            "stop_bad_request",
            "stop_schema_invalid",
            "stop_worker_failed",
            "stop_no_lane_ask_user",
            "stop_busy_not_launched",
        ):
            assert want in names

    def test_a_golden_round_trips_through_the_records_unchanged(self):
        for p in GOLDEN:
            with self.subTest(p.stem):
                gold = json.loads(p.read_text())
                assert canon(codec.to_json(codec.from_json(wire.RunResult, gold))) == canon(gold)

    def test_a_golden_fits_the_generated_answer_schema(self):
        sch = schema.of(wire.RunResult)
        for p in GOLDEN:
            with self.subTest(p.stem):
                assert answer.schema_problem(json.loads(p.read_text()), sch) is None

    def test_route_builds_and_prints_the_golden(self):
        """result() + emit() rebuild each launched-and-stopped golden from its own facts and print it identically."""
        for p in GOLDEN:
            gold = json.loads(p.read_text())
            stop = gold["stop"]
            if gold.get("agent_model") or "stop_no_lane" in p.stem:  # built by decision(), not by result() alone
                continue
            kw = {k: v for k, v in gold.items() if k not in ("stop", "contract")}
            if stop:
                kw.update(
                    retry_after=stop["retry"]["at"], fix=stop.get("fix"), resumable=stop.get("resumable"), partial=stop.get("partial")
                )
            with self.subTest(p.stem), redirect_stdout(io.StringIO()) as out:
                answer.emit(answer.result(stop["reason"] if stop else None, **kw), False)
            assert canon(json.loads(out.getvalue())) == canon(gold)

    def test_new_fields_are_absent_until_set_and_a_null_is_not_absent(self):
        gold = json.loads((GOLDEN[0].parent / "done.json").read_text())
        for k in ("exit_code", "first_error", "ask_kind"):
            assert k not in gold
        gold["exit_code"] = None
        got = codec.to_json(codec.from_json(wire.RunResult, gold))
        assert "exit_code" in got
        assert got["exit_code"] is None

    def test_the_worker_names_its_process(self):
        w = wire.WorkerEnd(pid=7, pgid=7, start="Oct 1")
        assert codec.from_json(wire.WorkerEnd, codec.to_json(w)) == w
        assert "pid" not in codec.to_json(wire.WorkerEnd())


class Codec(Case):
    def test_an_int_stays_an_int_and_a_wrong_type_is_refused(self):
        gold = json.loads((GOLDEN[0].parent / "done.json").read_text())
        gold["cost"] = 0
        assert json.dumps(codec.to_json(codec.from_json(wire.RunResult, gold))["cost"]) == "0"
        for key, bad in (("cost", "free"), ("text", 3), ("denied", {}), ("contract", 2), ("transcript_status", "maybe")):
            with self.subTest(key), pytest.raises(codec.CodecError):
                codec.from_json(wire.RunResult, dict(gold, **{key: bad}))

    def test_an_unknown_key_and_a_missing_key_are_refused(self):
        gold = json.loads((GOLDEN[0].parent / "done.json").read_text())
        with pytest.raises(codec.CodecError):
            codec.from_json(wire.RunResult, dict(gold, surprise=1))
        with pytest.raises(codec.CodecError):
            codec.from_json(wire.RunResult, {k: v for k, v in gold.items() if k != "usage"})

    def test_a_stale_version_is_refused(self):
        with pytest.raises(codec.StaleRecord):
            codec.from_json(live.WorkerStarted, {"v": 2, "pid": 1, "pgid": 1, "run_id": "r"})


class Generated:
    def test_contract_json_answer_schema_is_what_the_records_generate(self):
        assert CONTRACT["answer_schema"] == schema.of(wire.RunResult)

    def test_the_schema_requires_what_the_wire_always_carries(self):
        sch = schema.of(wire.RunResult)
        required = set(arr(sch["required"]))
        assert {"contract", "stop", "usage", "tokens", "denied", "transcript_status"} <= required
        assert "worker" not in required
        assert not sch["additionalProperties"]


class LiveRecords(Case):
    def test_every_kind_round_trips_with_its_kind(self):
        recs = [
            live.LiveStart(t=1.0, harness="codex", pid=3, lane="L"),
            live.LiveCmdStart(t=1.0, id="a", text="ls", cwd="/w"),
            live.LiveCmdEnd(t=2.0, id="a", exit=None, secs=1.0, out="x"),
            live.LiveToolStart(t=1.0, id="b", text="edit f", prov=True),
            live.LiveToolEnd(t=2.0, id="b", secs=1.0),
            live.LiveMsg(t=1.0, text="m"),
            live.LiveThink(t=1.0, text="t"),
            live.LiveTokens(t=1.0, in_=5, cached=2, out=1),
            live.LiveStall(t=1.0, secs=61),
            live.LiveRetry(t=1.0, n=2, of=5, why="x"),
            live.LiveEnd(t=3.0, status="done", secs=2.0, cost_usd=0.5),
            live.LiveRaw(t=1.0, type="weird"),
        ]
        assert {r.KIND for r in recs} == set(live.LIVE_EVENTS)
        for r in recs:
            with self.subTest(r.KIND):
                wire_form = codec.to_json(r)
                assert wire_form["kind"] == r.KIND
                assert "k" not in wire_form
                assert codec.from_tagged(live.LIVE_EVENTS, wire_form) == r
        assert codec.to_json(live.LiveTokens(t=1.0, in_=5))["in"] == 5

    def test_start_end_kinds_come_in_pairs(self):
        kinds = set(live.LIVE_EVENTS)
        for k in kinds:
            if k.endswith("_start"):
                assert (k[:-6] + "_end") in kinds


def test_live_record_with_only_the_old_tag_is_refused():
    with pytest.raises(codec.CodecError):
        codec.from_tagged(live.LIVE_EVENTS, {"k": "msg", "t": 1.0, "text": "old"})
