"""dash.py: the dashboard v2 view contract. The committed fixtures are what the builder makes, every one decodes strictly and
re-encodes byte for byte, every dash record appears in them, and every bead id they name exists in the snapshot."""
import dataclasses
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support import dash_fixtures as fx

from taskloop.contracts import codec, schema
from taskloop.contracts import dash as D

CLASS = {"snapshot.json": D.Snapshot, "bead/": D.BeadDetail, "live/": D.LivePage, "result.json": D.Result}


def cls_of(rel: str) -> type:
    return next(c for k, c in CLASS.items() if rel.startswith(k))


def records(obj, seen: set) -> None:
    if dataclasses.is_dataclass(obj):
        seen.add(type(obj))
        for f in dataclasses.fields(obj):
            records(getattr(obj, f.name), seen)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            records(v, seen)
    elif isinstance(obj, dict):
        for v in obj.values():
            records(v, seen)


class DashFixtures(unittest.TestCase):
    def setUp(self) -> None:
        self.built = fx.build()

    def test_committed_fixtures_are_what_the_builder_makes(self) -> None:
        if os.environ.get("UPDATE_GOLDEN"):
            fx.write()
        on_disk = {str(p.relative_to(fx.DIR)) for p in fx.DIR.rglob("*.json") if p.name != "mock-8b.json"}
        self.assertEqual(on_disk, set(self.built), "stale or missing fixture files; UPDATE_GOLDEN=1 rewrites them")
        for rel, obj in self.built.items():
            self.assertEqual((fx.DIR / rel).read_text(encoding="utf-8"), fx.encode(obj), f"{rel} drifted; UPDATE_GOLDEN=1")

    def test_every_fixture_decodes_strictly_and_round_trips(self) -> None:
        for rel in self.built:
            raw = json.loads((fx.DIR / rel).read_text(encoding="utf-8"))
            if rel == "writes.json":
                self.assertEqual(set(raw), set(D.WRITES))
                for verb, body in raw.items():
                    self.assertEqual(codec.to_json(codec.from_json(D.WRITES[verb], body)), body, verb)
                continue
            self.assertEqual(codec.to_json(codec.from_json(cls_of(rel), raw)), raw, rel)

    def test_unknown_keys_are_refused(self) -> None:
        raw = json.loads((fx.DIR / "snapshot.json").read_text(encoding="utf-8"))
        raw["beads"][0]["surprise"] = 1
        with self.assertRaises(codec.CodecError):
            codec.from_json(D.Snapshot, raw)

    def test_every_dash_record_is_in_a_fixture(self) -> None:
        seen: set = set()
        records(self.built, seen)
        mine = {c for c in vars(D).values() if isinstance(c, type) and dataclasses.is_dataclass(c) and c.__module__ == D.__name__}
        self.assertEqual({c.__name__ for c in mine - seen}, set())

    def test_every_record_has_a_schema(self) -> None:
        for c in (D.Snapshot, D.BeadDetail, D.LivePage, D.Result, *D.WRITES.values()):
            self.assertIn("properties", schema.of(c), c.__name__)

    def test_bead_ids_resolve(self) -> None:
        snap: D.Snapshot = self.built["snapshot.json"]
        ids = {b.id for b in snap.beads}
        named = [p.bead for p in snap.pieces] + [s.bead for s in snap.slots if s.bead] + [a.bead for a in snap.asks]
        # ledger rows may name beads that landed before midnight, which the snapshot no longer carries
        named += [n for b in snap.beads for n in b.needs] + [r.bead for r in snap.ledger if r.status != "answered"]
        self.assertEqual(set(named) - ids, set())
        slots = {s.id for s in snap.slots}
        self.assertEqual({p.slot for p in snap.pieces} - slots, set())
        for rel, d in self.built.items():
            if rel.startswith("bead/"):
                self.assertEqual(rel, f"bead/{d.card.id}.json")
                self.assertEqual(set(d.waits_for + d.unblocks) - ids, set(), rel)


if __name__ == "__main__":
    unittest.main()
