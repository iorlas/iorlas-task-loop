import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
import loop  # noqa: E402
import report  # noqa: E402
import tl  # noqa: E402

T0 = datetime(2026, 10, 21, 6, 0).timestamp()  # the window's start in the fixtures: local 06:00
MIN = 60.0


def git(repo, *args, t=None):
    env = dict(os.environ)
    if t is not None:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = "@%d +0000" % int(t)
    r = subprocess.run(["git", "-C", str(repo)] + list(args), check=True, capture_output=True, text=True, env=env)
    return r.stdout.strip()


def commit(repo, name, text, msg, t):
    (Path(repo) / name).write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", msg, t=t)
    return git(repo, "rev-parse", "HEAD")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        env = {"XDG_CONFIG_HOME": str(self.home / "cfg"), "APPDATA": str(self.home / "cfg"),
               "CLAUDE_CODE_SESSION_ID": "abcdef12-3456", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        self.repo = self.home / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        commit(self.repo, "a.txt", "a\n", "init", T0 - 600 * MIN)

    def tearDown(self):
        self.env.stop()

        def force(fn, path, _):  # Windows: git's pack files are read-only
            os.chmod(path, stat.S_IWRITE)
            fn(path)
        shutil.rmtree(self.tmp.name, onerror=force)


# ---- the window -------------------------------------------------------------------------------------------------------

class ParseTime(unittest.TestCase):
    NOW = datetime(2026, 10, 21, 20, 30).timestamp()

    def test_hh_mm_is_today(self):
        self.assertEqual(report.parse_time("06:00", self.NOW), datetime(2026, 10, 21, 6, 0).timestamp())

    def test_durations_count_back_from_now(self):
        self.assertEqual(report.parse_time("12h", self.NOW), self.NOW - 12 * 3600)
        self.assertEqual(report.parse_time("90m", self.NOW), self.NOW - 90 * 60)
        self.assertEqual(report.parse_time("2d", self.NOW), self.NOW - 2 * 86400)

    def test_iso_local_and_with_offset(self):
        self.assertEqual(report.parse_time("2026-10-20T22:15", self.NOW), datetime(2026, 10, 20, 22, 15).timestamp())
        self.assertEqual(report.parse_time("2026-10-20 22:15", self.NOW), datetime(2026, 10, 20, 22, 15).timestamp())
        self.assertEqual(report.parse_time("2026-10-20", self.NOW), datetime(2026, 10, 20).timestamp())
        self.assertEqual(report.parse_time("2026-10-21T03:00:00Z", self.NOW), 1792551600.0)

    def test_since_hh_mm_rolls_back_until_rolls_forward(self):
        morning = datetime(2026, 10, 21, 7, 0).timestamp()
        self.assertEqual(report.parse_time("22:00", morning), datetime(2026, 10, 20, 22, 0).timestamp())
        self.assertEqual(report.parse_time("22:00", morning, forward=True), datetime(2026, 10, 21, 22, 0).timestamp())
        self.assertEqual(report.parse_time("06:00", morning, forward=True), datetime(2026, 10, 22, 6, 0).timestamp())

    def test_nonsense_is_refused(self):
        with self.assertRaises(ValueError):
            report.parse_time("yesterday-ish", self.NOW)


# ---- 10.2: lost work --------------------------------------------------------------------------------------------------

class LostWork(Base):
    def branch(self, name, files, t, start="main"):
        git(self.repo, "checkout", "-q", "-b", name, start)
        shas = [commit(self.repo, f, text, msg, t + i * MIN) for i, (f, text, msg) in enumerate(files)]
        git(self.repo, "checkout", "-q", "main")
        return shas

    def lost(self, status, traces=(), since=None):
        return report.lost_work(str(self.repo), since=since, base="main", status_of=lambda b: status.get(b),
                                traces=list(traces))

    def by_class(self, rows):
        out = {}
        for r in rows:
            out.setdefault(r["class"], []).append((r["branch"], r["sha"][:8]))
        return out

    def test_an_orphan_commit_on_a_closed_beads_branch_is_lost(self):
        sha, = self.branch("task/t-1", [("f.txt", "work\n", "wip (t-1): failed")], T0)
        rows = self.lost({"t-1": "closed"})
        self.assertEqual(self.by_class(rows), {"lost": [("task/t-1", sha[:8])]})
        self.assertIn("closed", rows[0]["why"])

    def test_a_fast_forward_land_leaves_nothing_to_check(self):
        self.branch("task/t-1", [("f.txt", "work\n", "work (t-1)")], T0)
        git(self.repo, "merge", "-q", "--ff-only", "task/t-1")
        self.assertEqual(self.lost({"t-1": "closed"}), [])

    def test_a_squash_land_covers_the_branch_commits_before_it(self):
        self.branch("task/t-1", [("f.txt", "one\n", "wip (t-1): blocked"), ("g.txt", "two\n", "wip (t-1): paused")], T0)
        (self.repo / "f.txt").write_text("one\n")  # the land: one commit titled after the bead, made later
        (self.repo / "g.txt").write_text("two\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "Do the thing (t-1)", t=T0 + 30 * MIN)
        rows = self.lost({"t-1": "closed"})
        self.assertEqual(set(self.by_class(rows)), {"landed"})
        self.assertEqual(len(rows), 2)

    def test_the_recorded_land_sha_on_the_base_covers_the_branch(self):
        self.branch("task/t-1", [("f.txt", "one\n", "wip (t-1): blocked")], T0)
        (self.repo / "f.txt").write_text("one, edited at land\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "a title the bead lost", t=T0 + 30 * MIN)
        land = git(self.repo, "rev-parse", "HEAD")
        trace = {"bead": "t-1", "outcome": "landed", "sha": land, "started": T0, "ended": T0 + 31 * MIN}
        self.assertEqual(set(self.by_class(self.lost({"t-1": "closed"}, [trace]))), {"landed"})

    def test_a_cherry_picked_commit_is_landed_by_its_patch(self):
        sha, = self.branch("task/t-1", [("f.txt", "work\n", "work")], T0)
        git(self.repo, "cherry-pick", sha)
        self.assertEqual(set(self.by_class(self.lost({"t-1": "closed"}))), {"landed"})

    def test_work_after_the_land_is_lost(self):
        self.branch("task/t-1", [("f.txt", "late\n", "wip (t-1): after")], T0 + 60 * MIN)
        (self.repo / "g.txt").write_text("landed\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "Do the thing (t-1)", t=T0)
        self.assertEqual(set(self.by_class(self.lost({"t-1": "closed"}))), {"lost"})

    def test_a_paused_beads_wip_is_pending_not_lost(self):
        self.branch("task/t-1", [("f.txt", "work\n", "wip (t-1): paused")], T0)
        rows = self.lost({"t-1": "open"})
        self.assertEqual(set(self.by_class(rows)), {"pending"})

    def test_a_later_run_reclaims_the_wip(self):
        self.branch("task/t-1", [("f.txt", "work\n", "wip (t-1): blocked")], T0)
        later = {"bead": "t-1", "outcome": "blocked", "why": "paused: x", "sha": "", "started": T0 + 10 * MIN,
                 "ended": T0 + 20 * MIN}
        self.assertEqual(set(self.by_class(self.lost({"t-1": "in_progress"}, [later]))), {"reclaimed"})

    def test_a_tracker_outage_is_unknown_never_lost(self):
        self.branch("task/t-1", [("f.txt", "work\n", "wip (t-1): paused")], T0)
        self.assertEqual(set(self.by_class(self.lost({"t-1": "?"}))), {"unknown"})

    def test_bd_failing_reads_as_unknown(self):
        failed = subprocess.CompletedProcess([], 1, "", "dolt: connection refused")
        with mock.patch.object(tl, "bd", return_value=failed):
            self.assertEqual(report.bead_status("t-1", str(self.repo)), "?")
        missing = subprocess.CompletedProcess([], 1, "", "Error: issue t-1 not found")
        with mock.patch.object(tl, "bd", return_value=missing):
            self.assertIsNone(report.bead_status("t-1", str(self.repo)))

    def test_a_slot_resets_wip_branch_is_lost(self):
        self.branch("wip/s1/1792540800", [("f.txt", "dead session\n", "wip: left in slot s1")], T0)
        self.assertEqual(set(self.by_class(self.lost({}))), {"lost"})

    def test_since_skips_older_commits(self):
        self.branch("task/t-1", [("f.txt", "old\n", "wip (t-1): failed")], T0 - 120 * MIN)
        self.assertEqual(self.lost({"t-1": "closed"}, since=T0), [])
        self.assertEqual(len(self.lost({"t-1": "closed"})), 1)


# ---- 10.1: the scorecard ----------------------------------------------------------------------------------------------

def trace(bead, outcome, start_min, end_min, why="", sha="", rounds=0, replans=0, sessions=(), worktree=None, run=None,
          stderr=None):
    started, ended = T0 + start_min * MIN, T0 + end_min * MIN
    stem = run or "%s-%s" % (bead, time.strftime("%Y%m%d-%H%M%S", time.localtime(started)))
    return {"v": 1, "run": stem, "bead": bead, "repo": "https://example.invalid/r.git", "worktree": worktree,
            "started": started, "ended": ended, "outcome": outcome, "why": why, "sha": sha,
            "stats": {"rounds": rounds, "replans": replans}, "log": str(tl.config_dir() / "engine" / (stem + ".jsonl")),
            "sessions": list(sessions), "stderr": stderr}


def session(role, family, tin, cached, out):
    return {"role": role, "family": family, "tokens": {"in": tin, "cached": cached, "out": out}}


class Scorecard(Base):
    def setUp(self):
        super().setUp()
        self.wt = str(self.repo / ".slots" / "s1")
        (tl.config_dir() / "engine").mkdir(parents=True, exist_ok=True)
        w = self.wt
        runs = [
            trace("t-0", "landed", -200, -150, sha="x", worktree=w),  # before the window: not counted
            trace("t-1", "landed", 10, 40, sha="a1", rounds=1, worktree=w, stderr=str(self.home / "t-1.stderr"),
                  sessions=[session("planner", "claude", 100, 80, 10), session("worker", "openai", 1000, 900, 50)]),
            trace("t-2", "blocked", 20, 50, why="verify: before land, the workers could not check: x", worktree=w),
            trace("t-2", "landed", 55, 70, sha="a2", worktree=w, sessions=[session("reviewer", "openai", 10, 0, 1)]),
            trace("t-3", "blocked", -10, 5, why="owner decision needed", worktree=w),  # overlaps 06:00: in the window
            trace("t-3", "landed", 30, 45, sha="a3", worktree=w),
            trace("t-4", "blocked", 60, 90, why="stage 1 stuck after 3 rounds and 1 re-plan(s)", replans=1, worktree=w),
            trace("t-5", "blocked", 60, 61, why="paused: logged_out on plan", worktree=w),
            trace("t-6", "failed", 60, 70, why="failed: plan node produced no valid output", worktree=w),
            trace("t-7", "landed", 80, 100, sha="a7", worktree=w),
            trace("t-11", "failed", 100, 110, why="failed: stopped (SIGTERM)", worktree=w),  # tl stop --now: no crash
            trace("t-12", "failed", 110, 112, why="failed: engine error KeyError: 'x'", worktree=w),  # a caught crash
            trace("o-1", "landed", 10, 20, sha="z", worktree="/elsewhere/repo"),  # another repo
        ]
        with open(tl.config_dir() / "traces.jsonl", "w") as f:
            for r in runs:
                f.write(json.dumps(r) + "\n")
        # route.py's stderr carries a worker's test traceback: no engine crash
        (self.home / "t-1.stderr").write_text("Traceback (most recent call last):\n  File x\nAssertionError\n")
        # t-7's landing run resumed after an answer given before the window: it landed with an ask
        (tl.config_dir() / "engine" / (runs[-4]["run"] + ".jsonl")).write_text(json.dumps(
            {"t": T0, "kind": "note", "text": "ask t-7-1 (verify) is answered: the bead changed since it was asked"}) + "\n")
        # a crash: an engine log with no close and no trace, long quiet
        dead = tl.config_dir() / "engine" / ("t-8-%s.jsonl" % time.strftime("%Y%m%d-%H%M%S", time.localtime(T0 + 5 * MIN)))
        dead.write_text(json.dumps({"t": T0 + 5 * MIN, "kind": "cmd", "text": "git commit -q -m wip (t-8): failed"}) + "\n")
        os.utime(dead, (T0 + 6 * MIN, T0 + 6 * MIN))
        # a run that is still going: no trace yet, but alive
        live = tl.config_dir() / "engine" / ("t-9-%s.jsonl" % time.strftime("%Y%m%d-%H%M%S", time.localtime(T0 + 100 * MIN)))
        live.write_text(json.dumps({"t": T0 + 100 * MIN, "kind": "node", "text": "write"}) + "\n")
        # the loop's own record of a run-task that died before its engine wrote anything
        with open(loop.paths(tl.repo_root(str(self.repo)))["log"], "w") as f:  # the loop keys it so
            f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(T0 + 95 * MIN)), "bead": "t-10",
                                "slot": "s1", "outcome": "failed", "minutes": 0.1, "trace": None,
                                "why": "failed: no outcome from run-task (exit 1); see x.log"}) + "\n")
        # an orphan commit on a closed bead's branch
        git(self.repo, "checkout", "-q", "-b", "task/t-6")
        commit(self.repo, "f.txt", "x\n", "wip (t-6): failed", T0 + 70 * MIN)
        git(self.repo, "checkout", "-q", "main")
        # t-1 squash-landed: its branch's wip is folded into one base commit titled after the bead
        git(self.repo, "checkout", "-q", "-b", "task/t-1")
        commit(self.repo, "h.txt", "draft\n", "wip (t-1): blocked", T0 + 20 * MIN)
        git(self.repo, "checkout", "-q", "main")
        commit(self.repo, "h.txt", "final\n", "Do the thing (t-1)", T0 + 40 * MIN)
        self.comments = {
            "t-2": [{"text": "Ask (engine) t-2-1 (verify): x", "created_at": "2026-10-21T03:50:00Z", "author": "tl-x"},
                    {"text": "Right. (Claude, supervising.)", "created_at": "2026-10-21T03:51:00Z", "author": "D"}],
            "t-3": [{"text": "Ask (engine) t-3-1 (decision): x", "created_at": "2026-10-21T03:04:00Z", "author": "tl-x"},
                    {"text": "Answer (Denis, relayed by Claude): take A.", "created_at": "2026-10-21T03:20:00Z", "author": "D"}],
            "t-4": [{"text": "Ask (engine) t-4-1 (stuck): x", "created_at": "2026-10-21T04:30:00Z", "author": "tl-x"},
                    {"text": "Reflect (engine): outcome=blocked", "created_at": "2026-10-21T04:30:01Z", "author": "tl-x"}],
        }
        self.status = {"t-6": "closed"}

    def card(self, until=None):
        return report.scorecard(str(self.repo), T0, until or T0 + 200 * MIN, base="main",
                                comments_of=lambda b: self.comments.get(b, []), status_of=lambda b: self.status.get(b),
                                alive=lambda bead: bead == "t-9", now=T0 + 200 * MIN)

    def test_the_six_counts(self):
        c = self.card()
        self.assertEqual(c["beads"], 11)  # t-1..t-8, t-10..t-12 (t-9 still runs); not t-0, not o-1
        self.assertEqual(c["landed"], 4)
        self.assertEqual(c["landed_no_ask"], 1)  # t-1; t-2, t-3 and t-7 landed after an ask
        self.assertEqual(c["parked"], 1)  # t-4
        self.assertEqual(c["paused"], 1)  # t-5
        self.assertEqual(c["failed"], 5)  # t-6, the stopped t-11, and the crashed t-8, t-10 and t-12
        self.assertEqual(c["crashes"], 3)  # not t-1 (a traceback in route.py's stderr), not t-11 (a stop)
        self.assertEqual(sorted(x["bead"] for x in c["crash_list"]), ["t-10", "t-12", "t-8"])
        self.assertEqual(c["lost"], 1)  # t-6; t-1's squash-landed wip is no loss
        self.assertEqual(c["pending_list"], [])

    def test_who_answered_the_asks(self):
        a = self.card()["asks"]
        self.assertEqual((a["count"], a["beads"]), (4, 4))
        self.assertEqual((a["supervisor"], a["owner"], a["open"]), (1, 1, 1))

    def test_minutes_rounds_and_tokens(self):
        c = self.card()
        self.assertEqual(c["minutes"]["median"], 20)  # traced beads: 1 2 10 10 20 30 30 30 45
        self.assertEqual(c["minutes"]["p90"], 45)
        self.assertEqual(c["rounds"], 1)
        self.assertEqual(c["replans"], 1)
        self.assertEqual(c["tokens"]["lane"]["codex"], {"in": 1010, "cached": 900, "out": 51})
        self.assertEqual(c["tokens"]["lane"]["claude"], {"in": 100, "cached": 80, "out": 10})
        self.assertEqual(c["tokens"]["role"]["worker"]["in"], 1000)

    def test_the_m2_verdict_names_what_failed(self):
        c = self.card()
        self.assertFalse(c["m2"]["pass"])
        failed = {k for k, v in c["m2"]["checks"].items() if not v["ok"]}
        self.assertEqual(failed, {"landed_no_ask", "lost", "crashes"})

    def test_the_cli_prints_a_table_and_a_verdict_and_json(self):
        args = ["report", "--repo", str(self.repo), "--since", "2026-10-21T06:00", "--until", "2026-10-21T09:20"]
        with mock.patch.object(report, "default_base", return_value="main"), \
                mock.patch.object(tl, "comments", lambda b, cwd=None: self.comments.get(b, [])), \
                mock.patch.object(report, "bead_status", lambda b, repo: self.status.get(b)), \
                mock.patch.object(report, "run_alive", lambda bead: bead == "t-9"):
            out = io.StringIO()
            with redirect_stdout(out):
                rc = tl.main(args)
            self.assertEqual(rc, 1)  # M2 failed
            text = out.getvalue()
            self.assertIn("M2 FAIL", text)
            self.assertIn("crashes 3", text)
            out = io.StringIO()
            with redirect_stdout(out):
                tl.main(args + ["--json"])
            self.assertEqual(json.loads(out.getvalue())["landed"], 4)
            out = io.StringIO()
            with redirect_stdout(out):
                rc = tl.main(["lost", "--repo", str(self.repo)])
            self.assertIn("task/t-6", out.getvalue())
            self.assertEqual(rc, 1)


