#!/usr/bin/env python3
"""Freeze the lifecycle baseline (tl-7y6.1.1): python3 tools/freeze_baseline.py [--repo PATH] [--out FILE].

Recomputes every `tl report lifecycle` metric on this checkout's engine over the study window, compares the study
figures, and writes docs/study/baselines-2026-10-25.json. Read-only on the repo and on ~/.config/task-loop. A number that
cannot be recomputed here is written "unavailable" with the reason, never estimated."""
import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "skills" / "task-loop"))
import report  # noqa: E402
import tl  # noqa: E402

TZ = timezone(timedelta(hours=3))  # the study's local time (Europe/Istanbul)
WINDOW = (datetime(2026, 10, 18, 0, 0, tzinfo=TZ), datetime(2026, 10, 25, 20, 7, 28, tzinfo=TZ))
SNAPSHOT_END = datetime(2026, 10, 25, 10, 0, tzinfo=TZ)  # where the study's lifesim-only figures were taken
CACHE_COMMIT = "5c05cccc"
DOCS_DESIGN = re.compile(r"^(docs|design)/|\.md$")
# the figures in the bead description (study 49 s3.1), the only ones this file may correct
STUDY = {
    "landed_beads": 131, "landed_beads_per_day": 19, "slot_min": 17541, "slot_min_per_landed_bead": 134,
    "non_landing_slot_min": 9774, "non_landing_slot_min_share": 0.56, "beads_landed_on_run_1": 59,
    "beads_touched": 164, "landed_run1_share_touched": 0.36, "avoidable_asks": 83, "asks": 94, "runs": 398,
    "runs_per_landed_bead": 3.0,
}
DEAD_TIME_HOURS = (2.8, 6.5)


def git(repo, *a):
    p = subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return p.stdout.strip() if p.returncode == 0 else ""


def totals(repo, since, until):
    r = report.lifecycle_stats(repo, since.timestamp(), until.timestamp(), whole=True)
    return r, r["weeks"][0] if r["weeks"] else {}


def corrections(w, snap):
    out = []
    for k, study in STUDY.items():
        got = w.get(k)
        if got is None:
            continue
        delta = (got - study) / study
        if abs(delta) <= 0.10:
            continue
        s = snap.get(k)
        why = ("window ends later than the study snapshot; at %s the value is %s (%+.1f%%)"
               % (SNAPSHOT_END.isoformat(), s, (s - study) / study * 100) if s is not None and abs((s - study) / study) <= 0.10
               else "differs at the study snapshot too: %s" % s)
        out.append({"metric": k, "study": study, "recomputed": got, "delta_pct": round(delta * 100, 1), "why": why})
    for name, m in sorted((w.get("median_dead_time_per_started_because") or {}).items()):
        if m is None:
            continue
        h = m / 60
        lo, hi = DEAD_TIME_HOURS
        if h < lo * 0.9 or h > hi * 1.1:
            out.append({"metric": "median_dead_time_h[%s]" % name, "study": "%s-%s h" % (lo, hi),
                        "recomputed": round(h, 2), "delta_pct": None,
                        "why": "the study gives one range for all start reasons; the engine measures it per started_because"})
    return out


def check_kind(item):
    return "hit" if item.get("cached") else "reused" if item.get("reused") else "skipped" if item.get("status") == "skipped" else "miss"


