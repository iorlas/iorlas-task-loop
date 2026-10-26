#!/usr/bin/env python3
"""End-to-end check for `tl report lifecycle`: isolated config, repo and worktree-local inputs.

Run: python3 tests/lifecycle_scenario.py --evidence .task/<bead>/evidence
It writes the text and JSON reports plus a small facts file under --evidence and exits non-zero on a mismatch.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(Path(__file__).resolve().parent)); import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
import lifecycle  # noqa: E402
TL = ROOT / "skills" / "task-loop" / "tl.py"
T0 = datetime(2026, 10, 19, tzinfo=timezone.utc).timestamp()
H = 3600.0
SINCE = "2026-10-19T00:00:00Z"
UNTIL = "2026-10-27T00:00:00Z"


def git(repo, *args, t=None):
    env = dict(os.environ)
    if t is not None:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = "@%d +0000" % int(t)
    return subprocess.run(["git", "-C", str(repo)] + list(args), check=True, capture_output=True, text=True,
                          env=env).stdout.strip()


def commit(repo, msg, t, body=None, allow_empty=False):
    args = ["commit", "-qm", msg]
    if allow_empty:
        args.insert(1, "--allow-empty")
    if body:
        args += ["-m", body]
    git(repo, *args, t=t)
    return git(repo, "rev-parse", "HEAD")


def trace(bead, outcome, start_h, end_h, why="", sha="", sessions=(), because="first", run=None, worktree=""):
    started, ended = T0 + start_h * H, T0 + end_h * H
    stem = run or "%s-%d" % (bead, int(started))
    return {"v": 1, "run": stem, "bead": bead, "repo": "https://example.invalid/scenario.git",
            "worktree": worktree, "started": started, "ended": ended, "outcome": outcome, "why": why,
            "sha": sha, "started_because": because, "fingerprint": lifecycle.run_fingerprint(outcome, why),
            "sessions": list(sessions), "stats": {}}


def session(tin, cached):
    return {"node": "write", "role": "worker", "family": "openai", "tokens": {"in": tin, "cached": cached, "out": 1}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--evidence", default=".task/lifecycle-scenario/evidence")
    a = ap.parse_args()
    evidence = Path(a.evidence).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.TemporaryDirectory(prefix="tl-lifecycle-")
    try:
        home = Path(tmp.name)
        repo = home / "repo"
        repo.mkdir()
        wt = repo / ".slots" / "s1"
        wt.mkdir(parents=True)
        env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / "cfg"), APPDATA=str(home / "cfg"),
                   GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
                   PYTHONDONTWRITEBYTECODE="1")
        git(repo, "init", "-q", "-b", "main")
        (repo / "a.txt").write_text("a\n")
        git(repo, "add", "-A")
        commit(repo, "init", T0 - H)
        (repo / "a.txt").write_text("landed a\n")
        git(repo, "add", "-A")
        sha_a = commit(repo, "land a", T0 + 4.1 * H)
        commit(repo, "Revert \"land a\"", T0 + 5 * H, allow_empty=True,
               body="This reverts commit %s." % sha_a)
        (repo / "b.txt").write_text("landed b\n")
        git(repo, "add", "-A")
        sha_b = commit(repo, "land b", T0 + 3.1 * H)

        cfg = home / "cfg" / "task-loop"
        (cfg / "engine").mkdir(parents=True)
        (cfg / "asks").mkdir(parents=True)
        (cfg / "agent-runs" / "lanes").mkdir(parents=True)
        (home / ".claude" / "plugins" / "data" / "iorlas-delegate-iorlas-marketplace").mkdir(parents=True)
        # A pinned fake delegate makes the report read the real `status --json` adapter without a network call.
        delegate = home / ".claude" / "plugins" / "cache" / "market" / "iorlas-delegate" / "1.0.0" / "skills" / "delegate"
        delegate.mkdir(parents=True)
        (delegate / "route.py").write_text(
            "import json, sys\n"
            "if 'status' in sys.argv:\n"
            "    print(json.dumps({'lanes': {'OPENAI': {'name': 'OPENAI', 'out': False, 'usage': ["
            "{'window': '5h', 'used_pct': 30, 'resets_at': 0}]}}}))\n"
            "else:\n"
            "    print('{}')\n", encoding="utf-8")
        (cfg / "pinned.json").write_text(json.dumps({"delegate": "1.0.0"}), encoding="utf-8")

        runs = [
            trace("a", "failed", 1, 2, why="compile error in Assets/Player.cs", worktree=str(wt)),
            trace("a", "landed", 3, 4, sha=sha_a, because="retry", worktree=str(wt), sessions=[session(100, 40)]),
            trace("b", "landed", 2, 3, sha=sha_b, worktree=str(wt), sessions=[session(50, 10)]),
            trace("c", "failed", 5, 9, why="timeout: no answer", worktree=str(wt)),
        ]
        a_run = runs[1]["run"]
        c_run = runs[3]["run"]
        for r in runs:
            r["log"] = str(cfg / "engine" / (r["run"] + ".jsonl"))
        (cfg / "traces.jsonl").write_text("".join(json.dumps(r) + "\n" for r in runs))
        (cfg / "engine" / (a_run + ".jsonl")).write_text("".join(json.dumps(x) + "\n" for x in [
            {"t": T0 + 3.1 * H, "kind": "node", "id": 1, "step": "verify", "text": "verify"},
            {"t": T0 + 3.2 * H, "kind": "end", "id": 1, "step": "verify", "text": "verify 1: done"},
            {"t": T0 + 3.4 * H, "kind": "gate", "text": "gate: exit 0", "secs": 120, "cached": False},
        ]))
        (cfg / "engine" / (c_run + ".jsonl")).write_text(json.dumps(
            {"t": T0 + 8 * H, "kind": "kill", "node": "write", "why": "hung",
             "first_error_t": T0 + 7 * H, "kill_t": T0 + 8 * H}) + "\n")
        (cfg / "asks" / "a-1.json").write_text(json.dumps(
            {"id": "a-1", "bead": "a", "kind": "verify", "why": "verify: x", "t": T0 + 2 * H}))
        (cfg / "asks" / "b-1.json").write_text(json.dumps(
            {"id": "b-1", "bead": "b", "kind": "decision", "why": "owner decision needed", "t": T0 + 2.5 * H}))
        history = home / ".claude" / "plugins" / "data" / "iorlas-delegate-iorlas-marketplace" / "history.jsonl"
        history.write_text("".join(json.dumps(x) + "\n" for x in [
            {"ts": T0 + 1 * H, "lane": "OPENAI", "model": "gpt", "status": "failed",
             "reason": "compile error in Assets/A.cs"},
            {"ts": T0 + 2 * H, "lane": "OPENAI", "model": "gpt", "status": "failed",
             "reason": "compile error in Assets/B.cs"},
        ]))
        (cfg / "agent-runs" / "lanes" / "delegate.json").write_text(json.dumps({
            "v": 1, "producer": "delegate", "at": T0 + 2 * H,
            "lanes": [{"name": "OPENAI", "usage": [{"window": "5h", "used_pct": 30}]}]}))
        (cfg / "agent-runs" / "lanes" / "delegate-old.json").write_text(json.dumps({
            "v": 1, "producer": "delegate", "at": T0 + 1 * H,
            "lanes": [{"name": "OPENAI", "usage": [{"window": "5h", "used_pct": 10}]}]}))

        base = [sys.executable, str(TL), "report", "lifecycle", "--repo", str(repo),
                "--since", SINCE, "--until", UNTIL]
        js = subprocess.run(base + ["--json"], capture_output=True, text=True, env=env, cwd=str(repo))
        txt = subprocess.run(base, capture_output=True, text=True, env=env, cwd=str(repo))
        (evidence / "lifecycle-json.txt").write_text(js.stdout + js.stderr)
        (evidence / "lifecycle-text.txt").write_text(txt.stdout + txt.stderr)
        assert js.returncode == 0, "json report exit %d: %s" % (js.returncode, js.stderr[-2000:])
        assert txt.returncode == 0, "text report exit %d: %s" % (txt.returncode, txt.stderr[-2000:])
        d = json.loads(js.stdout)
        w = d["weeks"][0]
        facts = {
            "landed_beads": w["landed_beads"],
            "slot_min": w["slot_min"],
            "non_landing_share": w["non_landing_share"],
            "avoidable_asks": w["avoidable_asks"],
            "landed_run1": w["landed_run1"],
            "runs_per_landed": w["runs_per_landed"],
            "dead_time_retry": w["dead_time_min"]["retry"],
            "fingerprint_top": w["fingerprints"][0]["fingerprint"],
            "fingerprint_streak": w["fingerprint_streaks"][0]["max"],
            "slot_min_over_180": w["slot_min_over_180"],
            "verify_slot_min": w["verify_slot_min"],
            "hung_slot_min": w["hung_slot_min"],
            "release_gate_median_min": w["release_gate_median_min"],
            "uncached_input_per_landed": w["uncached_input_per_landed"],
            "reverts_per_100": w["reverts_per_100"],
            "quota_pct_per_landed": w["quota_pct_per_landed"],
            "quota_now": (d["quota"]["lanes"] or [{}])[0].get("used_pct") if d["quota"].get("available") else None,
        }
        expected = {
            "landed_beads": 2,
            "slot_min": 420.0,
            "non_landing_share": round(300 / 420, 4),
            "avoidable_asks": 1,
            "landed_run1": 1,
            "runs_per_landed": 2.0,
            "dead_time_retry": 60.0,
            "fingerprint_top": "compile error in <path>",
            "fingerprint_streak": 2,
            "slot_min_over_180": 240.0,
            "verify_slot_min": 6.0,
            "hung_slot_min": 60.0,
            "release_gate_median_min": 2.0,
            "uncached_input_per_landed": 50.0,
            "reverts_per_100": 50.0,
            "quota_pct_per_landed": 10.0,
            "quota_now": 30,
        }
        for k, want in expected.items():
            assert facts[k] == want, "%s: got %r, want %r" % (k, facts[k], want)
        assert "OPENAI 5h: 30.0%" in txt.stdout, "the status --json snapshot is missing from the text report"
        for line in ("landed beads/day", "slot-min per landed bead", "non-landing slot-min share",
                     "avoidable asks/week", "beads landed on run 1", "runs per landed bead",
                     "median dead time", "fingerprint top-5", "max consecutive same-fingerprint",
                     "slot-min in runs >180 min", "verify-stage slot-min", "hung-step slot-min",
                     "median release-gate minutes", "uncached input tokens per landed bead",
                     "reverts per 100 landings", "quota % consumed per landed bead"):
            assert line in txt.stdout, "missing text line: %s" % line
        (evidence / "lifecycle-facts.json").write_text(json.dumps({"facts": facts, "expected": expected}, indent=1))
        print("lifecycle scenario: OK  %s" % evidence)
        return 0
    finally:
        tmp.cleanup()


if __name__ == "__main__":
    sys.exit(main())
