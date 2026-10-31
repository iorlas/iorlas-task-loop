"""The wire form of the records: every record round-trips, a golden JSON locks each kind's wire shape, and bad data is refused."""
import enum
import importlib
import json
import os
import pkgutil
import sys
import unittest
from pathlib import Path
from typing import Any, get_args

import msgspec

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

import taskloop.contracts as pkg
from contracts import samples as S
from taskloop.contracts import delegate, enums, events, ids, log, trace, wire
from taskloop.contracts.ask import Ask
from taskloop.contracts.loop import LoopCommand
from taskloop.contracts.wire import Rec, StaleRecord

GOLDEN = Path(__file__).resolve().parent / "golden"
FAMILIES = {"engine_log": (S.LOG, log.EngineLog), "events": (S.EVENTS, events.Event), "live_events": (S.LIVE, delegate.LiveEvent)}


def kinds(union: Any) -> set[str]:
    """The tags of a tagged union's members."""
    return {m.__struct_config__.tag for m in get_args(union)}


def reachable(obj: Any, out: set) -> None:
    """Every record type found in `obj`, nested ones included."""
    if isinstance(obj, Rec):
        out.add(type(obj))
        for name in wire.names(type(obj)):
            reachable(getattr(obj, name), out)
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
                    body = json.loads(json.dumps(wire.dump(rec)))
                    back = wire.load(type(rec), body)
                    self.assertEqual(back, rec)
                    self.assertEqual(json.loads(json.dumps(wire.dump(back))), body)

    def test_every_record_class_of_the_package_has_a_sample(self):
        found: set = set()
        for coll in (S.LOG, S.EVENTS, S.LIVE, S.OTHERS):
            for rec in coll.values():
                reachable(rec, found)

        bases = {"Row", "LogRec", "EventRec", "LiveRec"}
        missing = []
        for m in pkgutil.iter_modules(pkg.__path__):
            if (
                m.name in ("wire", "jsonl", "stores", "schema", "paths", "ports", "answers", "dash", "dashcost", "needs")
            # plumbing, not records (ports: call arguments, never written; answers: the workers' replies, tests/contracts/test_schema.py;
            # dash, dashcost, needs: the dashboard view, sampled by tests/fixtures/dash and tests/contracts/test_dash.py)
            ):
                continue
            mod = importlib.import_module("taskloop.contracts." + m.name)
            for n, c in vars(mod).items():
                if (
                    isinstance(c, type)
                    and issubclass(c, Rec)
                    and c.__module__ == mod.__name__
                    and n not in bases
                    and c not in found
                ):
                    missing.append(f"{m.name}.{n}")
        self.assertEqual(missing, [], "add a sample for each record in tests/contracts/samples.py")

    def test_union_tables_cover_every_member(self):
        self.assertEqual(kinds(log.EngineLog), set(S.LOG))
        self.assertEqual(kinds(events.Event), set(S.EVENTS))
        self.assertEqual(kinds(delegate.LiveEvent), set(S.LIVE))

    def test_a_union_member_decodes_by_its_kind(self):
        for name, (coll, table) in FAMILIES.items():
            for kind, rec in coll.items():
                with self.subTest(f"{name}/{kind}"):
                    self.assertIs(type(wire.load(table, wire.dump(rec))), type(rec))


class Golden(unittest.TestCase):
    def test_one_line_per_kind_of_each_union(self):
        for name, (coll, _) in FAMILIES.items():
            produced = "".join(json.dumps(wire.dump(rec)) + "\n" for rec in coll.values())
            golden_check(self, name + ".jsonl", produced)

    def test_the_other_records(self):
        produced = json.dumps({k: wire.dump(v) for k, v in S.OTHERS.items()}, indent=1, sort_keys=False) + "\n"
        golden_check(self, "records.json", produced)

    def test_a_golden_line_decodes_to_its_sample(self):
        for name, (coll, table) in FAMILIES.items():
            lines = (GOLDEN / (name + ".jsonl")).read_text(encoding="utf-8").splitlines()
            for line, rec in zip(lines, coll.values(), strict=False):
                self.assertEqual(wire.load(table, json.loads(line)), rec)


