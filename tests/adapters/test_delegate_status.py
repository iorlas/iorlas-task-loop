"""The contract tie (tl-3k5): the reader of delegate's `route.py status --json` against a real answer of delegate 0.51.0, and against
the installed delegate's own answer when there is one. A delegate release that renames or drops a key the reader needs fails here."""
import json
import sys
from pathlib import Path

import pytest

from tltestkit.case import Case

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402, F401

from tlkernel import wire  # noqa: E402
from tlkernel.delegate_status import snapshot_of  # noqa: E402
from tlkernel.snapshots import StatusSnapshot  # noqa: E402

REAL = json.loads((ROOT / "tests" / "fixtures" / "delegate_status_0.51.0_real.json").read_text())
FIXTURE_SCHEMA = json.loads((ROOT / "src/delegate/data/contract.json").read_text(
    encoding="utf-8"))["status_schema"]


def keys(j: dict, path: str = "") -> set[str]:
    """The key paths of an answer, lists of rows folded into one row's paths."""
    out = set()
    for k, v in j.items():
        out.add(path + k)
        if isinstance(v, dict) and k in ("cockpit", "unlock", "login", "next_worker"):
            out |= keys(v, path + k + ".")
        if isinstance(v, list) and v and isinstance(v[0], dict) and k == "lanes":
            out |= {p for row in v for p in keys(row, path + k + "[].")}
    return out


class Reader(Case):
    def test_a_real_answer_reads_into_a_snapshot_with_every_card_field(self):
        snap = snapshot_of(REAL)
        assert [ln.id for ln in snap.lanes] == [r["id"] for r in REAL["cockpit"]["lanes"]]
        for ln in snap.lanes:
            assert ln.label and ln.family and ln.kind and ln.model and ln.state and ln.emoji and ln.reason, ln
        assert snap.at == REAL["ts"]
        assert wire.load(StatusSnapshot, wire.dump(snap)) == snap

    def test_a_dropped_or_renamed_key_fails_the_reader(self):
        for drop in ("ts", "lanes", "cockpit"):
            with self.subTest(drop=drop), pytest.raises(ValueError):
                snapshot_of({k: v for k, v in REAL.items() if k != drop})
        rows = [{k: v for k, v in r.items() if k != "state"} for r in REAL["cockpit"]["lanes"]]
        with pytest.raises(ValueError):
            snapshot_of(dict(REAL, cockpit=dict(REAL["cockpit"], lanes=rows)))
        with pytest.raises(ValueError):
            snapshot_of(dict(REAL, lanes={k: dict(v, out="no") for k, v in REAL["lanes"].items()}))

    def test_the_fixture_has_every_key_the_reader_consumes(self):
        have = keys(REAL)
        for need in ("ts", "lanes", "cockpit", "needs_input", "cockpit.lanes[].id", "cockpit.lanes[].state", "cockpit.lanes[].windows",
                     "cockpit.lanes[].unlock", "cockpit.lanes[].warnings", "cockpit.lanes[].model", "cockpit.lanes[].label",
                     "cockpit.lanes[].family", "cockpit.lanes[].kind", "cockpit.lanes[].emoji", "cockpit.lanes[].reason"):
            assert need in have


def key_errors(data: object, schema: dict, path: str = "$") -> list[str]:
    """Where `data` has a key the schema does not name (additionalProperties false) or lacks a required one. Keys only: the repo has
    no instance validator, and the drift we fear is a renamed, dropped or added key, not a changed scalar type."""
    errs: list[str] = []
    t = schema.get("type")
    if isinstance(data, dict) and "object" in (t if isinstance(t, list) else [t]):
        props, extra = schema.get("properties"), schema.get("additionalProperties")
        if props is not None:
            errs += [f"{path}.{k} is required and missing" for k in schema.get("required", []) if k not in data]
            for k, v in data.items():
                if k in props:
                    errs += key_errors(v, props[k], f"{path}.{k}")
                elif extra is False:
                    errs.append(f"{path}.{k} is not in delegate's status_schema")
        elif isinstance(extra, dict):
            for k, v in data.items():
                errs += key_errors(v, extra, f"{path}.{k}")
    elif isinstance(data, list) and isinstance(schema.get("items"), dict):
        for v in data:
            errs += key_errors(v, schema["items"], path + "[]")
    return errs


class Schema(Case):
    """The library's status schema checks the fixture and the reader (delegate's own tests run its status for real)."""

    def test_the_real_fixture_has_exactly_the_keys_the_schema_names(self):
        assert key_errors(REAL, FIXTURE_SCHEMA) == []

    def test_the_schema_catches_a_dropped_and_an_added_key(self):
        schema = FIXTURE_SCHEMA
        assert key_errors({k: v for k, v in REAL.items() if k != "ts"}, schema)
        assert key_errors(dict(REAL, surprise=1), schema)

    def test_every_key_the_reader_consumes_is_one_the_schema_names(self):
        props = FIXTURE_SCHEMA["properties"]
        lane = props["cockpit"]["properties"]["lanes"]["items"]["properties"]
        old = props["lanes"]["additionalProperties"]["properties"]
        for k in ("ts", "lanes", "cockpit", "needs_input"):
            assert k in props
        for k in ("id", "label", "family", "kind", "model", "state", "emoji", "reason", "unlock", "windows", "warnings"):
            assert k in lane, "delegate's cockpit lane dropped a key snapshot_of reads"
        for k in ("out", "out_until", "reason", "notes"):
            assert k in old, "delegate's flat lane dropped a key snapshot_of reads"