def cache_table(repo, traces):
    """Landed runs after CACHE_COMMIT whose whole landed diff is under docs/ or design/ (or *.md): their check rounds."""
    cut = git(repo, "show", "-s", "--format=%ct", CACHE_COMMIT)
    if not cut:
        return {"available": False, "reason": "commit %s is not in %s" % (CACHE_COMMIT, repo)}
    rows, hit, miss = [], 0, 0
    for r in sorted(traces, key=lambda x: x.get("started") or 0):
        if r.get("outcome") != "landed" or not r.get("sha") or (r.get("started") or 0) < int(cut):
            continue
        paths = git(repo, "show", "--name-only", "--format=", r["sha"]).splitlines()
        if not paths or not all(DOCS_DESIGN.search(p) for p in paths):
            continue
        rounds = []
        for rec in report.read_jsonl(r.get("log") or ""):
            if rec.get("kind") == "checks":
                kinds = [check_kind(i) for i in rec.get("items") or []]
                rounds.append({"round": rec.get("round"), "hit": kinds.count("hit"), "miss": kinds.count("miss"),
                               "reused": kinds.count("reused"), "skipped": kinds.count("skipped")})
        hit += sum(x["hit"] for x in rounds)
        miss += sum(x["miss"] for x in rounds)
        rows.append({"run": r.get("run"), "bead": r.get("bead"), "sha": r["sha"][:12], "changed_paths": paths[:20], "changed_path_count": len(paths),
                     "class": "design-only" if all(p.startswith("design/") for p in paths) else
                     "docs-only" if all(p.startswith("docs/") or p.endswith(".md") for p in paths) else "docs+design",
                     "rounds": rounds or "unavailable: engine log has no checks record"})
    return {"available": True, "after_commit": CACHE_COMMIT, "after_ts": int(cut), "runs": rows, "hit": hit, "miss": miss,
            "hit_rate": round(hit / (hit + miss), 3) if hit + miss else None,
            "paths_basis": "the landed commit's changed paths (per-round paths are not in pre-HEAD engine logs)",
            "reading": ("the docs/design-only rounds missed the check cache %d times and hit %d: S6 docs-only caching %s"
                        % (miss, hit, "is still needed" if miss > hit else "is not needed"))}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(Path("~/Workspaces/lifesim").expanduser()))
    ap.add_argument("--out", default=str(HERE.parent / "docs" / "study" / "baselines-2026-10-25.json"))
    a = ap.parse_args(argv)
    repo = tl.repo_root(a.repo)
    full, w = totals(repo, *WINDOW)
    _, snap = totals(repo, WINDOW[0], SNAPSHOT_END)
    engine_repo = HERE.parent
    unavailable = [
        {"metric": "median_release_gate_min", "reason": "gate records exist only in runs written by this engine; none are in the window"},
        {"metric": "hung_step_slot_min", "reason": "kill and vendor_error records exist only in runs written by this engine; the window predates them"},
        {"metric": "reverts_per_100_landings", "reason": "every landing's 7-day follow-up runs past the window end (%s landings censored)" % w.get("revert_censored")},
        {"metric": "quota_percent_per_landed_bead", "reason": "delegate keeps no per-bead quota history; a current `status --json` snapshot cannot measure a past week"},
        {"metric": "quota_codex_claude_85_92", "reason": "the study's 85% / 92% are past snapshots; not reconstructible from history.jsonl"},
    ]
    w = dict(w)
    w["hung_step_slot_min"] = "unavailable"  # the report's 0.0 means "no kill record"; none could exist before this engine
    doc = {
        "v": 1, "bead": "tl-7y6.1.1",
        "engine": {"version": json.loads((engine_repo / ".claude-plugin" / "plugin.json").read_text())["version"],
                   "source_sha": git(engine_repo, "rev-parse", "HEAD"), "branch": git(engine_repo, "branch", "--show-current"),
                   "dirty": bool(git(engine_repo, "status", "--porcelain", "--", "skills", "tools"))},
        "scope": {"repo": str(repo), "traces": str(tl.config_dir() / "traces.jsonl"),
                  "note": "lifesim only: the study's landed/slot-min figures are lifesim-only (docs/baseline-2026-10-25.md)"},
        "window": {"since": WINDOW[0].isoformat(), "until": WINDOW[1].isoformat(),
                   "since_iso": full["since_iso"], "until_iso": full["until_iso"],
                   "bucketing": "one bucket for the whole window (tl report lifecycle splits at UTC Mondays)"},
        "metrics": w,
        "snapshot_at_study": {"until": SNAPSHOT_END.isoformat(), "metrics": {k: snap.get(k) for k in STUDY}},
        "study_figures": STUDY,
        "corrections": corrections(w, snap),
        "unavailable": unavailable,
        "quota_snapshot": full.get("quota_snapshot"),
        "cache_hit_table": cache_table(repo, report.repo_traces(repo)),
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print("wrote %s: %d landed, %s slot-min, %d corrections" % (a.out, w.get("landed_beads", 0), w.get("slot_min"), len(doc["corrections"])))


if __name__ == "__main__":
    main()