class PlannerReport(unittest.TestCase):
    """tl-bxk.10.13: planner calls per bead and their input tokens, from delegate's history and the engine logs."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        home = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {"HOME": str(home), "XDG_CONFIG_HOME": str(home / "cfg"),
                                                "APPDATA": str(home / "cfg")})
        self.env.start()
        self.hist = home / "history.jsonl"
        self.eng = tl.config_dir() / "engine"
        self.eng.mkdir(parents=True)
        t = T0
        rows = [("planner", "x-1", 1000, 9000), ("planner", "x-1", 500, 4500), ("planner", "x-1", 200, 800),
                ("planner", "x-1", 100, 100), ("worker", "x-1", 9999, 9999), ("planner", "x-2", 300, 700),
                ("planner", "y-9", 1, 1)]
        self.hist.write_text("".join(json.dumps({"ts": t + k, "role": r, "task": b, "tokens": {"in": i, "cached": c, "out": 5}})
                                     + "\n" for k, (r, b, i, c) in enumerate(rows)))
        nodes = [("plan: plan", {}), ("plan: re-plan", {}), ("plan: rewrite checks", {}), ("plan: amend", {"mode": "amend"})]
        (self.eng / "x-1-20261021-060000.jsonl").write_text("".join(
            json.dumps(dict({"t": t + k, "kind": "node", "text": txt, "node": "plan"}, **kw)) + "\n"
            for k, (txt, kw) in enumerate(nodes)))
        (self.eng / "x-2-20261021-060000.jsonl").write_text(json.dumps(
            {"t": t, "kind": "node", "text": "plan: plan", "node": "plan", "mode": "plan"}) + "\n")

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_calls_are_split_into_first_again_amend_and_send_back_and_input_is_in_plus_cached(self):
        p = report.planner_stats(T0 - 1, T0 + 100, history=self.hist)
        by = {x["bead"]: x for x in p["per_bead"]}
        self.assertEqual({k: by["x-1"][k] for k in ("calls", "first", "again", "amend", "back", "other", "input")},
                         {"calls": 4, "first": 1, "again": 1, "amend": 1, "back": 1, "other": 0, "input": 16100})
        self.assertEqual((by["x-2"]["calls"], by["x-2"]["first"], by["x-2"]["input"]), (1, 1, 1000))
        self.assertEqual((p["calls"], p["beads"], p["input"]), (6, 3, 17101))  # the worker call is no planner call
        only = report.planner_stats(T0 - 1, T0 + 100, {"x"}, history=self.hist)
        self.assertEqual((only["calls"], only["beads"]), (5, 2))
        self.assertEqual(report.planner_stats(T0 + 50, T0 + 100, history=self.hist)["calls"], 0)  # outside the window

    def test_input_is_in_when_in_already_holds_the_cache_else_in_plus_cached(self):
        self.assertEqual(report.input_tokens({"in": 10000, "cached": 9000}), 10000)   # delegate 0.22+ and Codex
        self.assertEqual(report.input_tokens({"in": 1000, "cached": 9000}), 10000)    # before 0.22: uncached-only in
        self.assertEqual(report.input_tokens({"in": 5, "cached": 0}), 5)
        self.assertEqual(report.input_tokens({}), 0)

    def test_the_cli_prints_the_planner_table_read_only(self):
        before = sorted(p.name for p in self.eng.iterdir())
        out = io.StringIO()
        with mock.patch.object(report, "HISTORY", str(self.hist)), redirect_stdout(out):
            rc = tl.main(["report", "--planner", "--prefix", "x", "--since", "2026-10-21", "--until", "2026-10-22"])
        text = out.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("planner: 5 calls on 2 beads", text)
        self.assertRegex(text, r"x-1\s+4\s+1\s+1\s+1\s+1\s+0\s+0\.02")
        self.assertEqual(before, sorted(p.name for p in self.eng.iterdir()))


if __name__ == "__main__":
    unittest.main()
