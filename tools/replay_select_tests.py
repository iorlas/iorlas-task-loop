#!/usr/bin/env python3
"""Replay the shadow test selection over explicit worktree-local landing records; read-only and offline.

`python3 tools/replay_select_tests.py RECORDS.json [--json]` validates exactly 50 landings,
recomputes each selected set through tools/select_tests.py against that landing's recorded
full test inventory, and reports every landing's selected share and missed failures. The
median selected share is printed for the window. Any missed failure fails the replay.

There is no historical record file in this worktree yet; the schema and the missing input
are documented in docs/select-tests.md. This checker is not wired into the gate.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import select_tests  # noqa: E402

WINDOW = 50
SHA = re.compile(r"^[0-9a-fA-F]{7,40}$")


class RecordError(Exception):
    pass


def _string(where, value, name):
    if not isinstance(value, str) or not value.strip():
        raise RecordError("%s: %s must be a non-empty string" % (where, name))
    return value


def _strings(where, value, name, allow_empty=False):
    if not isinstance(value, list) or (not value and not allow_empty):
        raise RecordError("%s: %s must be a %slist of strings" % (
            where, name, "non-empty " if not allow_empty else ""))
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise RecordError("%s: %s must contain non-empty strings" % (where, name))
    return value


def _sha(where, value, name):
    value = _string(where, value, name)
    if not SHA.match(value):
        raise RecordError("%s: %s must be a hexadecimal commit sha" % (where, name))
    return value


def validate(landings):
    if not isinstance(landings, list):
        raise RecordError("records.landings must be a list")
    if len(landings) != WINDOW:
        raise RecordError("incomplete 50-landing window: got %d landings" % len(landings))
    ids, orders, landed_shas, valid = set(), set(), set(), []
    for index, item in enumerate(landings):
        where = "landing %d" % (index + 1)
        if not isinstance(item, dict):
            raise RecordError("%s must be an object" % where)
        for required in ("id", "order", "base", "landed", "paths", "inventory", "failures", "errors"):
            if required not in item:
                raise RecordError("%s is missing %s (a missing outcome is rejected)" % (where, required))
        landing_id = _string(where, item["id"], "id")
        if landing_id in ids:
            raise RecordError("%s: duplicate landing id %r" % (where, landing_id))
        ids.add(landing_id)
        order = item["order"]
        if isinstance(order, bool) or not isinstance(order, int) or order < 1:
            raise RecordError("%s: order must be a positive integer" % where)
        if order in orders:
            raise RecordError("%s: duplicate landing order %d" % (where, order))
        orders.add(order)
        base = _sha(where, item["base"], "base")
        landed = _sha(where, item["landed"], "landed")
        landed_key = landed.lower()
        if landed_key in landed_shas:
            raise RecordError("%s: duplicate landing %s" % (where, landed))
        landed_shas.add(landed_key)
        paths = _strings(where, item["paths"], "paths")
        inventory = _strings(where, item["inventory"], "inventory")
        if len(set(inventory)) != len(inventory):
            raise RecordError("%s: inventory contains duplicate test ids" % where)
        failures = _strings(where, item["failures"], "failures", allow_empty=True)
        errors = _strings(where, item["errors"], "errors", allow_empty=True)
        unknown = (set(failures) | set(errors)) - set(inventory)
        if unknown:
            raise RecordError("%s: outcomes not in the full inventory: %s" % (
                where, ", ".join(sorted(unknown))))
        valid.append({"id": landing_id, "order": order, "base": base, "landed": landed,
                      "paths": list(paths), "inventory": list(inventory),
                      "failures": list(failures), "errors": list(errors)})
    if sorted(orders) != list(range(1, WINDOW + 1)):
        raise RecordError("landing order must be exactly 1..%d without gaps" % WINDOW)
    return sorted(valid, key=lambda landing: landing["order"])


def replay(landings, features=None, edges=None):
    features = select_tests.feature_map() if features is None else features
    edges = select_tests.layer_edges() if edges is None else edges
    results = []
    for landing in landings:
        selected = set(select_tests.select_ids(landing["paths"], features=features, edges=edges,
                                               all_ids=landing["inventory"]))
        missed = sorted((set(landing["failures"]) | set(landing["errors"])) - selected)
        results.append({"id": landing["id"], "order": landing["order"], "selected": len(selected),
                        "inventory": len(landing["inventory"]),
                        "share": len(selected) / len(landing["inventory"]), "missed": missed})
    return {"window": len(results), "landings": results,
            "median_share": statistics.median(item["share"] for item in results),
            "ok": not any(item["missed"] for item in results)}


def worktree_records(path):
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        raise RecordError("records path is outside the worktree: %s" % path)
    return resolved


def main(argv=None):
    parser = argparse.ArgumentParser(description="Replay the shadow test selection over 50 landing records.")
    parser.add_argument("records", help="JSON file with a landings list")
    parser.add_argument("--json", action="store_true", help="print the replay result as JSON")
    args = parser.parse_args(argv)
    try:
        data = json.loads(worktree_records(args.records).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "landings" not in data:
            raise RecordError("records must be an object with a landings list")
        result = replay(validate(data["landings"]))
    except (OSError, ValueError, RecordError, select_tests.SelectionError) as error:
        print("cannot replay safely: %s" % error, file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        for item in result["landings"]:
            print("landing %02d %s: selected %d/%d (%.2f%%), missed %d" % (
                item["order"], item["id"], item["selected"], item["inventory"],
                item["share"] * 100, len(item["missed"])))
            for test_id in item["missed"]:
                print("  missed failure: " + test_id)
        print("median selected share: %.2f%%" % (result["median_share"] * 100))
        print("OK: no selected set missed a recorded failure" if result["ok"]
              else "FAIL: the selected set missed a recorded failure")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.dont_write_bytecode = True
    raise SystemExit(main())