class Refusals(unittest.TestCase):
    def wire(self, **kw):
        d = wire.dump(S.OUTCOME)
        d.update(kw)
        return d

    def test_a_foreign_version_is_stale(self):
        with self.assertRaises(StaleRecord) as cm:
            wire.load(type(S.OUTCOME), self.wire(v=1))
        self.assertEqual((cm.exception.found, cm.exception.want), (1, 2))
        with self.assertRaises(StaleRecord):
            wire.load(type(S.OUTCOME), {k: v for k, v in self.wire().items() if k != "v"})

    def test_an_unknown_key_is_refused(self):
        with self.assertRaisesRegex(msgspec.ValidationError, "extra"):
            wire.load(type(S.OUTCOME), self.wire(extra=1))

    def test_a_missing_required_key_is_named(self):
        d = self.wire()
        del d["bead"]
        with self.assertRaisesRegex(msgspec.ValidationError, "bead"):
            wire.load(type(S.OUTCOME), d)

    def test_types_are_not_coerced(self):
        for key, bad in (("minutes", "3"), ("rounds", 2.5), ("rounds", True), ("asked", 1), ("bead", 7), ("outcome", "nope")):
            with self.subTest(key), self.assertRaises(msgspec.ValidationError):
                wire.load(type(S.OUTCOME), self.wire(**{key: bad}))

    def test_an_int_is_a_float_but_a_float_is_not_an_int(self):
        self.assertEqual(wire.load(type(S.OUTCOME), self.wire(minutes=3)).minutes, 3.0)

    def test_the_path_names_the_nested_field(self):
        d = wire.dump(S.LOG["call_end"])
        d["tokens"]["out"] = "many"
        with self.assertRaises(msgspec.ValidationError) as cm:
            wire.load(log.CallEnd, d)
        self.assertIn("$.tokens.out", str(cm.exception))

    def test_a_wrong_kind_and_an_unknown_kind(self):
        d = wire.dump(S.LOG["warn"])
        with self.assertRaises(msgspec.ValidationError):
            wire.load(log.Note, d)
        with self.assertRaisesRegex(msgspec.ValidationError, "kind"):
            wire.load(log.EngineLog, dict(d, kind="nope"))
        with self.assertRaises(msgspec.ValidationError):
            wire.load(log.Note, [])

    def test_a_literal_takes_only_its_members(self):
        d = wire.dump(S.other(LoopCommand))
        d["action"] = "explode"
        with self.assertRaisesRegex(msgspec.ValidationError, "action"):
            wire.load(type(S.other(LoopCommand)), d)


class Wire(unittest.TestCase):
    def test_a_keyword_field_keeps_its_wire_name(self):
        self.assertEqual(wire.dump(trace.Tokens(in_=3, cached=2, out=1)), {"in": 3, "cached": 2, "out": 1})
        self.assertEqual(wire.load(trace.Tokens, {"in": 3}).in_, 3)

    def test_v_and_kind_come_first(self):
        self.assertEqual(list(wire.dump(S.LOG["lock"]))[:3], ["v", "kind", "t"])

    def test_a_tuple_is_written_as_an_array(self):
        self.assertEqual(json.dumps(wire.dump(S.LOCK)["route"]), '[10, "5"]')

    def test_an_optional_nested_record_is_null_or_a_dict(self):
        a = S.other(Ask)
        self.assertEqual(wire.dump(a)["answer"]["action"], "confirm")
        self.assertIsNone(wire.dump(a.replace(answer=None))["answer"])

    def test_nested_records_carry_no_version(self):
        d = wire.dump(S.other(Ask))
        self.assertEqual(d["v"], Ask.V)
        self.assertNotIn("v", d["answer"])

    def test_a_record_is_frozen(self):
        with self.assertRaises(AttributeError):
            S.OUTCOME.rounds = 9  # type: ignore[misc]


class Ids(unittest.TestCase):
    def test_a_run_id_is_opaque_and_sorts_by_time(self):
        a, b = ids.RunId.new(1793050200.0), ids.RunId.new(1793050200.5)
        later = ids.RunId.new(1793050300.0, entropy=bytes(10))
        self.assertEqual(ids.RunId.parse(str(a)), a)
        self.assertEqual((len(str(a)), a == b), (26, False))  # same second, different ids
        self.assertLess(str(b), str(later))
        self.assertFalse(hasattr(a, "bead"))

    def test_a_bad_run_id_or_bead_id(self):
        for text in ("nodate", "tl-7y6.3.1-20261027-002239", "", "01KBN6Z0M4R5E8YQ2T7C9W3XH", "01KBN6Z0M4R5E8YQ2T7C9W3XHU", "Z" * 26):
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
