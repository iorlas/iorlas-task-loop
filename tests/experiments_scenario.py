#!/usr/bin/env python3
"""End-to-end checks for `tl experiments` (tl-7y6.1.2): isolated config, repo and worktree-local inputs.

Run: python3 tests/experiments_scenario.py --case {schema,report,verdict,wip} --evidence .task/<bead>/evidence/<case>
Each case writes its CLI outputs plus a facts file under --evidence and exits non-zero on a mismatch. The repo, the
traces, the asks, the delegate history and the quota readings are all built here; no tracker, no network, no user
config is read, and no git command runs: git is a stub on PATH that answers for the fixture repo (from any of its
subdirectories, as real git would) and fails every other call, so tl.repo_root resolves the fixture repo and nothing
of this worktree's real repository is ever read.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
import lifecycle  # noqa: E402

TL = ROOT / "skills" / "task-loop" / "tl.py"
T0 = datetime(2026, 10, 19, tzinfo=timezone.utc).timestamp()  # Monday 00:00 UTC
H = 3600.0
SINCE, UNTIL = "2026-10-19T00:00:00Z", "2026-10-27T00:00:00Z"
EMPTY_SINCE, EMPTY_UNTIL = "2026-10-27T00:00:00Z", "2026-10-28T00:00:00Z"
NOW = datetime(2026, 10, 26, 12, tzinfo=timezone.utc).timestamp()
SHA_A, SHA_B = "a" * 40, "b" * 40  # fixture shas: the landing traces' recorded lands


def mocked_git(home, repo):
    """The mocked external git adapter: a stub on PATH. Asked for the fixture repo's common dir from anywhere inside
    it, it answers with that repo (as real git does from every subdirectory of a repository); every other call fails,
    as git does outside any repository. No real git command runs."""
    stub = ("#!/usr/bin/env python3\n"
            "import os, sys\n"
            "args = sys.argv[1:]\n"
            "d = os.path.abspath(args[1]) if args[:1] == ['-C'] else os.getcwd()\n"
            "if 'rev-parse' in args and '--git-common-dir' in args and (d + os.sep).startswith(%r + os.sep):\n"
            "    print(os.path.join(%r, '.git'))\n"
            "    sys.exit(0)\n"
            "sys.stderr.write('fatal: not a git repository (the mocked adapter)\\\\n')\n"
            "sys.exit(128)\n" % (str(repo), str(repo)))
    bin_ = home / "bin"
    bin_.mkdir()
    f = bin_ / "git"
    f.write_text(stub, encoding="utf-8")
    f.chmod(0o755)
    return bin_


def trace(bead, outcome, start_h, end_h, why="", sha="", sessions=(), because="first", run=None, worktree=""):
    started, ended = T0 + start_h * H, T0 + end_h * H
    stem = run or "%s-%d" % (bead, int(started))
    return {"v": 1, "run": stem, "bead": bead, "repo": "https://example.invalid/scenario.git",
            "worktree": worktree, "started": started, "ended": ended, "outcome": outcome, "why": why,
            "sha": sha, "started_because": because, "fingerprint": lifecycle.run_fingerprint(outcome, why),
            "sessions": list(sessions), "stats": {}}


def day(offset):
    """A UTC date `offset` days from today: due states must hold whenever the engine reruns this scenario."""
    return (datetime.now(timezone.utc) + timedelta(days=offset)).strftime("%Y-%m-%d")


class World:
    """An isolated home (config, delegate pin, history) and a plain fixture repo whose git is the mocked stub."""

    def __init__(self, home):
        self.home = home
        self.repo = home / "repo"
        self.repo.mkdir()
        (self.repo / ".git").mkdir()  # the fixture's repo marker: no git command ever populates it
        self.sub = self.repo / "sub"
        self.sub.mkdir()  # a subdirectory of the repo, to dispatch the CLI from
        wt = self.repo / ".slots" / "s1"
        wt.mkdir(parents=True)
        self.env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / "cfg"), APPDATA=str(home / "cfg"),
                        PATH="%s%s%s" % (mocked_git(home, self.repo), os.pathsep, os.environ.get("PATH", "")),
                        PYTHONDONTWRITEBYTECODE="1")
        sha_a, sha_b = SHA_A, SHA_B

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
            trace("a", "landed", 3, 4, sha=sha_a, because="retry", worktree=str(wt),
                  sessions=[{"node": "write", "role": "worker", "family": "openai",
                             "tokens": {"in": 100, "cached": 40, "out": 1}}]),
            trace("b", "landed", 2, 3, sha=sha_b, worktree=str(wt),
                  sessions=[{"node": "write", "role": "worker", "family": "openai",
                             "tokens": {"in": 50, "cached": 10, "out": 1}}]),
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
        self.exp = self.repo / ".task-loop" / "experiments"
        self.exp.mkdir(parents=True)

    def sidecar(self, bead, **kw):
        d = {"hypothesis": "smaller slices raise the beads landed per day", "metric": "landed_beads_per_day",
             "baseline": 0.1, "check_when": {"date": day(3)},
             "keep_if": "landed beads/day >= 0.14 for a whole week",
             "revert": "git revert the slice commits and re-freeze the baseline",
             "labels": ["experiment"], "created": "2026-10-26"}
        d.update(kw)
        (self.exp / ("%s.json" % bead)).write_text(json.dumps(d, indent=1) + "\n", encoding="utf-8")

    def run(self, *args, **kw):
        kw.setdefault("cwd", str(self.repo))  # the CLI as a person in that directory runs it
        return subprocess.run([sys.executable, str(TL)] + list(args), capture_output=True, text=True,
                              env=self.env, **kw)


def save(evidence, name, r):
    (evidence / name).write_text((r.stdout or "") + (r.stderr or ""), encoding="utf-8")
    return r


def case_schema(w, evidence):
    w.sidecar("a", check_when={"date": day(3)})
    w.sidecar("b", metric="runs_per_landed", baseline=2.0, check_when={"runs": 2, "since": "2026-10-19"})
    w.sidecar("m1", metric="landed_beads")                       # unknown metric id
    w.sidecar("m2", baseline="0.1")                              # a string baseline
    w.sidecar("m3", check_when={})                               # neither a date nor runs
    w.sidecar("m4", labels=["experiment", "bet"])                # a bet is not an experiment
    (w.exp / "m5.json").write_text("{not json", encoding="utf-8")
    js = save(evidence, "schema-json.txt", w.run("experiments", "--json"))
    txt = save(evidence, "schema-text.txt", w.run("experiments"))
    assert js.returncode == 0 and txt.returncode == 0, (js.returncode, txt.returncode, txt.stderr[-2000:])
    d = json.loads(js.stdout)
    assert d["open_count"] == 2 and len(d["rejected"]) == 5, (d["open_count"], len(d["rejected"]))
    why = " ".join(x["why"] for x in d["rejected"])
    for k in lifecycle.KPIS:  # the unknown-metric diagnostic names every valid id
        assert k["id"] in why, k["id"]
    assert "valid ids" in why
    beads = {x["bead"] for x in d["rejected"]}
    assert beads == {"m1", "m2", "m3", "m4", "m5"}, beads
    assert any("bet" in x["why"] for x in d["rejected"])
    for line in ("REJECTED", "baseline must be a number", "check_when", "not valid JSON"):
        assert line in txt.stdout, line
    # the ids the sidecars may use are the ones `tl report lifecycle` prints
    life = save(evidence, "schema-lifecycle-text.txt",
                w.run("report", "lifecycle", "--since", SINCE, "--until", UNTIL))
    assert life.returncode == 0, life.stderr[-2000:]
    for k in lifecycle.KPIS:
        assert "[%s]" % k["id"] in life.stdout, k["id"]
    facts = {"open": [x["bead"] for x in d["open"]], "rejected": sorted(beads), "valid_ids": [k["id"] for k in
                                                                                              lifecycle.KPIS]}
    (evidence / "schema-facts.json").write_text(json.dumps(facts, indent=1), encoding="utf-8")
    return facts


def case_report(w, evidence):
    w.sidecar("a", baseline=0.1, check_when={"date": day(3)})                     # waiting, current 0.25
    w.sidecar("b", metric="slot_min_per_landed", baseline=200.0,
              check_when={"runs": 2, "since": "2026-10-19"})                      # waiting 1/2, current 210.0
    w.sidecar("c", metric="avoidable_asks_per_week", baseline=0,
              check_when={"runs": 1, "since": "2026-10-19"})                      # due (1/1), current 1
    w.sidecar("d", metric="median_release_gate_minutes", baseline=3.0,
              check_when={"date": day(-2)})                                       # overdue: NO VERDICT
    w.sidecar("e", metric="quota_percent_per_landed_bead", baseline=5.0, check_when={"date": day(10)})
    w.sidecar("f", metric="uncached_input_tokens_per_landed_bead", baseline=100,
              check_when={"runs": 3, "since": "2026-10-19"})                      # 0/3, current 50.0
    w.sidecar("g", verdict={"kind": "keep", "date": "2026-10-20"})                # closed: never listed open
    base = ["experiments", "--repo", str(w.repo), "--since", SINCE, "--until", UNTIL]
    js = save(evidence, "report-json.txt", w.run(*base, "--json"))
    txt = save(evidence, "report-text.txt", w.run(*base))
    # from a subdirectory of the repo, with no --repo: tl.repo_root must resolve the repo, not the subdirectory
    # (the bug: 0 open, check passing, overdue NO VERDICT silent)
    sub = save(evidence, "report-from-subdir.txt",
               w.run("experiments", "--since", SINCE, "--until", UNTIL, cwd=str(w.sub)))
    sub_js = save(evidence, "report-from-subdir-json.txt",
                  w.run("experiments", "--since", SINCE, "--until", UNTIL, "--json", cwd=str(w.sub)))
    empty = save(evidence, "report-empty-window.txt",
                 w.run("experiments", "--repo", str(w.repo), "--since", EMPTY_SINCE, "--until", EMPTY_UNTIL))
    empty_js = save(evidence, "report-empty-window-json.txt",
                    w.run("experiments", "--repo", str(w.repo), "--since", EMPTY_SINCE, "--until", EMPTY_UNTIL,
                          "--json"))
    assert all(r.returncode == 0 for r in (js, txt, sub, sub_js, empty, empty_js)), [
        r.stderr[-800:] for r in (js, txt, sub, sub_js, empty, empty_js)]
    d = json.loads(js.stdout)
    sd = json.loads(sub_js.stdout)
    assert sd["open_count"] == 6 and sd["overdue_no_verdict"] == ["d"], (sd["open_count"],
                                                                         sd["overdue_no_verdict"])
    assert "6 open (cap 8)" in sub.stdout and "NO VERDICT" in sub.stdout, sub.stdout[-800:]
    by = {x["bead"]: x for x in d["open"]}
    assert d["open_count"] == 6 and len(d["closed"]) == 1 and not d["rejected"]
    currents = {b: x["current"] for b, x in by.items()}
    assert currents == {"a": 0.25, "b": 210.0, "c": 1, "d": 2.0, "e": 10.0, "f": 50.0}, currents
    assert by["a"]["state"] == "waiting" and by["a"]["due_in_days"] == 3
    assert (by["b"]["state"], by["b"]["runs_done"]) == ("waiting", 1)
    assert by["c"]["state"] == "due"
    assert by["d"]["state"] == "overdue" and by["d"]["no_verdict"]
    assert d["overdue_no_verdict"] == ["d"]
    assert d["closed"][0]["verdict"] == {"kind": "keep", "date": "2026-10-20"}
    for line in ("baseline 0.1", "current 0.25", "NO VERDICT", "check_when runs 1/2 since 2026-10-19",
                 "check_when runs 1/1 since 2026-10-19 (due", "overdue 2 d", "closed: verdict keep 2026-10-20"):
        assert line in txt.stdout, line
    e = json.loads(empty_js.stdout)  # a window with no landings: the per-landed measures stay unavailable, never 0
    eb = {x["bead"]: x for x in e["open"]}["b"]
    assert eb["current"] is None and eb["current_unavailable"], eb
    assert "unavailable" in empty.stdout
    facts = {"currents": currents, "overdue_no_verdict": d["overdue_no_verdict"],
             "from_subdir_open_count": sd["open_count"], "from_subdir_overdue": sd["overdue_no_verdict"],
             "empty_window_current_b": eb["current"], "states": {b: x["state"] for b, x in by.items()}}
    (evidence / "report-facts.json").write_text(json.dumps({"facts": facts}, indent=1), encoding="utf-8")
    return facts


def case_verdict(w, evidence):
    w.sidecar("k1")
    w.sidecar("k2", metric="avoidable_asks_per_week", baseline=0)
    w.sidecar("k3", metric="slot_min_per_landed", baseline=200.0)
    outs = []
    for bead, kind, cwd in (("k1", "keep", None), ("k2", "revert", None), ("k3", "extend", str(w.sub))):
        r = save(evidence, "verdict-%s.txt" % kind, w.run("experiments", "verdict", bead, kind, "--date",
                                                          "2026-10-26", **({"cwd": cwd} if cwd else {})))
        outs.append((bead, kind, r.returncode))
        assert r.returncode == 0, (bead, kind, r.stderr[-1500:])
        side = json.loads((w.exp / ("%s.json" % bead)).read_text(encoding="utf-8"))
        assert side["verdict"] == {"kind": kind, "date": "2026-10-26"}, side.get("verdict")
    js = save(evidence, "verdict-list-json.txt", w.run("experiments", "--json"))
    d = json.loads(js.stdout)
    assert d["open_count"] == 0 and len(d["closed"]) == 3
    assert {x["verdict"]["kind"] for x in d["closed"]} == {"keep", "revert", "extend"}
    chk = save(evidence, "verdict-check.txt", w.run("experiments", "check"))
    assert chk.returncode == 0, chk.stderr[-1500:]
    bad = save(evidence, "verdict-bad-kind.txt", w.run("experiments", "verdict", "k1", "hold"))
    unknown = save(evidence, "verdict-unknown-bead.txt", w.run("experiments", "verdict", "zz", "keep"))
    again = save(evidence, "verdict-again.txt",
                 w.run("experiments", "verdict", "k1", "revert", "--date", "2026-10-27"))
    assert bad.returncode != 0 and "keep|revert|extend" in (bad.stderr + bad.stdout)
    assert unknown.returncode != 0 and "no experiment sidecar" in unknown.stderr
    assert again.returncode != 0 and "not re-verdicted" in again.stderr
    side = json.loads((w.exp / "k1.json").read_text(encoding="utf-8"))  # the first verdict persists
    assert side["verdict"] == {"kind": "keep", "date": "2026-10-26"}
    facts = {"verdicts": outs, "closed_kinds": sorted(x["verdict"]["kind"] for x in d["closed"]),
             "rejected_rcs": [bad.returncode, unknown.returncode, again.returncode]}
    (evidence / "verdict-facts.json").write_text(json.dumps({"facts": facts}, indent=1), encoding="utf-8")
    return facts


def case_wip(w, evidence):
    for i in range(8):  # eight open fixtures: dates and run counts both present
        cw = {"date": day(i + 1)} if i % 2 else {"runs": i + 1, "since": "2026-10-26"}
        w.sidecar("w%d" % i, baseline=0.1, check_when=cw)
    eight = save(evidence, "wip-eight.txt", w.run("experiments", "check"))
    assert eight.returncode == 0, eight.stderr[-1500:]
    assert "8 open (cap 8)" in eight.stdout
    w.sidecar("w8", metric="runs_per_landed", baseline=2.0, check_when={"runs": 3, "since": "2026-10-26"})
    nine = save(evidence, "wip-nine.txt", w.run("experiments", "check"))
    nine_js = save(evidence, "wip-nine-json.txt", w.run("experiments", "check", "--json"))
    assert nine.returncode == 1 and "WIP cap exceeded" in nine.stdout and "9 open" in nine.stdout
    d9 = json.loads(nine_js.stdout)
    assert d9["open_count"] == 9 and d9["over_cap"]
    closed = save(evidence, "wip-verdict-close.txt",
                  w.run("experiments", "verdict", "w8", "revert", "--date", "2026-10-26"))
    assert closed.returncode == 0, closed.stderr[-1500:]
    eight_again = save(evidence, "wip-eight-after-verdict.txt", w.run("experiments", "check"))
    assert eight_again.returncode == 0, eight_again.stderr[-1500:]  # a verdict-closed record leaves the cap
    w.sidecar("wbet", labels=["experiment", "bet"])  # a bet is rejected even when also labelled experiment
    bet = save(evidence, "wip-bet.txt", w.run("experiments", "check"))
    bet_js = save(evidence, "wip-bet-json.txt", w.run("experiments", "check", "--json"))
    assert bet.returncode == 1 and "REJECTED" in bet.stdout and "bet" in bet.stdout
    db = json.loads(bet_js.stdout)
    assert db["open_count"] == 8 and [x["bead"] for x in db["rejected"]] == ["wbet"], (db["open_count"],
                                                                                       db["rejected"])
    facts = {"rcs": {"eight": eight.returncode, "nine": nine.returncode, "after_verdict": eight_again.returncode,
                     "bet": bet.returncode}, "open_counts": {"nine": d9["open_count"], "bet": db["open_count"]}}
    (evidence / "wip-facts.json").write_text(json.dumps({"facts": facts}, indent=1), encoding="utf-8")
    return facts


CASES = {"schema": case_schema, "report": case_report, "verdict": case_verdict, "wip": case_wip}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", choices=sorted(CASES), required=True)
    ap.add_argument("--evidence", default=".task/tl-7y6.1.2/evidence")
    a = ap.parse_args()
    evidence = Path(a.evidence).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    scratch = ROOT / ".task" / "tmp"  # worktree-local temporary data, never the system temp dir
    scratch.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.TemporaryDirectory(prefix="tl-experiments-", dir=str(scratch))
    try:
        facts = CASES[a.case](World(Path(tmp.name)), evidence)
        print("experiments scenario (%s): OK  %s" % (a.case, evidence))
        print("facts: " + json.dumps(facts, sort_keys=True))
        return 0
    finally:
        tmp.cleanup()


if __name__ == "__main__":
    sys.exit(main())
