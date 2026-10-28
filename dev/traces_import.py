#!/usr/bin/env python3
"""One-shot importer: traces.jsonl v1 rows into RunTrace v2 (the only migration code of the contracts rewrite).

    python3 dev/traces_import.py --out FILE [--src ~/.config/task-loop/traces.jsonl] [--force]

Reads the v1 file, writes one RunTrace v2 line per row to --out (never to the source), and prints a summary: rows read, rows
written, rows refused (with why), and the v1 keys that have no place in v2. Run once, then put the output where the v2 reader
looks. Every field a v1 row carries that v2 has a place for is carried byte for byte.
"""
import argparse
import collections
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from taskloop.contracts import codec, ids, paths, trace  # noqa: E402
from taskloop.contracts.enums import Outcome  # noqa: E402

TOP_DROPPED = {"no_sandbox"}          # the 0.6 name of `host`
CALL_DROPPED = {"context", "no_sandbox"}  # the worker's env key names and instruction files; v2 keeps a calls's context_k only
RENAMED = {"repo": "repo_url", "delegate": "delegate_path"}


def _fields(cls: type) -> set[str]:
    return {p.attr for p in codec.plan(cls)}


def _pick(cls: type, row: dict[str, Any], rename: dict[str, str] | None = None) -> dict[str, Any]:
    want = _fields(cls)
    return {(rename or {}).get(k, k): v for k, v in row.items() if (rename or {}).get(k, k) in want and v is not None}


def call_of(s: dict[str, Any]) -> trace.AiCall:
    kw = _pick(trace.AiCall, s)
    kw["tokens"] = codec.from_json(trace.Tokens, s["tokens"]) if s.get("tokens") else trace.Tokens()
    kw["denied"] = [trace.Denied(tool=d["tool"], input=d.get("input") or {}) for d in s.get("denied") or []]
    return trace.AiCall(**kw)


def reflection_of(r: dict[str, Any] | None) -> trace.Reflection | None:
    if not r:
        return None
    return trace.Reflection(went_well=list(r.get("went_well") or []), wasted=list(r.get("wasted") or []),
                            change=list(r.get("change") or []),
                            went_badly=[trace.WentBadly(**{k: str(w.get(k) or "") for k in ("what", "cause", "session", "evidence")})
                                        for w in r.get("went_badly") or []])


def import_row(row: dict[str, Any]) -> trace.RunTrace:
    """One v1 row as a RunTrace. Raises ValueError (CodecError included) when the row cannot be one."""
    if row.get("v") != 1:
        raise ValueError("not a v1 row: v=%r" % (row.get("v"),))
    kw = _pick(trace.RunTrace, row, RENAMED)
    for k in ("run", "outcome", "cost", "stats", "sessions", "verified", "write_rounds", "strays", "reflection", "lane_notes",
              "faults", "why_code"):
        kw.pop(k, None)
    return trace.RunTrace(
        run=ids.RunId.parse(row["run"]), outcome=Outcome(row["outcome"]),
        cost=trace.Cost(usd=float(row.get("cost") or 0.0)),
        stats=trace.Stats(**_pick(trace.Stats, row.get("stats") or {})),
        sessions=[call_of(s) for s in row.get("sessions") or []],
        verified=[trace.Verified(**{k: str(v.get(k) or "") for k in ("what", "kind", "verdict", "evidence", "why")})
                  for v in row.get("verified") or []],
        write_rounds=[trace.WriteRound(**_pick(trace.WriteRound, w)) for w in row.get("write_rounds") or []],
        strays=[str(x) for x in row.get("strays") or []], reflection=reflection_of(row.get("reflection")),
        lane_notes=[str(x) for x in row.get("lane_notes") or []], **kw)


def dropped_keys(row: dict[str, Any]) -> list[str]:
    """The v1 keys of this row (top level `k`, session level `session.k`) that v2 does not carry."""
    out = [k for k in row if k in TOP_DROPPED]
    for s in row.get("sessions") or []:
        out += ["session.%s" % k for k in s if k in CALL_DROPPED]
    return out


def read_v1(src: Path) -> tuple[list[dict[str, Any]], list[str]]:
    rows, bad = [], []
    for n, line in enumerate(src.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            bad.append("line %d: not JSON" % n)
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            bad.append("line %d: not an object" % n)
    return rows, bad


def import_file(src: Path, out: Path, force: bool = False) -> dict[str, Any]:
    """Convert `src` into `out` (a new file, atomically); returns the summary."""
    if out.resolve() == src.resolve():
        raise SystemExit("--out is the source file; the importer never writes its source")
    if out.exists() and not force:
        raise SystemExit("%s exists; --force replaces it" % out)
    rows, refused = read_v1(src)
    lines, dropped = [], collections.Counter()
    for row in rows:
        try:
            rec = import_row(row)
        except (ValueError, KeyError, TypeError) as e:
            refused.append("%s: %s" % (row.get("run", "?"), e))
            continue
        dropped.update(dropped_keys(row))
        lines.append(json.dumps(codec.to_json(rec), ensure_ascii=False) + "\n")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text("".join(lines), encoding="utf-8")
    os.replace(tmp, out)
    return {"read": len(rows), "written": len(lines), "refused": refused, "dropped_keys": dict(sorted(dropped.items()))}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", type=Path, default=paths.ConfigDir().traces())
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    summary = import_file(a.src, a.out, a.force)
    print(json.dumps(summary, indent=1))
    return 1 if summary["refused"] else 0


if __name__ == "__main__":
    sys.exit(main())
