#!/usr/bin/env python3
"""tl-7y6.1.2 stage 2: load experiments from a bead snapshot into typed sidecars (one-off importer).

python3 tools/migrate_experiments.py --snapshot beads.json [--mappings overrides.json] [--repo R] [--json]

The snapshot is an explicit worktree-local JSON file — `bd list --json --all -n 0` output saved to a file, or
{"beads": [...]} — the importer never queries the tracker. Only a bead's `## Experiment` description block is
extracted; each becomes <repo>/.task-loop/experiments/<bead-id>.json (the stage-1 sidecar contract). --repo is
resolved as given (no git): a one-off writer writes exactly where it is told.

Nothing is written unless every record validates (all-or-nothing): bet labels, duplicate or path-escaping bead ids,
unknown metric names, invalid records, a conflicting different open sidecar, or a resulting open count above
experiments.CAP reject the whole import and leave the repo untouched. Existing verdicts are never overwritten (a
closed sidecar stands), and an identical rerun writes nothing. A prose baseline or check_when the block cannot
express faithfully (ranges, "after the asks settle", "next release") is never guessed and asks or releases are never
reinterpreted as runs: the typed value goes in the mappings file. Metric names are normalized through the shared
registry (lifecycle.KPIS: the id or its label). Provenance lives in the report (stdout, or --json): the sidecar's
own schema carries only the stage-1 fields, and the sidecar is named after its bead.

The eight experiments of this stage still wait on the complete source snapshot; the checked-in fixture
(tests/fixtures/experiments/migration-beads.json) is deliberately synthetic.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "skills" / "task-loop"))
import experiments  # noqa: E402
import lifecycle  # noqa: E402

BLOCK_FIELDS = ("hypothesis", "metric", "baseline", "check_when", "keep_if", "revert", "created")
MAPPING_FIELDS = ("metric", "baseline", "check_when", "created")
REQUIRED_IN_BLOCK = ("hypothesis", "metric", "baseline", "check_when", "keep_if", "revert")
HEADING = re.compile(r"^(#{1,6})\s+(\S.*?)\s*$")
FIELD = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)$")
INT = re.compile(r"^-?\d+$")


class MigrationError(ValueError):
    """One reason the import is refused; str(e) is the diagnostic (it names the valid choices)."""


# ---- the Experiment block ---------------------------------------------------------------------------------------------

def sections(description):
    """[(level, title, body_lines)] of a markdown-ish description; a heading of any level ends the section above."""
    out, cur = [], None
    for line in str(description or "").splitlines():
        m = HEADING.match(line)
        if m:
            if cur:
                out.append(cur)
            cur = [len(m.group(1)), m.group(2), []]
        elif cur is not None:
            cur[2].append(line)
    if cur:
        out.append(cur)
    return out


def experiment_block(bead):
    """The text under the bead's one `## Experiment` heading, or None when there is none.

    Only the exact heading (a trailing colon allowed) is an Experiment block: `## Experiments` or a passing mention in
    prose is not extracted. Two such blocks in one description are refused rather than merged.
    """
    found = None
    for _, title, lines in sections(bead.get("description") or ""):
        if title.strip().lower().rstrip(":").strip() == "experiment":
            if found is not None:
                raise MigrationError("%s: two Experiment blocks in one description; keep one" % bead.get("id"))
            found = "\n".join(lines).strip()
    return found


def parse_block(bead, text):
    """{field: text} for the block's `field: value` lines; an indented continuation line extends the value above it."""
    fields, last = {}, None
    for line in text.splitlines():
        if not line.strip():
            last = None
            continue
        m = FIELD.match(line)
        key = m.group(1).lower() if m else ""
        if key in BLOCK_FIELDS:
            if key in fields:
                raise MigrationError("%s: the Experiment block states %s twice" % (bead, key))
            fields[key] = m.group(2).strip()
            last = key
        elif m:
            raise MigrationError("%s: unknown field %r in the Experiment block; valid fields: %s"
                                 % (bead, m.group(1), ", ".join(BLOCK_FIELDS)))
        elif last:
            fields[last] += " " + line.strip()
        else:
            raise MigrationError("%s: the Experiment block has text before any field: %r" % (bead, line.strip()))
    return fields


# ---- typing the block's values ----------------------------------------------------------------------------------------

