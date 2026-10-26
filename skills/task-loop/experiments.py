"""tl-7y6.1.2: typed experiment sidecars and the `tl experiments` report.

Council 49 §5: at most CAP experiments open at once, one metric each, typed, the revert written before the change is
kept, and an overdue experiment with no verdict is never silent. One JSON sidecar per bead under
<repo>/.task-loop/experiments/<bead-id>.json:

  {"hypothesis": "...",                      what the change claims
   "metric": "<a KPI id `tl report lifecycle` prints>",   one metric, from lifecycle.KPI_BY_ID
   "baseline": 0.14,                          a number the report's current value is compared against
   "check_when": {"date": "2026-11-02"}       due on that UTC day, or
                 {"runs": 5, "since": "2026-10-26"},   due once 5 runs of the bead started on/after the anchor day
   "keep_if": "...",                          the condition to keep the change
   "revert": "...",                           the revert, written before the experiment starts
   "labels": ["experiment"],                  "bet" is rejected: a bet is not an experiment
   "created": "2026-10-26",
   "verdict": null | {"kind": "keep"|"revert"|"extend", "date": "2026-11-03"}}

The verdict's typed-comment grammar arrives with s1-intake-parser; until then `tl experiments verdict BEAD KIND`
writes the sidecar field, and any verdict closes the experiment record. Pure helpers plus read-only adapters:
Python 3.8+, standard library only; this module must not import engine.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import lifecycle

CAP = 8  # council 49 §5: keep <= 8 experiments open
VERDICT_KINDS = ("keep", "revert", "extend")
FIELDS = ("hypothesis", "metric", "baseline", "check_when", "keep_if", "revert", "labels", "created", "verdict")
BEAD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ExperimentError(ValueError):
    """A sidecar that does not satisfy the contract; str(e) is the diagnostic (it names the valid choices)."""


# ---- validation -------------------------------------------------------------------------------------------------------

def valid_date(s):
    """True for a real YYYY-MM-DD date string."""
    if not isinstance(s, str) or not ISO_DATE.match(s):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def valid_bead_id(bead):
    return bool(bead) and bool(BEAD_ID.match(bead)) and ".." not in bead


def _text(data, field):
    v = data.get(field)
    if not isinstance(v, str) or not v.strip():
        raise ExperimentError("%s must be a non-empty string" % field)
    return v


def parse_sidecar(bead, data):
    """Validate one sidecar (bead is its file's stem); a normalized dict, or ExperimentError with the reason.

    Unknown fields, unknown metric ids, non-numeric baselines, malformed check_when and `bet` labels are all rejected;
    every message names the valid choices, so a wrong sidecar is a one-read fix.
    """
    if not valid_bead_id(bead):
        raise ExperimentError("%r is not a bead id a sidecar may be named after" % (bead or ""))
    if not isinstance(data, dict):
        raise ExperimentError("%s: the sidecar must be a JSON object" % bead)
    unknown = sorted(set(data) - set(FIELDS))
    if unknown:
        raise ExperimentError("%s: unknown field(s) %s; valid fields: %s" % (bead, ", ".join(unknown),
                                                                            ", ".join(FIELDS)))
    for field in ("hypothesis", "keep_if", "revert"):
        _text(data, field)
    metric = data.get("metric")
    if not isinstance(metric, str) or metric not in lifecycle.KPI_BY_ID:
        raise ExperimentError("%s: unknown metric id %r; valid ids (printed by `tl report lifecycle`): %s" % (
            bead, metric, ", ".join(k["id"] for k in lifecycle.KPIS)))
    baseline = data.get("baseline")
    if isinstance(baseline, bool) or not isinstance(baseline, (int, float)):
        raise ExperimentError("%s: baseline must be a number, not %r" % (bead, baseline))
    cw = data.get("check_when")
    if not isinstance(cw, dict):
        raise ExperimentError("%s: check_when must be an object {\"date\": D} or {\"runs\": N, \"since\": D}" % bead)
    has_date, has_runs = "date" in cw, "runs" in cw
    if has_date and has_runs:
        raise ExperimentError("%s: check_when has both a date and runs; pick one" % bead)
    if has_date:
        extra = sorted(set(cw) - {"date"})
        if extra or not valid_date(cw.get("date")):
            raise ExperimentError("%s: check_when date must be {\"date\": \"YYYY-MM-DD\"}" % bead)
    elif has_runs:
        extra = sorted(set(cw) - {"runs", "since"})
        runs, since = cw.get("runs"), cw.get("since")
        if extra or isinstance(runs, bool) or not isinstance(runs, int) or runs < 1:
            raise ExperimentError("%s: check_when runs must be {\"runs\": N, \"since\": \"YYYY-MM-DD\"} with N >= 1"
                                  % bead)
        if not valid_date(since):
            raise ExperimentError("%s: check_when needs an explicit start anchor: \"since\": \"YYYY-MM-DD\" (UTC)" % bead)
    else:
        raise ExperimentError("%s: check_when must be either {\"date\": \"YYYY-MM-DD\"} or "
                              "{\"runs\": N, \"since\": \"YYYY-MM-DD\"}" % bead)
    labels = data.get("labels", [])
    if not isinstance(labels, list) or any(not isinstance(x, str) or not x.strip() for x in labels):
        raise ExperimentError("%s: labels must be a list of non-empty strings" % bead)
    if any(x.strip().lower() == "bet" for x in labels):
        raise ExperimentError("%s: labelled bet: a bet is not an experiment (no revert pre-written); remove the bet "
                              "label or record it outside .task-loop/experiments" % bead)
    created = data.get("created")
    if created is not None and not valid_date(created):
        raise ExperimentError("%s: created must be \"YYYY-MM-DD\" or absent" % bead)
    verdict = data.get("verdict")
    if verdict is not None:
        if not isinstance(verdict, dict) or sorted(verdict) != ["date", "kind"]:
            raise ExperimentError("%s: verdict must be null or {\"kind\": K, \"date\": \"YYYY-MM-DD\"}" % bead)
        if verdict.get("kind") not in VERDICT_KINDS:
            raise ExperimentError("%s: verdict kind must be one of %s, not %r" % (
                bead, "|".join(VERDICT_KINDS), verdict.get("kind")))
        if not valid_date(verdict.get("date")):
            raise ExperimentError("%s: verdict date must be \"YYYY-MM-DD\"" % bead)
    return {"bead": bead, "hypothesis": data["hypothesis"], "metric": metric,
            "metric_label": lifecycle.KPI_BY_ID[metric]["label"], "baseline": baseline,
            "check_when": {"date": cw["date"]} if has_date else {"runs": cw["runs"], "since": cw["since"]},
            "keep_if": data["keep_if"], "revert": data["revert"], "labels": list(labels), "created": created,
            "verdict": dict(verdict) if verdict else None}


# ---- loading ---------------------------------------------------------------------------------------------------------

def sidecar_dir(repo):
    return Path(repo) / ".task-loop" / "experiments"


def load_experiments(repo):
    """Every *.json sidecar as {"open": [...], "closed": [...], "rejected": [{bead, why, path}]}, sorted by bead id.

    An experiment is open until it has a verdict; bead closure is never consulted (council 49 §5: the cap counts
    experiments, and only a verdict closes one).
    """
    out = {"open": [], "closed": [], "rejected": []}
    d = sidecar_dir(repo)
    for f in sorted(d.glob("*.json")) if d.is_dir() else []:
        bead = f.stem
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            out["rejected"].append({"bead": bead, "why": "%s is not valid JSON: %s" % (f.name, e), "path": str(f)})
            continue
        try:
            exp = parse_sidecar(bead, data)
        except ExperimentError as e:
            out["rejected"].append({"bead": bead, "why": str(e), "path": str(f)})
            continue
        exp["path"] = str(f)
        (out["closed"] if exp["verdict"] else out["open"]).append(exp)
    return out


# ---- due and verdict -------------------------------------------------------------------------------------------------

def day_start(date_s):
    """Epoch seconds of a YYYY-MM-DD day's 00:00 UTC."""
    return datetime.strptime(date_s, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()


def today(now=None):
    now = time.time() if now is None else now
    return datetime.fromtimestamp(float(now), timezone.utc).strftime("%Y-%m-%d")


def runs_since(traces, bead, since_t):
    """Runs of `bead` that started at/after `since_t`; a malformed row counts for nothing."""
    n = 0
    for r in traces or []:
        if not isinstance(r, dict) or r.get("bead") != bead:
            continue
        try:
            t = float(r.get("started"))
        except (TypeError, ValueError):
            continue
        if t >= since_t:
            n += 1
    return n


def due(exp, now, runs_done=None):
    """{"state": "waiting"|"due"|"overdue", ...} for one open experiment at `now` (epoch seconds, UTC days).

    A date is due on its own UTC day and overdue the day after; N runs are due when the Nth has started and overdue
    once a further run started with still no verdict.
    """
    cw = exp["check_when"]
    if "date" in cw:
        d = datetime.strptime(cw["date"], "%Y-%m-%d").date()
        t = datetime.fromtimestamp(float(now), timezone.utc).date()
        if t > d:
            return {"state": "overdue", "kind": "date", "date": cw["date"], "overdue_days": (t - d).days}
        if t == d:
            return {"state": "due", "kind": "date", "date": cw["date"]}
        return {"state": "waiting", "kind": "date", "date": cw["date"], "due_in_days": (d - t).days}
    n, done = cw["runs"], (runs_done or 0)
    base = {"kind": "runs", "runs": n, "since": cw["since"], "runs_done": done}
    if done > n:
        return dict(base, state="overdue", overdue_runs=done - n)
    if done == n:
        return dict(base, state="due")
    return dict(base, state="waiting")


def read_sidecar(repo, bead):
    """(data, path) of one bead's sidecar; ExperimentError when it is missing or invalid."""
    path = sidecar_dir(repo) / ("%s.json" % bead)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise ExperimentError("no experiment sidecar for %s under %s" % (bead, sidecar_dir(repo)))
    except ValueError as e:
        raise ExperimentError("%s is not valid JSON: %s" % (path.name, e))
    return parse_sidecar(bead, data), path


def write_verdict(repo, bead, kind, date_s=None, now=None):
    """Persist the verdict (the sidecar field, until s1-intake-parser's grammar lands) and return its record.

    A closed experiment is not re-verdicted: the record is append-only, so `extend` means a new sidecar.
    """
    if kind not in VERDICT_KINDS:
        raise ExperimentError("verdict kind must be one of %s, not %r" % ("|".join(VERDICT_KINDS), kind))
    date_s = date_s or today(now)
    if not valid_date(date_s):
        raise ExperimentError("verdict date must be \"YYYY-MM-DD\", not %r" % date_s)
    exp, path = read_sidecar(repo, bead)
    if exp["verdict"]:
        raise ExperimentError("%s already has a verdict (%s %s); a closed experiment is not re-verdicted" % (
            bead, exp["verdict"]["kind"], exp["verdict"]["date"]))
    data = json.loads(path.read_text(encoding="utf-8"))
    data["verdict"] = {"kind": kind, "date": date_s}
    tmp = path.with_name(path.name + ".%d.tmp" % os.getpid())
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return data["verdict"]


# ---- the report ------------------------------------------------------------------------------------------------------

def repo_traces(repo):
    """Adapter: the repo's trace rows (report.repo_traces); tests inject their own."""
    import report
    return report.repo_traces(repo)


def lifecycle_stats(repo, since, until):
    """Adapter: the lifecycle report over [since, until) as one window (report.lifecycle_stats, whole=True)."""
    import report
    return report.lifecycle_stats(repo, since, until, whole=True)


def experiments_report(repo, since, until, now=None, traces=None, stats=None):
    """The `tl experiments` report as data. `traces` and `stats` may be injected (tests); else the adapters above read
    the repo's own inputs. The current metric is the lifecycle report's value over [since, until) as one window; a
    measure that report cannot compute stays unavailable (None), never 0."""
    now = time.time() if now is None else now
    loaded = load_experiments(repo)
    week = None
    if stats is None:
        stats = lifecycle_stats(repo, since, until)
    weeks = stats.get("weeks") if isinstance(stats, dict) else None
    if weeks:
        week = weeks[0]
    if traces is None:
        traces = repo_traces(repo)
    open_rows = []
    for exp in loaded["open"]:
        row = dict(exp)
        cw = exp["check_when"]
        row.update(due(exp, now, runs_since(traces, exp["bead"], day_start(cw["since"])) if "runs" in cw else None))
        row["current"] = lifecycle.kpi_value(week, exp["metric"])
        row["current_unavailable"] = row["current"] is None
        row["no_verdict"] = row["state"] == "overdue"
        open_rows.append(row)
    open_rows.sort(key=lambda x: x["bead"])
    return {"v": 1, "repo": str(repo), "cap": CAP, "since": float(since), "until": float(until),
            "since_iso": lifecycle.utc_iso(since), "until_iso": lifecycle.utc_iso(until),
            "open": open_rows, "closed": sorted(loaded["closed"], key=lambda x: x["bead"]),
            "rejected": sorted(loaded["rejected"], key=lambda x: x["bead"]),
            "open_count": len(open_rows), "over_cap": len(open_rows) > CAP,
            "overdue_no_verdict": [x["bead"] for x in open_rows if x["no_verdict"]]}


def num(v):
    s = "%.4f" % float(v)
    return s.rstrip("0").rstrip(".") or "0"


def due_line(x):
    if x["kind"] == "date":
        if x["state"] == "overdue":
            return "check_when date %s (overdue %d d)" % (x["date"], x["overdue_days"])
        if x["state"] == "due":
            return "check_when date %s (due today)" % x["date"]
        return "check_when date %s (due in %d d)" % (x["date"], x["due_in_days"])
    if x["state"] == "overdue":
        return "check_when runs %d/%d since %s (overdue by %d run%s)" % (
            x["runs_done"], x["runs"], x["since"], x["overdue_runs"], "s" if x["overdue_runs"] != 1 else "")
    if x["state"] == "due":
        return "check_when runs %d/%d since %s (due: %d runs done)" % (x["runs_done"], x["runs"], x["since"], x["runs"])
    return "check_when runs %d/%d since %s (due after %d runs)" % (x["runs_done"], x["runs"], x["since"], x["runs"])


def print_experiments(r):
    print("tl experiments  %s  %d open (cap %d), %d closed, %d rejected  %s -> %s" % (
        Path(r["repo"]).name, r["open_count"], r["cap"], len(r["closed"]), len(r["rejected"]),
        r["since_iso"], r["until_iso"]))
    for x in r["open"]:
        print("  %-16s %-38s baseline %-10s current %s" % (
            x["bead"], x["metric"], num(x["baseline"]), num(x["current"]) if not x["current_unavailable"]
            else "unavailable"))
        print("    %s%s" % (due_line(x), "  NO VERDICT" if x["no_verdict"] else ""))
        print("    keep_if %s" % x["keep_if"])
        print("    revert %s" % x["revert"])
    for x in r["closed"]:
        print("  %-16s closed: verdict %s %s (%s)" % (x["bead"], x["verdict"]["kind"], x["verdict"]["date"],
                                                       x["metric"]))
    for x in r["rejected"]:
        print("  %-16s REJECTED: %s" % (x["bead"], x["why"]))
    if r["over_cap"]:
        print("WIP cap exceeded: %d open > %d; verdict or revert experiments before opening more" % (
            r["open_count"], r["cap"]))
    if r["overdue_no_verdict"]:
        print("overdue with NO VERDICT: %s" % ", ".join(r["overdue_no_verdict"]))


# ---- CLI -------------------------------------------------------------------------------------------------------------

def resolve_repo(repo=None):
    """The repo whose .task-loop/experiments is read: tl.repo_root, so a call from any subdirectory (or worktree) of
    the repository finds the same sidecars as one from its root; without a repo it is the current directory's."""
    import tl
    return tl.repo_root(repo)


def cmd_experiments(a):
    op = getattr(a, "op", None) or "list"
    if op == "verdict":
        return cmd_verdict(a)
    repo = resolve_repo(getattr(a, "repo", None))
    now = time.time()
    import report
    since = report.parse_time(a.since, now) if a.since else now - 7 * lifecycle.DAY
    until = report.parse_time(a.until, now, forward=True) if a.until else now
    r = experiments_report(repo, since, until, now=now)
    if a.json:
        print(json.dumps(r, indent=1, ensure_ascii=False))
    else:
        print_experiments(r)
    if op == "check":
        return 1 if (r["over_cap"] or r["rejected"]) else 0
    return 0


def cmd_verdict(a):
    bead, kind = getattr(a, "bead", None) or "", getattr(a, "kind", None) or ""
    if not valid_bead_id(bead):
        print("tl: verdict needs a bead id (usage: tl experiments verdict BEAD keep|revert|extend [--date D])",
              file=sys.stderr)
        return 2
    repo = resolve_repo(getattr(a, "repo", None))
    try:
        v = write_verdict(repo, bead, kind, getattr(a, "date", None))
    except ExperimentError as e:
        print("tl: %s" % e, file=sys.stderr)
        return 1
    print("VERDICT %s %s %s (%s)" % (bead, v["kind"], v["date"], sidecar_dir(repo)))
    return 0
