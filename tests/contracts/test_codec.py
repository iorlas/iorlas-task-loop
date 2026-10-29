"""The codec: every record round-trips, a golden JSON locks each kind's wire shape, and bad data is refused by name."""
import dataclasses
import enum
import importlib
import json
import os
import pkgutil
import sys
import unittest
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

import taskloop.contracts as pkg
from contracts import samples as S
from taskloop.contracts import codec, delegate, enums, events, ids, log, trace
from taskloop.contracts.ask import Ask
from taskloop.contracts.codec import CodecError, StaleRecord
from taskloop.contracts.loop import LoopCommand
from taskloop.contracts.run import LoopLogLine

GOLDEN = Path(__file__).resolve().parent / "golden"
FAMILIES = {"engine_log": (S.LOG, log.ENGINE_LOG), "events": (S.EVENTS, events.EVENT), "live_events": (S.LIVE, delegate.LIVE_EVENT)}


def reachable(obj: Any, out: set) -> None:
    """Every dataclass type found in `obj`, nested ones included."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        out.add(type(obj))
        for f in dataclasses.fields(obj):
            reachable(getattr(obj, f.name), out)
    elif isinstance(obj, (list, tuple, set, frozenset)):
        for x in obj:
            reachable(x, out)
    elif isinstance(obj, dict):
        for x in obj.values():
            reachable(x, out)


def golden_check(test: unittest.TestCase, name: str, produced: str) -> None:
    path = GOLDEN / name
    if os.environ.get("UPDATE_GOLDEN"):
        path.parent.mkdir(exist_ok=True)
        path.write_text(produced, encoding="utf-8")
    test.assertEqual(produced, path.read_text(encoding="utf-8"), f"{name} differs; UPDATE_GOLDEN=1 rewrites it")


class RoundTrip(unittest.TestCase):
    def test_every_record_round_trips_through_json_text(self):
        for coll in (S.LOG, S.EVENTS, S.LIVE, S.OTHERS):
            for name, rec in coll.items():
                with self.subTest(name):
                    wire = json.loads(json.dumps(codec.to_json(rec)))
                    back = codec.from_json(type(rec), wire)
                    self.assertEqual(back, rec)
                    self.assertEqual(codec.to_json(back), wire)

    def test_every_record_class_of_the_package_has_a_sample(self):
        found: set = set()
        for coll in (S.LOG, S.EVENTS, S.LIVE, S.OTHERS):
            for rec in coll.values():
                reachable(rec, found)

        bases = {"LogRec", "EventRec", "LiveRec"}
        missing = []
        for m in pkgutil.iter_modules(pkg.__path__):
            if (
                m.name in ("codec", "jsonl", "stores", "schema", "paths", "ports", "answers", "dash")
            # plumbing, not records (ports: call arguments, never written; answers: the workers' replies, tests/contracts/test_schema.py;
            # dash: the dashboard view, sampled by tests/fixtures/dash_v2 and tests/contracts/test_dash.py)
            ):
                continue
            mod = importlib.import_module("taskloop.contracts." + m.name)
            for n, c in vars(mod).items():
                if (
                    isinstance(c, type)
                    and dataclasses.is_dataclass(c)
                    and c.__module__ == mod.__name__
                    and n not in bases
                    and c not in found
                ):
                    missing.append(f"{m.name}.{n}")
        self.assertEqual(missing, [], "add a sample for each record in tests/contracts/samples.py")

    def test_union_tables_cover_every_member(self):
        self.assertEqual(set(log.ENGINE_LOG), set(S.LOG))
        self.assertEqual(set(events.EVENT), set(S.EVENTS))
        self.assertEqual(set(delegate.LIVE_EVENT), set(S.LIVE))

    def test_a_union_member_decodes_by_its_kind(self):
        for name, (coll, table) in FAMILIES.items():
            for kind, rec in coll.items():
                with self.subTest(f"{name}/{kind}"):
                    self.assertIs(type(codec.from_tagged(table, codec.to_json(rec))), type(rec))


class Golden(unittest.TestCase):
    def test_one_line_per_kind_of_each_union(self):
        for name, (coll, _) in FAMILIES.items():
            produced = "".join(json.dumps(codec.to_json(rec)) + "\n" for rec in coll.values())
            golden_check(self, name + ".jsonl", produced)

    def test_the_other_records(self):
        produced = json.dumps({k: codec.to_json(v) for k, v in S.OTHERS.items()}, indent=1, sort_keys=False) + "\n"
        golden_check(self, "records.json", produced)

    def test_a_golden_line_decodes_to_its_sample(self):
        for name, (coll, table) in FAMILIES.items():
            lines = (GOLDEN / (name + ".jsonl")).read_text(encoding="utf-8").splitlines()
            for line, rec in zip(lines, coll.values(), strict=False):
                self.assertEqual(codec.from_tagged(table, json.loads(line)), rec)


class Refusals(unittest.TestCase):
    def wire(self, **kw):
        d = codec.to_json(S.OUTCOME)
        d.update(kw)
        return d

    def test_a_foreign_version_is_stale(self):
        with self.assertRaises(StaleRecord) as cm:
            codec.from_json(type(S.OUTCOME), self.wire(v=1))
        self.assertEqual((cm.exception.found, cm.exception.want), (1, 2))
        with self.assertRaises(StaleRecord):
            codec.from_json(type(S.OUTCOME), {k: v for k, v in self.wire().items() if k != "v"})

    def test_an_unknown_key_is_refused(self):
        with self.assertRaisesRegex(CodecError, "unknown key extra"):
            codec.from_json(type(S.OUTCOME), self.wire(extra=1))

    def test_a_missing_required_key_is_named(self):
        d = self.wire()
        del d["bead"]
        with self.assertRaisesRegex(CodecError, "bead: missing"):
            codec.from_json(type(S.OUTCOME), d)

    def test_types_are_not_coerced(self):
        for key, bad in (("minutes", "3"), ("rounds", 2.5), ("rounds", True), ("asked", 1), ("bead", 7), ("outcome", "nope")):
            with self.subTest(key), self.assertRaises(CodecError):
                codec.from_json(type(S.OUTCOME), self.wire(**{key: bad}))

    def test_an_int_is_a_float_but_a_float_is_not_an_int(self):
        self.assertEqual(codec.from_json(type(S.OUTCOME), self.wire(minutes=3)).minutes, 3.0)

    def test_the_path_names_the_nested_field(self):
        d = codec.to_json(S.LOG["call_end"])
        d["tokens"]["out"] = "many"
        with self.assertRaisesRegex(CodecError, r"CallEnd\.tokens\.out"):
            codec.from_json(log.CallEnd, d)

    def test_a_wrong_kind_and_an_unknown_kind(self):
        d = codec.to_json(S.LOG["warn"])
        with self.assertRaisesRegex(CodecError, "kind 'warn', expected 'note'"):
            codec.from_json(log.Note, d)
        with self.assertRaisesRegex(CodecError, "unknown kind"):
            codec.from_tagged(log.ENGINE_LOG, dict(d, kind="nope"))
        with self.assertRaisesRegex(CodecError, "expected an object"):
            codec.from_json(log.Note, [])

    def test_a_literal_takes_only_its_members(self):
        d = codec.to_json(S.other(LoopCommand))
        d["action"] = "explode"
        with self.assertRaisesRegex(CodecError, "not one of"):
            codec.from_json(type(S.other(LoopCommand)), d)


class Wire(unittest.TestCase):
    def test_a_keyword_field_keeps_its_wire_name(self):
        self.assertEqual(codec.to_json(trace.Tokens(in_=3, cached=2, out=1)), {"in": 3, "cached": 2, "out": 1})
        self.assertEqual(codec.from_json(trace.Tokens, {"in": 3}).in_, 3)

    def test_v_and_kind_come_first(self):
        self.assertEqual(list(codec.to_json(S.LOG["lock"]))[:3], ["v", "kind", "t"])

    def test_a_set_is_written_sorted_and_a_tuple_as_an_array(self):
        @codec.record
        class WithSet:
            features: frozenset[str]

        self.assertEqual(codec.to_json(WithSet(features=frozenset({"b", "a"})))["features"], ["a", "b"])
        self.assertEqual(codec.to_json(S.LOCK)["route"], [10, S.T])

    def test_an_optional_nested_record_is_null_or_a_dict(self):
        a = S.other(Ask)
        self.assertEqual(codec.to_json(a)["answer"]["action"], "confirm")
        self.assertIsNone(codec.to_json(dataclasses.replace(a, answer=None))["answer"])

    def test_nested_records_carry_no_version(self):
        d = codec.to_json(S.other(LoopLogLine))
        self.assertEqual(d["v"], 2)
        self.assertNotIn("v", d["outcome"])

    def test_the_hints_are_read_once_per_class(self):
        codec.plan.cache_clear()
        for _ in range(3):
            codec.to_json(S.TRACE)
        seen: set = set()
        reachable(S.TRACE, seen)
        self.assertEqual(codec.plan.cache_info().misses, len(seen))


class Ids(unittest.TestCase):
    def test_run_id_round_trips_its_string(self):
        r = ids.RunId.parse("lifesim-vbo-20261018-215800")
        self.assertEqual((str(r.bead), r.started.hour, str(r)), ("lifesim-vbo", 21, "lifesim-vbo-20261018-215800"))
        self.assertEqual(ids.RunId.parse("tl-7y6.3.1-20261027-002239").bead, "tl-7y6.3.1")
        self.assertEqual(ids.RunId.parse(str(r)), r)

    def test_a_bad_run_id_or_bead_id(self):
        for text in ("nodate", "x-2026-10", "-20261018-215800", "a-20261318-215800", "a b-20261018-215800"):
            with self.subTest(text), self.assertRaises(ValueError):
                ids.RunId.parse(text)
        for text in ("", "-a", ".a", "a b", "é"):
            with self.assertRaises(ValueError):
                ids.parse_bead_id(text)

    def test_versions_order_as_numbers(self):
        v = ids.Version.parse
        self.assertGreater(v("0.23.56"), v("0.9.1"))
        self.assertEqual(str(v("0.23.56")), "0.23.56")
        for bad in ("", "1..2", "1.a", "v1"):
            with self.assertRaises(ValueError):
                v(bad)

    def test_repo_key_is_twelve_hex(self):
        k = ids.repo_key("/r/.git")
        self.assertEqual((len(k), k, ids.repo_key("/r/.git")), (12, k, k))

    def test_enum_members_are_their_wire_strings(self):
        for e in vars(enums).values():
            if isinstance(e, type) and issubclass(e, enum.StrEnum) and e is not enum.StrEnum:
                self.assertTrue(all(str(m) == m.value for m in e), e)


if __name__ == "__main__":
    unittest.main()