def metric_id(bead, name):
    """The registry id for metric text: the id itself or its label (case-insensitive), never a guess."""
    n = " ".join(str(name or "").split())
    low = n.lower()
    for k in lifecycle.KPIS:
        if n == k["id"] or low == k["label"].lower():
            return k["id"]
    raise MigrationError("%s: %r is not a KPI; valid ids (as `tl report lifecycle` prints them) or labels: %s" % (
        bead, n, "; ".join("%s (%s)" % (k["id"], k["label"]) for k in lifecycle.KPIS)))


def parse_baseline(bead, text):
    t = " ".join(str(text or "").split())
    if INT.match(t):
        return int(t)
    try:
        v = float(t)
    except ValueError:
        raise MigrationError('%s: baseline %r is prose, not a number; give {"%s": {"baseline": N}} in --mappings'
                             % (bead, t, bead))
    if v != v or v in (float("inf"), float("-inf")):
        raise MigrationError("%s: baseline %r is not a finite number" % (bead, t))
    return v


def parse_check_when(bead, text):
    """A typed check_when from block text: "2026-11-02" / "date 2026-11-02" or "5 runs since 2026-10-26".

    Anything else — a range, "after the asks settle", "next release" — is refused: asks and releases are never
    reinterpreted as runs; the typed value goes in the mappings file instead.
    """
    t = " ".join(str(text or "").split())
    m = re.fullmatch(r"(?:date\s+)?(\S+)", t, re.I)
    if m and experiments.valid_date(m.group(1)):
        return {"date": m.group(1)}
    m = re.fullmatch(r"(?:(\d+)\s+runs?|runs?\s+(\d+))\s+since\s+(\S+)", t, re.I)
    if m and int(m.group(1) or m.group(2)) >= 1 and experiments.valid_date(m.group(3)):
        return {"runs": int(m.group(1) or m.group(2)), "since": m.group(3)}
    raise MigrationError(
        '%s: check_when %r cannot be typed faithfully from prose (asks and releases are not runs, a range is not a '
        'count); give {"%s": {"check_when": {"date": "YYYY-MM-DD"}}} or {"runs": N, "since": "YYYY-MM-DD"} in '
        '--mappings' % (bead, t, bead))


def labels_of(bead):
    """The bead's own labels plus "experiment"; a bet label rejects the bead as an experiment."""
    labels = [str(x).strip() for x in (bead.get("labels") or []) if str(x).strip()]
    if any(x.lower() == "bet" for x in labels):
        raise MigrationError("%s: labelled bet: a bet is not an experiment (no revert pre-written); it is not "
                             "imported" % bead["id"])
    out = []
    for x in labels + ["experiment"]:
        if x not in out:
            out.append(x)
    return out


def created_from(bead):
    """The bead's own created_at day when the snapshot states one (explicit data, not a guess)."""
    d = str(bead.get("created_at") or "")[:10]
    return d if experiments.valid_date(d) else None


def build_record(bead, fields, mapping):
    """The sidecar dict for one bead, validated by the shared stage-1 contract (experiments.parse_sidecar)."""
    bid = bead["id"]
    if not experiments.valid_bead_id(bid):
        raise MigrationError("%r is not a bead id a sidecar may be named after (path-escaping ids are rejected)" % bid)
    for f in REQUIRED_IN_BLOCK:
        if f not in fields:
            raise MigrationError("%s: the Experiment block states no %s" % (bid, f))

    def typed(field, parse):
        if field in mapping:
            return mapping[field]
        return parse(fields[field])

    record = {"hypothesis": fields["hypothesis"],
              "metric": metric_id(bid, typed("metric", lambda t: t)),
              "baseline": typed("baseline", lambda t: parse_baseline(bid, t)),
              "check_when": typed("check_when", lambda t: parse_check_when(bid, t)),
              "keep_if": fields["keep_if"],
              "revert": fields["revert"],
              "labels": labels_of(bead),
              "verdict": None}
    created = mapping.get("created") or (fields["created"] if "created" in fields else created_from(bead))
    if created is not None:
        record["created"] = created
    try:
        experiments.parse_sidecar(bid, record)
    except experiments.ExperimentError as e:
        raise MigrationError(str(e))
    return record


