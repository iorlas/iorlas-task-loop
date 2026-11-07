"""Incremental facts match the original whole-log projection and survive JSON."""

import dataclasses
import json
import random
from pathlib import Path
from typing import get_args

import msgspec
from support.dashlogs import RunScript, T

from taskloop_dash import jsonl
from taskloop_dash.views import runfacts as facts
from tlkernel import log as rec
from tlkernel import wire
from tlkernel.runlife import Liveness
from tlkernel.stuck import open_episode
from tltestkit.case import Case


def fixture_records(path):
    """Adapt the archived v2 corpus in tests only; production still rejects foreign versions."""
    types = {tp.__struct_config__.tag: tp for tp in get_args(rec.EngineLog)}
    rows = []
    for line in path.read_bytes().splitlines():
        raw = json.loads(line)
        if raw.get("v") != 2:
            row = jsonl.parse(line)
            if row is not None:
                rows.append(row)
            continue
        tp = types[raw["kind"]]
        if "run" in raw and isinstance(raw["run"], str):
            raw["run_id"] = raw["run"]
        if "prev_run" in raw:
            raw["parent_id"] = raw["prev_run"]
        if raw["kind"] == "step_end":
            raw["exec_seconds"] = raw.get("secs", 0.0)
        if raw["kind"] == "wait_end":
            raw["wait_seconds"] = raw.get("secs", 0.0)
        if raw["kind"] == "checks":
            items = []
            for original in raw["items"]:
                item = {**original, "secs": original.get("secs") or 0.0, "tries": original.get("tries") or 1}
                if item["status"] == "ran":
                    item["status"] = "passed" if item["exit"] == 0 else "failed"
                items.append(item)
            raw["run"] = {"round": raw["round"], "results": items}
        fields = {f.encode_name for f in msgspec.structs.fields(tp)}
        rows.append(wire.load(rec.EngineLog, {"v": 3, "kind": raw["kind"], **{k: v for k, v in raw.items() if k in fields}}))
    return rows


def whole(name, records):
    """The pre-fold run_of algorithm, kept independent of the new fold."""
    body = [r for r in records if not isinstance(r, rec.Beat)]
    start = next((r for r in body if isinstance(r, rec.RunStart)), None)
    return facts.Run(
        name, Liveness.LIVE, start, start.t if start else (body[0].t if body else 0.0),
        max((r.t for r in body), default=0.0), facts.spans_of(body), facts.calls_of(body),
        next((r for r in reversed(body) if isinstance(r, rec.Close)), None),
        tuple(r for r in body if isinstance(r, rec.Transition)), tuple(r for r in body if isinstance(r, rec.Artifacts)),
        next((r for r in reversed(body) if isinstance(r, rec.Checks)), None), facts.open_wait(body),
        next((r.lane for r in reversed(body) if isinstance(r, rec.CallEnd) and r.lane), ""),
        next((r.exit for r in reversed(body) if isinstance(r, rec.CallEnd) and r.exit is not None), None),
        said=tuple(r for r in body if isinstance(r, rec.Said)),
        assumed=sum(isinstance(r, rec.Assumed) for r in body), stuck=open_episode(body), waits=facts.waits_of(body))


class RunFold(Case):
    def check_records(self, name, records):
        empty = facts.FoldState()
        state = facts.fold(empty, records)
        made = facts.run_from(name, state, T)
        assert dataclasses.replace(made, budgets=()) == whole(name, records)
        assert made.records == ()
        restored = wire.load(facts.FoldState, json.dumps(wire.dump(state)))
        assert restored == state
        assert facts.run_from(name, restored, T) == made
        splits = range(len(records) + 1) if len(records) < 100 else random.Random(5).sample(range(len(records) + 1), 40)
        for i in splits:
            with self.subTest(name=name, split=i):
                prefix = facts.fold(empty, records[:i])
                saved = wire.load(facts.FoldState, json.dumps(wire.dump(prefix)))
                assert facts.fold(saved, records[i:]) == state
                assert prefix == facts.fold(empty, records[:i])

    def test_engine_fixture_corpus(self):
        paths = sorted(Path("tests/fixtures/state/engine").glob("*.jsonl"))
        paths += [Path("tests/contracts/golden/engine_log.jsonl")]
        count = 0
        for path in paths:
            rows = fixture_records(path)
            if any(isinstance(r, rec.RunStart) for r in rows):
                count += 1
                with self.subTest(path=path):
                    self.check_records(path.stem, rows)
        assert count > 0

    def test_pairs_stuck_and_non_events_across_every_boundary(self):
        s = RunScript("b-1").add("wait_start", id="w1", what="lane")
        s.add("wait_start", id="w2", what="network").add("wait_end", id="w1", wait_seconds=4)
        s.add("stuck", why="silent", step="write", since=T).beat()
        s.step("write", 10, 123, lane="lane").add("wait_end", id="w2", wait_seconds=8)
        s.add("stuck", why="same_red", step="checks", since=T, sig="red")
        s.add("note", text="still red").add("checks", node_id="n", run={"round": 1, "results": []})
        s.close("done")
        self.check_records(s.name, s.records())
        self.check_records("empty", [])

    def test_unshown_rows_do_not_grow_state_and_completed_pairs_are_released(self):
        s = RunScript("b-1").step("write", 1, 2)
        state = facts.fold(facts.FoldState(), s.records())
        before = wire.dump(state)
        assert state.open_calls == ()
        assert state.open_waits == ()
        noise = [rec.Note(t=s.t, text="ignored"), rec.Beat(t=s.t + 100)] * 1000
        assert wire.dump(facts.fold(state, noise)) == before

    def test_generated_stage_facts_and_budget_totals(self):
        s = RunScript("b-1").step("plan", 10, 100, cost=0.1, source="harness")
        s.add("assumed", step="n1", text="one assumption").move("write", "planned")
        s.step("write", 20, 200, lane="lane").artifacts(2, "write", "answer.json")
        s.add("said", step="n2", who="engine", text="written")
        s.add("overrun", stage="write", budget_s=10, elapsed_s=20)
        s.step("checks", 5).add("checks", node_id="n3", run={"round": 1, "results": [
            {"id": "unit", "cmd": "pytest", "group": "tests", "exit": 0, "status": "passed", "wall_min": 2}]})
        self.check_records(s.name, s.records())
        state = facts.fold(facts.FoldState(), s.records())
        assert [(b.checks, b.budget, b.elapsed) for b in state.budgets] == [(0, 0, 0), (0, 10, 20), (120, 0, 0)]
