"""tl report: the owner's comments against the engine's."""
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

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: E402, F401

# isort: split
import tl  # noqa: E402
from support import (  # noqa: E402
    looptest,
    tlbd,
)
from support.fakes import FakeBeadStore, as_comment  # noqa: E402
from support.logs import typed  # noqa: E402

from taskloop.adapters import (  # noqa: E402
    beadtools,
    gitrepo,
    ident,
)
from taskloop.app.launch import repos  # noqa: E402
from taskloop.app.report import card, inputs, lost  # noqa: E402

T0 = datetime(2026, 10, 21, 6, 0).timestamp()  # the window's start in the fixtures: local 06:00
MIN = 60.0


def git(repo, *args, t=None):
    env = dict(os.environ)
    if t is not None:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"@{int(t)} +0000"
    r = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env)
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


# ---- 10.2: lost work --------------------------------------------------------------------------------------------------

class LostWork(Base):
    def branch(self, name, files, t, start="main"):
        git(self.repo, "checkout", "-q", "-b", name, start)
        shas = [commit(self.repo, f, text, msg, t + i * MIN) for i, (f, text, msg) in enumerate(files)]
        git(self.repo, "checkout", "-q", "main")
        return shas

    def lost(self, status, traces=(), since=None):
        return lost.lost_work(str(self.repo), since=since, base="main", status_of=status.get,
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
        with tlbd.bd_boundary(result=tlbd.done(returncode=1, stderr="dolt: connection refused")):
            self.assertEqual(inputs.bead_status("t-1", str(self.repo)), "?")
        with tlbd.bd_boundary(result=tlbd.done(returncode=1, stderr="Error: issue t-1 not found")):
            self.assertIsNone(inputs.bead_status("t-1", str(self.repo)))

    def test_a_slot_resets_wip_branch_is_lost(self):
        self.branch("wip/s1/1792540800", [("f.txt", "dead session\n", "wip: left in slot s1")], T0)
        self.assertEqual(set(self.by_class(self.lost({}))), {"lost"})

    def test_a_branch_fresh_set_aside_is_superseded_and_names_its_bead(self):
        self.branch("task/t-1-stale-20261020-101500", [("f.txt", "old try\n", "wip (t-1): blocked")], T0)
        rows = self.lost({"t-1": "closed"})
        self.assertEqual(self.by_class(rows), {"superseded": [("task/t-1-stale-20261020-101500", rows[0]["sha"][:8])]})
        self.assertEqual(rows[0]["bead"], "t-1")

    def test_a_set_aside_branch_whose_bead_landed_later_is_landed(self):
        self.branch("task/t-1-stale-20261020-101500", [("f.txt", "old try\n", "wip (t-1): blocked")], T0)
        (self.repo / "g.txt").write_text("landed\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "Do the thing (t-1)", t=T0 + 30 * MIN)
        self.assertEqual(set(self.by_class(self.lost({"t-1": "closed"}))), {"landed"})

    def test_since_skips_older_commits(self):
        self.branch("task/t-1", [("f.txt", "old\n", "wip (t-1): failed")], T0 - 120 * MIN)
        self.assertEqual(self.lost({"t-1": "closed"}, since=T0), [])
        self.assertEqual(len(self.lost({"t-1": "closed"})), 1)


# ---- 10.1: the scorecard ----------------------------------------------------------------------------------------------

def trace(bead, outcome, start_min, end_min, why="", sha="", rounds=0, replans=0, sessions=(), worktree=None, run=None,
          stderr=None, kind=""):
    started, ended = T0 + start_min * MIN, T0 + end_min * MIN
    stem = run or "{}-{}".format(bead, time.strftime("%Y%m%d-%H%M%S", time.localtime(started)))
    return {"v": 1, "run": stem, "bead": bead, "repo": "https://example.invalid/r.git", "worktree": worktree,
            "started": started, "ended": ended, "outcome": outcome, "why": why, "sha": sha,
            "stats": {"rounds": rounds, "replans": replans}, "log": str(ident.config_dir() / "engine" / (stem + ".jsonl")),
            "sessions": list(sessions), "stderr": stderr, "kind": kind}


def session(role, family, tin, cached, out):
    return {"role": role, "family": family, "tokens": {"in": tin, "cached": cached, "out": out}}


class Scorecard(Base):
    def setUp(self):
        super().setUp()
        self.wt = str(self.repo / ".slots" / "s1")
        (ident.config_dir() / "engine").mkdir(parents=True, exist_ok=True)
        w = self.wt
        runs = [
            trace("t-0", "landed", -200, -150, sha="x", worktree=w),  # before the window: not counted
            trace("t-1", "landed", 10, 40, sha="a1", rounds=1, worktree=w, stderr=str(self.home / "t-1.stderr"),
                  sessions=[session("planner", "claude", 100, 80, 10), session("worker", "openai", 1000, 900, 50)]),
            trace("t-2", "blocked", 20, 50, why="verify: before land, the workers could not check: x", worktree=w, kind="ask_decision"),
            trace("t-2", "landed", 55, 70, sha="a2", worktree=w, sessions=[session("reviewer", "openai", 10, 0, 1)]),
            trace("t-3", "blocked", -10, 5, why="owner decision needed", worktree=w, kind="ask_decision"),  # overlaps 06:00: in the window
            trace("t-3", "landed", 30, 45, sha="a3", worktree=w),
            trace("t-4", "blocked", 60, 90, why="stage 1 stuck after 3 rounds and 1 re-plan(s)", replans=1, worktree=w, kind="ask_stuck"),
            trace("t-5", "blocked", 60, 61, why="paused: logged_out on plan", worktree=w),
            trace("t-6", "failed", 60, 70, why="failed: plan node produced no valid output", worktree=w),
            trace("t-7", "landed", 80, 100, sha="a7", worktree=w),
            trace("t-11", "failed", 100, 110, why="failed: stopped (SIGTERM)", worktree=w),  # tl stop --now: no crash
            trace("t-12", "failed", 110, 112, why="failed: engine error KeyError: 'x'", worktree=w),  # a caught crash
            trace("o-1", "landed", 10, 20, sha="z", worktree="/elsewhere/repo"),  # another repo
        ]
        with open(ident.config_dir() / "traces.jsonl", "w") as f:
            for r in runs:
                f.write(json.dumps(r) + "\n")
        # route.py's stderr carries a worker's test traceback: no engine crash
        (self.home / "t-1.stderr").write_text("Traceback (most recent call last):\n  File x\nAssertionError\n")
        # t-7's landing run resumed after an answer given before the window: it landed with an ask
        (ident.config_dir() / "engine" / (str(runs[-4]["run"]) + ".jsonl")).write_text(json.dumps(
            {"t": T0, "kind": "note", "text": "ask t-7-1 (verify) is answered: the bead changed since it was asked"}) + "\n")
        # a crash: an engine log with no close and no trace, long quiet
        dead = ident.config_dir() / "engine" / ("t-8-{}.jsonl".format(time.strftime("%Y%m%d-%H%M%S", time.localtime(T0 + 5 * MIN))))
        dead.write_text(json.dumps(typed("note", T0 + 5 * MIN, text="git commit -q -m wip (t-8): failed")) + "\n")
        # a run that is still going: no trace yet, but alive
        live = ident.config_dir() / "engine" / ("t-9-{}.jsonl".format(time.strftime("%Y%m%d-%H%M%S", time.localtime(T0 + 100 * MIN))))
        live.write_text(json.dumps(typed("beat", T0 + 200 * MIN - 30)) + "\n")  # its last beat, 30 s before the report's now
        # the loop's own record of a run-task that died before its engine wrote anything
        looptest.log(gitrepo.repo_root(str(self.repo))).parent.mkdir(parents=True, exist_ok=True)
        with open(looptest.log(gitrepo.repo_root(str(self.repo))), "w") as f:  # the loop keys it so
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
        return card.scorecard(str(self.repo), T0, until or T0 + 200 * MIN, base="main",
                                comments_of=lambda b: [as_comment(c) for c in self.comments.get(b, [])], status_of=self.status.get,
                                now=T0 + 200 * MIN)

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
        store = FakeBeadStore()
        store.notes = {b: [as_comment(x) for x in c] for b, c in self.comments.items()}
        with mock.patch.object(repos, "default_base", return_value="main"), mock.patch.object(beadtools, "bd_store", return_value=store), \
                mock.patch.object(lost, "bead_status", lambda b, repo: self.status.get(b)), \
                mock.patch.object(card, "time", mock.Mock(wraps=time, time=lambda: T0 + 200 * MIN)):  # the CLI reads the clock itself
            out = io.StringIO()
            with redirect_stdout(out):
                rc = tl.main(args)
            self.assertEqual(rc, 1)  # M2 failed
            text = out.getvalue()
            self.assertIn("M2 FAIL", text)
            self.assertIn("crashes 3", text)
            out = io.StringIO()
            with redirect_stdout(out):
                tl.main([*args, "--json"])
            self.assertEqual(json.loads(out.getvalue())["landed"], 4)
            out = io.StringIO()
            with redirect_stdout(out):
                rc = tl.main(["lost", "--repo", str(self.repo)])
            self.assertIn("task/t-6", out.getvalue())
            self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