# ---- inputs -----------------------------------------------------------------------------------------------------------

def load_json(path, what):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as e:
        raise MigrationError("cannot read the %s %s: %s" % (what, path, e))
    except ValueError as e:
        raise MigrationError("the %s %s is not valid JSON: %s" % (what, path, e))


def load_snapshot(path):
    """The snapshot's beads: a JSON list, or an object with a "beads" list (bd list --json output saved to a file)."""
    data = load_json(path, "bead snapshot")
    beads = data.get("beads") if isinstance(data, dict) else data
    if not isinstance(beads, list):
        raise MigrationError('the bead snapshot must be a JSON list of beads or {"beads": [...]}')
    seen, out = set(), []
    for b in beads:
        if not isinstance(b, dict) or not isinstance(b.get("id"), str) or not b["id"].strip():
            raise MigrationError("a snapshot entry is not a bead object with an id: %r" % (b,))
        if b["id"] in seen:
            raise MigrationError("%s appears twice in the snapshot" % b["id"])
        seen.add(b["id"])
        out.append(b)
    return out


def load_mappings(path):
    """{bead: {field: typed value}} for prose a block cannot type faithfully; empty when no file is given."""
    if not path:
        return {}
    data = load_json(path, "mappings file")
    if not isinstance(data, dict):
        raise MigrationError("the mappings file must be an object {bead-id: {field: value}}")
    for bead, m in data.items():
        if not isinstance(m, dict):
            raise MigrationError("the mapping for %s must be an object, not %r" % (bead, m))
        unknown = sorted(set(m) - set(MAPPING_FIELDS))
        if unknown:
            raise MigrationError("the mapping for %s has unknown field(s) %s; valid fields: %s (hypothesis, keep_if "
                                 "and revert come from the block, never from a mapping)" % (
                                     bead, ", ".join(unknown), ", ".join(MAPPING_FIELDS)))
    return data


# ---- the plan: validate everything, then decide what to write ---------------------------------------------------------

def plan(repo, beads, mappings, snapshot):
    """What the import would do: {"imported", "unchanged", "kept", "ignored", "open_after", "errors"}.

    Every rejection lands in "errors" (all of them, one run) and apply() is never called: a failed import leaves the
    repo untouched. A bead whose existing sidecar has a verdict is "kept" untouched; an identical record is
    "unchanged" (no rewrite); a different existing open sidecar is a conflict, never a clobber.
    """
    errors, ignored, blocks = [], [], {}
    for b in beads:
        try:
            block = experiment_block(b)
        except MigrationError as e:
            errors.append(str(e))
            continue
        if block is None:
            ignored.append({"bead": b["id"], "title": b.get("title", ""), "why": "no ## Experiment block"})
            continue
        blocks[b["id"]] = (b, block)
    ignored.sort(key=lambda x: x["bead"])
    for bid in sorted(set(mappings) - set(blocks)):
        errors.append("the mappings file names %s, which has no Experiment block in the snapshot" % bid)
    records = {}
    for bid, (b, block) in sorted(blocks.items()):
        try:
            records[bid] = {"bead": bid, "record": build_record(b, parse_block(bid, block), mappings.get(bid) or {}),
                            "source": {"bead": bid, "title": b.get("title", ""), "status": b.get("status", ""),
                                       "block": block, "snapshot": str(snapshot)}}
        except MigrationError as e:
            errors.append(str(e))
    existing = {}
    d = experiments.sidecar_dir(repo)
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        try:
            existing[f.stem] = {"data": json.loads(f.read_text(encoding="utf-8")), "path": str(f)}
        except (OSError, ValueError) as e:
            existing[f.stem] = {"error": "%s is not valid JSON: %s" % (f.name, e), "path": str(f)}
    open_other = {x["bead"] for x in experiments.load_experiments(str(repo))["open"]}
    imported, unchanged, kept = [], [], []
    for bid, rec in sorted(records.items()):
        ex = existing.get(bid)
        if ex is None:
            imported.append(rec)
            continue
        if "error" in ex:
            errors.append("%s: the existing sidecar is unreadable (%s); fix or remove it first" % (bid, ex["error"]))
            continue
        try:
            old = experiments.parse_sidecar(bid, ex["data"])
        except experiments.ExperimentError as e:
            errors.append("%s: the existing sidecar does not satisfy the contract (%s); fix or remove it first"
                          % (bid, e))
            continue
        if old["verdict"]:
            kept.append(dict(rec, verdict=old["verdict"]))
            continue
        if old == experiments.parse_sidecar(bid, rec["record"]):
            unchanged.append(rec)
            continue
        errors.append("%s: a different open sidecar already exists; remove it or reconcile the Experiment block "
                      "first (it was not overwritten)" % bid)
    open_after = len(open_other - set(records)) + len(imported) + len(unchanged)
    if open_after > experiments.CAP:
        errors.append("the import would leave %d experiments open (cap %d); verdict or revert some first" % (
            open_after, experiments.CAP))
    return {"repo": str(repo), "snapshot": str(snapshot), "imported": imported, "unchanged": unchanged, "kept": kept,
            "ignored": ignored, "open_after": open_after, "cap": experiments.CAP, "errors": errors}


def apply(repo, imported):
    """Write the new sidecars atomically; this runs only after plan() reported no errors."""
    d = experiments.sidecar_dir(repo)
    d.mkdir(parents=True, exist_ok=True)
    written = []
    for x in imported:
        path = d / ("%s.json" % x["bead"])
        tmp = path.with_name("%s.%d.tmp" % (path.name, os.getpid()))
        tmp.write_text(json.dumps(x["record"], indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(str(tmp), str(path))
        written.append(str(path))
    return written


# ---- CLI --------------------------------------------------------------------------------------------------------------

def when_of(record):
    cw = record["check_when"]
    if "date" in cw:
        return cw["date"]
    return "%d run%s since %s" % (cw["runs"], "" if cw["runs"] == 1 else "s", cw["since"])


def line_of(what, x):
    r = x["record"]
    base = "%s %-14s %-38s baseline %-10s check_when %s" % (
        what, x["bead"], r["metric"], experiments.num(r["baseline"]), when_of(r))
    if what == "kept":
        return "%s (verdict %s %s: the existing sidecar stands)" % (base, x["verdict"]["kind"], x["verdict"]["date"])
    return base


def main(argv=None):
    ap = argparse.ArgumentParser(description="Load Experiment blocks from a bead snapshot into typed sidecars "
                                             "(tl-7y6.1.2; never queries the tracker)")
    ap.add_argument("--snapshot", required=True, metavar="PATH",
                    help="a worktree-local bead JSON snapshot: `bd list --json --all -n 0` output saved to a file, "
                         'or {"beads": [...]}')
    ap.add_argument("--mappings", metavar="PATH",
                    help='typed overrides for prose a block cannot type faithfully: {"bead": {"metric", "baseline", '
                         '"check_when", "created"}}')
    ap.add_argument("--repo", default=".", metavar="R", help="the repository whose .task-loop/experiments is written "
                                                             "(resolved as given; default .)")
    ap.add_argument("--json", action="store_true", help="print the import report as JSON")
    a = ap.parse_args(argv)
    try:
        beads = load_snapshot(a.snapshot)
        mappings = load_mappings(a.mappings)
    except MigrationError as e:
        print("migrate: %s" % e, file=sys.stderr)
        return 2
    repo = str(Path(a.repo).resolve())
    p = plan(repo, beads, mappings, a.snapshot)
    if p["errors"]:
        for e in p["errors"]:
            print("migrate: %s" % e, file=sys.stderr)
        print("migrate: nothing was written (%d open would remain, cap %d); fix the snapshot or the mappings and "
              "rerun" % (p["open_after"], p["cap"]), file=sys.stderr)
        return 1
    apply(repo, p["imported"])
    if a.json:
        print(json.dumps(p, indent=1, ensure_ascii=False))
        return 0
    for x in p["imported"]:
        print(line_of("imported", x))
    for x in p["unchanged"]:
        print(line_of("unchanged", x))
    for x in p["kept"]:
        print(line_of("kept", x))
    for x in p["ignored"]:
        print("ignored %-14s %s" % (x["bead"], x["why"]))
    print("imported %d, unchanged %d, kept %d, ignored %d; open now %d (cap %d)" % (
        len(p["imported"]), len(p["unchanged"]), len(p["kept"]), len(p["ignored"]), p["open_after"], p["cap"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
