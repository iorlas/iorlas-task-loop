import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
import engine  # noqa: E402
import tl  # noqa: E402


def sh(*a, cwd):
    subprocess.run(list(a), cwd=cwd, check=True, capture_output=True)


PY = '"%s"' % sys.executable
HAS_F = PY + ' -c "import os,sys; sys.exit(0 if os.path.exists(\'f.txt\') else 1)"'
FALSE = PY + ' -c "import sys; sys.exit(1)"'
PLAN = {"summary": "do it", "stages": [{"goal": "add f", "files": ["f.txt"], "checks": [HAS_F],
                                        "hard": False}], "risks": [], "question": ""}
WRITE = {"summary": "wrote f", "checks_run": [{"cmd": "test -f f.txt", "exit": 0}], "question": "", "bad_checks": []}
ROUTE = "/h/.claude/plugins/cache/m/iorlas-delegate/%s/skills/delegate/route.py"
CLEAN = {"findings": [], "unmet": [], "question": "", "leftovers": []}


def review(unmet=(), findings=(), question=""):
    return dict(CLEAN, unmet=list(unmet), findings=list(findings), question=question)


def finding(severity):
    return {"file": "f.txt", "line": 1, "severity": severity, "fix": "a %s fix" % severity}


class DelegateScript:
    """Fake `route.py run`: answers per role from a queue; a write creates the file like a real writer."""

    def __init__(self, answers):
        self.answers, self.calls, self.prompts = {k: list(v) for k, v in answers.items()}, [], []
        self.unsandboxed = []

    def __call__(self, route, role, prompt, schema, cwd, resume, timeout, log_path, writer=None, parent="", task="",
                 title="", no_sandbox=False):
        node = next(k for k, v in engine.SCHEMAS.items() if v is schema)
        self.calls.append((role, resume, writer))
        self.unsandboxed.append((role, no_sandbox))
        self.prompts.append(prompt)
        a = self.answers[node].pop(0)
        if isinstance(a, dict) and a.get("v") is not None:
            j = a
        else:
            if node == "write":
                Path(cwd, "f.txt").write_text("d%d\n" % len(self.calls))
            j = {"v": 1, "status": "done", "data": a, "ref": "ref-" + node, "cost": 0.5, "secs": 1,
                 "family": "openai" if node == "write" else "claude", "lane": "L", "model": "m",
                 "effort": "e", "git_violation": [], "tokens": {"in": 1000, "cached": 800, "out": 50}}
        r = engine.Result(j.get("data"), "", j.get("ref") or "", float(j.get("cost") or 0), 1, "" if j["status"] == "done" else j["status"],
                          j.get("family") or "delegate")
        return r, j


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        home = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(home / "cfg"), "APPDATA": str(home / "cfg"),
                                                "CLAUDE_CODE_SESSION_ID": "sess1234-x", "GIT_AUTHOR_NAME": "t",
                                                "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                                                "GIT_COMMITTER_EMAIL": "t@t"})
        self.env.start()
        origin, self.wt = home / "o.git", home / "wt"
        sh("git", "init", "-q", "--bare", "-b", "main", str(origin), cwd=home)
        sh("git", "clone", "-q", str(origin), str(self.wt), cwd=home)
        (self.wt / "a.txt").write_text("a\n")
        sh("git", "add", "-A", cwd=self.wt)
        sh("git", "commit", "-qm", "init", cwd=self.wt)
        sh("git", "push", "-q", "origin", "HEAD:main", cwd=self.wt)
        self.bd_calls = []
        self.closed, self.blocked = [], []
        patches = [
            mock.patch.object(tl, "bd", side_effect=self.fake_bd),
            mock.patch.object(tl, "show", return_value={"id": "t-1", "title": "Add f", "metadata": {}}),
            mock.patch.object(tl, "comments", return_value=[]),
            mock.patch.object(tl, "cmd_close", side_effect=lambda a: self.closed.append(a.reason) or 0),
            mock.patch.object(tl, "cmd_block", side_effect=lambda a: self.blocked.append(a.why) or 0),
            mock.patch.object(tl, "cmd_land", return_value=0),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def fake_bd(self, *a, **kw):
        self.bd_calls.append(a)
        return mock.Mock(returncode=0, stdout="bead t-1: Add f\n", stderr="")

    def run_engine(self, answers, route="/fake/route.py", **cfg):
        script = DelegateScript(answers)
        c = engine.load_cfg(str(self.wt))
        c.update(cfg)
        with mock.patch.object(engine, "find_route", return_value=route), \
                mock.patch.object(engine, "call_delegate", script), mock.patch.object(engine.time, "sleep"):
            self.eng = engine.Engine("t-1", str(self.wt), c)
            rc = self.eng.run()
        return rc, script

    def test_happy_path_lands_and_closes(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer"])
        self.assertTrue(self.closed and self.closed[0].startswith("merged "))
        self.assertEqual(tl.git("show", "origin/main:f.txt", cwd=str(self.wt)), "d2")
        self.assertTrue(any(c[:2] == ("comments", "add") and "Reflect (engine)" in c[3] for c in self.bd_calls))

    def test_brief_is_a_digest_without_engine_comments(self):
        bead = {"id": "t-1", "title": "Add f", "metadata": {}, "description": "Add the file f.",
                "acceptance_criteria": "f.txt exists", "notes": "owner: keep it short",
                "dependencies": [{"id": "t-0", "title": "The epic", "description": "x" * 3000}]}
        comments = [{"author": "tl-a", "text": "Plan (engine): " + "p" * 6000},
                    {"author": "tl-a", "text": "Review (engine, stage 1/1): " + "r" * 2000},
                    {"author": "tl-a", "text": "Reflect (engine): outcome=failed; minutes=26"},
                    {"author": "tl-a", "text": "Blocked: failed: stopped (SIGTERM)"},
                    {"author": "denis", "text": "Use the old format, not the new one."}]
        with mock.patch.object(tl, "show", return_value=bead), mock.patch.object(tl, "comments", return_value=comments):
            rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        brief = (self.eng.run_dir / "brief.md").read_text()
        for kept in ("Add the file f.", "f.txt exists", "owner: keep it short", "Use the old format", "t-0 The epic",
                     "Blocked: failed: stopped (SIGTERM)"):
            self.assertIn(kept, brief)
        for dropped in ("p" * 50, "r" * 50, "x" * 50, "minutes=26"):
            self.assertNotIn(dropped, brief)
        self.assertLess(len(brief.encode()), 5000)

    def test_engine_files_live_outside_the_worktree_and_stale_ones_are_cleared(self):
        td = self.wt / ".task" / "t-1"
        (td / "evidence").mkdir(parents=True)
        (td / "evidence" / "seen-red.log").write_text("red then green\n")
        (td / "rechecks.json").write_text('{"exit": 124}')  # a writer's sandbox run from an earlier run
        (td / "verify-9.json").write_text("{}")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual(sorted(p.name for p in td.iterdir()), ["evidence"])
        self.assertTrue((td / "evidence" / "seen-red.log").exists())
        run = self.eng.run_dir
        self.assertFalse(str(run).startswith(str(self.wt)))
        for f in ("brief.md", "plan.json", "engine-checks.json"):
            self.assertTrue((run / f).exists(), f)
        self.assertIn(str(run / "brief.md"), s.prompts[0])

    def test_repo_checks_on_an_equal_tree_and_base_are_reused(self):
        count = Path(self.tmp.name) / "count"
        bump = PY + ' -c "open(%r, \'a\').write(\'1\')"' % str(count)
        eng = self.checks_engine(checks=[{"id": "bump", "cmd": bump, "group": "tests"}])
        st = {"checks": [], "files": []}
        first = eng.run_checks(st, "s")
        again = eng.run_checks(st, "s")
        self.assertEqual(count.read_text(), "1")
        self.assertTrue(again[0].get("cached"))
        (self.wt / "new.txt").write_text("x\n")  # an untracked file changes the tree
        eng.run_checks(st, "s")
        self.assertEqual(count.read_text(), "11")
        self.assertEqual(first[0]["exit"], 0)

    def test_a_check_that_times_out_is_red_and_leaves_no_process(self):
        c = engine.load_cfg(str(self.wt))
        c["node_timeout_min"] = 0.03  # under 2 s
        eng = engine.Engine("t-1", str(self.wt), c)
        res = eng.run_checks({"checks": ["bash -c 'sleep 61.234; true'"], "files": []}, "s")
        self.assertEqual(res[0]["exit"], 124)
        self.assertIn("timed out", res[0]["tail"])
        left = subprocess.run(["pgrep", "-f", "sleep 61.234"], capture_output=True, text=True).stdout.strip()
        self.assertEqual(left, "")

    def test_checks_run_without_the_launchers_claude_session(self):
        c = engine.load_cfg(str(self.wt))
        eng = engine.Engine("t-1", str(self.wt), c)
        with mock.patch.dict(os.environ, {"CLAUDE_CODE_ENTRYPOINT": "cli"}):
            res = eng.run_checks({"checks": [PY + ' -c "import os,sys; sys.exit(1 if os.environ.get(\'CLAUDE_CODE_ENTRYPOINT\') else 0)"'],
                                  "files": []}, "s")
        self.assertEqual(res[0]["exit"], 0)

    def test_planner_is_told_the_engine_owns_time_limits(self):
        self.assertIn("The engine sets every time limit", engine.PLAN_PROMPT)

    def checks_engine(self, **cfg):
        c = engine.load_cfg(str(self.wt))
        c.update(cfg)
        return engine.Engine("t-1", str(self.wt), c)

    def test_checks_run_in_groups_fastest_first_and_stop_at_a_red_group(self):
        eng = self.checks_engine(checks=[{"id": "unit", "cmd": PY + ' -c "pass"', "group": "tests"},
                                         {"id": "lint", "cmd": FALSE, "group": "static"}])
        res = eng.run_checks({"checks": [PY + ' -c "pass"'], "files": []}, "s")
        self.assertEqual([(c["group"], c["status"]) for c in res],
                         [("static", "failed"), ("tests", "skipped"), ("acceptance", "skipped")])
        self.assertIn("static failed", res[1]["why"])

    def test_a_repo_check_runs_only_when_its_paths_changed(self):
        eng = self.checks_engine(checks=[{"id": "unity", "cmd": PY + ' -c "pass"', "group": "tests", "when": ["client/**"]}])
        eng.git("checkout", "-q", "-b", "task/t-1")
        self.assertEqual(eng.run_checks({"checks": [], "files": []}, "s")[0]["status"], "skipped")
        (self.wt / "client").mkdir()
        (self.wt / "client" / "a.cs").write_text("x\n")
        self.assertEqual(eng.run_checks({"checks": [], "files": []}, "s")[0]["status"], "ran")

    def test_a_flaky_check_gets_its_retries(self):
        mark = Path(self.tmp.name) / "seen"
        flaky = PY + ' -c "import os,sys; p=%r; first=not os.path.exists(p); open(p,\'w\').close(); sys.exit(1 if first else 0)"' % str(mark)
        eng = self.checks_engine(checks=[{"id": "flaky", "cmd": flaky, "group": "tests", "retry": 1}])
        res = eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual((res[0]["exit"], res[0]["status"], res[0]["tries"]), (0, "ran", 2))

    def test_a_passing_check_still_shows_its_notable_lines(self):
        out = engine.compact([{"cmd": "just check", "exit": 0, "status": "ran", "group": "tests",
                               "tail": "lane light: ok\nunity steps run: client changed\nfoo\nbar\n439 passed"}])
        self.assertIn("unity steps run", out)
        self.assertIn("439 passed", out)

    def test_the_gate_runs_once_at_land_and_tells_the_push_which_tree_it_gated(self):
        count, seen = Path(self.tmp.name) / "gates", Path(self.tmp.name) / "gated-tree"
        gate = PY + ' -c "open(%r, \'a\').write(\'1\')"' % str(count)
        land = PY + ' -c "import os; open(%r, \'w\').write(os.environ.get(\'TASK_LOOP_GATED_TREE\', \'\'))" && git push -q origin HEAD:main' % str(seen)
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]},
                                gate=gate, land=land)
        self.assertEqual(rc, 0)
        self.assertEqual(count.read_text(), "1")
        self.assertEqual(seen.read_text(), tl.git("rev-parse", "HEAD^{tree}", cwd=str(self.wt)))

    def test_a_stage_check_always_reruns_it_can_read_state_outside_the_tree(self):
        state = Path(self.tmp.name) / "editor-open"  # a running editor, a log, a bead comment: git cannot see them
        eng = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        st = {"checks": ['! test -e %s' % state], "files": []}
        self.assertEqual(eng.run_checks(st, "s")[0]["exit"], 0)
        state.write_text("x")
        again = eng.run_checks(st, "s")
        self.assertEqual(again[0]["exit"], 1)
        self.assertFalse(again[0].get("cached"))

    def test_a_repo_check_marked_cache_false_always_reruns(self):
        count = Path(self.tmp.name) / "count"
        bump = PY + ' -c "open(%r, \'a\').write(\'1\')"' % str(count)
        eng = self.checks_engine(checks=[{"id": "bump", "cmd": bump, "group": "tests", "cache": False}])
        eng.run_checks({"checks": [], "files": []}, "s")
        eng.run_checks({"checks": [], "files": []}, "s")
        self.assertEqual(count.read_text(), "11")

    def test_a_failed_check_is_never_reused(self):
        count = Path(self.tmp.name) / "count"
        fails = PY + ' -c "import sys; open(%r, \'a\').write(\'1\'); sys.exit(1)"' % str(count)
        eng = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        st = {"checks": [fails], "files": []}
        eng.run_checks(st, "s")
        again = eng.run_checks(st, "s")
        self.assertEqual(count.read_text(), "11")
        self.assertFalse(again[0].get("cached"))

    def test_checks_run_in_bash(self):
        eng = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        res = eng.run_checks({"checks": ['diff <(echo a) <(echo a)'], "files": []}, "s")
        self.assertEqual(res[0]["exit"], 0, res[0]["tail"])

    def test_a_stop_during_a_check_stops_the_check_and_everything_it_started(self):
        if os.name == "nt":
            self.skipTest("POSIX process groups")
        eng = engine.Engine("t-1", str(self.wt), engine.load_cfg(str(self.wt)))
        pidfile = Path(self.wt, "child.pid")
        real = subprocess.Popen.communicate
        started = []

        def stopped(this, *a, **kw):
            for _ in range(100):
                if pidfile.exists() and pidfile.read_text().strip():
                    break
                time.sleep(0.05)
            started.append(this.pid)
            raise engine.Blocked("failed: stopped (SIGTERM)")
        with mock.patch.object(subprocess.Popen, "communicate", stopped):
            with self.assertRaises(engine.Blocked):
                eng.sh("sleep 30 & echo $! > child.pid; wait")
        child = int(pidfile.read_text())
        for _ in range(50):
            try:
                os.kill(child, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            os.killpg(started[0], 9)
            self.fail("the check's child outlived the stop")

    def test_a_worker_edit_to_the_plan_file_is_undone_before_the_next_step(self):
        real = DelegateScript.__call__

        def tamper(this, route, role, prompt, schema, cwd, *a, **kw):
            if role == "worker":
                (self.eng.run_dir / "plan.json").write_text('{"tampered": true}')
            if role == "reviewer":
                this.seen_plan = (self.eng.run_dir / "plan.json").read_text()
            return real(this, route, role, prompt, schema, cwd, *a, **kw)
        with mock.patch.object(DelegateScript, "__call__", tamper):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertNotIn("tampered", s.seen_plan)
        self.assertIn("add f", s.seen_plan)

    def test_tests_added_and_removed_come_from_the_diff(self):
        diff = ("+++ b/tests/test_a.py\n+def test_one():\n+    pass\n+def test_two():\n-def test_old():\n"
                "+++ b/T.cs\n+    [Fact]\n+    [Test]\n")
        self.assertEqual(engine.count_tests(diff, engine.DEFAULTS["test_pattern"]), (4, 1))

    def test_writer_is_told_the_repo_worker_rules_and_never_to_run_the_gate(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]},
                                worker_rules="docs/agents/codex.md", gate=PY + ' -c "pass"')
        self.assertEqual(rc, 0)
        w = next(p for (c, p) in zip(s.calls, s.prompts) if c[0] == "worker")
        self.assertIn("docs/agents/codex.md", w)
        self.assertIn('-c "pass"`) or the issue tracker (bd)', w)

    def test_a_run_leaves_a_trace_of_every_worker_session(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        runs = [json.loads(l) for l in (tl.config_dir() / "traces.jsonl").read_text().splitlines()]
        self.assertEqual(len(runs), 1)
        r = runs[0]
        self.assertEqual((r["bead"], r["outcome"], r["coordinator_session"]), ("t-1", "landed", "sess1234-x"))
        self.assertEqual([x["role"] for x in r["sessions"]], ["planner", "worker", "reviewer"])
        self.assertEqual(r["sessions"][1]["ref"], "ref-write")
        self.assertTrue(any(c[:2] == ("comments", "add") and "trace=" + r["run"] in c[3] for c in self.bd_calls))

    def test_a_run_counts_its_tokens_per_session_and_in_total(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        r = json.loads((tl.config_dir() / "traces.jsonl").read_text().splitlines()[-1])
        self.assertEqual(r["sessions"][1]["tokens"], {"in": 1000, "cached": 800, "out": 50})
        self.assertEqual((r["stats"]["tokens_in"], r["stats"]["tokens_cached"], r["stats"]["tokens_out"]), (3000, 2400, 150))

    def test_wip_from_an_earlier_run_lands_as_one_titled_commit(self):
        sh("git", "checkout", "-q", "-b", "task/t-1", cwd=self.wt)
        Path(self.wt, "g.txt").write_text("from run 1\n")
        sh("git", "add", "-A", cwd=self.wt)
        sh("git", "commit", "-qm", "wip (t-1): blocked", cwd=self.wt)
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        log = tl.git("log", "--format=%s", "origin/main", cwd=str(self.wt)).splitlines()
        self.assertEqual(log, ["Add f (t-1)", "init"])
        self.assertEqual(tl.git("show", "origin/main:g.txt", cwd=str(self.wt)), "from run 1")

    def test_review_sends_an_unmet_requirement_back_to_the_same_writer(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE],
                                 "review": [review(unmet=["cant-sit-still still carries example: true"]), CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual([c[1] for c in s.calls if c[0] == "worker"], [None, "ref-write"])
        self.assertIn("cant-sit-still still carries example: true", [p for (c, p) in zip(s.calls, s.prompts)
                                                                     if c[0] == "worker"][1])

    def test_rounds_used_up_replan_once_then_stuck(self):
        rc, s = self.run_engine({"plan": [PLAN, PLAN], "write": [WRITE, WRITE],
                                 "review": [review(unmet=["x"]), review(unmet=["x"])]}, max_rounds=1)
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls].count("planner"), 2)
        self.assertIn("stuck", self.blocked[0])

    def test_red_checks_never_reach_review_and_end_the_round(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[FALSE])])
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE] * 4}, max_rounds=2, max_check_tries=2, max_replans=0)
        self.assertEqual(rc, 2)
        self.assertNotIn("reviewer", [c[0] for c in s.calls])
        self.assertEqual([c[0] for c in s.calls].count("worker"), 4)
        self.assertIn("stuck", self.blocked[0])
        self.assertEqual((self.eng.stats["writes"], self.eng.stats["rounds"]), (4, 2))

    def test_a_check_the_writer_flags_as_wrong_replans_at_once(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[FALSE])])
        flag = dict(WRITE, bad_checks=[{"cmd": FALSE, "why": "it exits 1 whatever the code does"}])
        rc, s = self.run_engine({"plan": [plan, PLAN], "write": [flag, WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "planner", "worker", "reviewer"])
        self.assertIn("exits 1 whatever the code does", (self.eng.run_dir / "replan.md").read_text())

    def test_the_planner_gets_the_repo_rules_and_is_told_the_engine_owns_the_gate(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]},
                                worker_rules="docs/agents/codex.md", gate="just check")
        self.assertIn("docs/agents/codex.md", s.prompts[0])
        self.assertIn("never put `just check` in a stage", s.prompts[0])

    def test_low_findings_are_noted_and_do_not_send_back(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [review(findings=[finding("low")])]})
        self.assertEqual(rc, 0)
        self.assertTrue(any(c[:2] == ("comments", "add") and "a low fix" in c[3] for c in self.bd_calls))

    def test_a_medium_finding_sends_back(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE],
                                 "review": [review(findings=[finding("medium")]), CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in s.calls].count("worker"), 2)

    def test_only_the_last_stages_review_checks_every_bead_requirement(self):
        two = dict(PLAN, stages=[PLAN["stages"][0], dict(PLAN["stages"][0], goal="add f again")])
        rc, s = self.run_engine({"plan": [two], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]})
        self.assertEqual(rc, 0)
        reviews = [p for (c, p) in zip(s.calls, s.prompts) if c[0] == "reviewer"]
        self.assertNotIn("every requirement", reviews[0])
        self.assertIn("every requirement", reviews[1])

    def test_writer_question_is_an_owner_decision(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [dict(WRITE, question="Keep the old save format?")]})
        self.assertEqual(rc, 2)
        self.assertIn("Keep the old save format?", self.blocked[0])
        self.assertNotIn("reviewer", [c[0] for c in s.calls])

    def test_blocked_work_is_committed_on_the_task_branch(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [review(question="A or B?")]})
        self.assertEqual(rc, 2)
        self.assertEqual(tl.git("status", "--porcelain", cwd=str(self.wt)), "")
        self.assertIn("wip (t-1)", tl.git("log", "-1", "--format=%s", "task/t-1", cwd=str(self.wt)))

    def test_review_diffs_from_the_merge_base_and_gets_the_facts(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        rv = s.prompts[2]
        self.assertNotIn("git diff HEAD", rv)
        self.assertRegex(rv, r"git diff [0-9a-f]{40}")
        for fact in ("exit 0", "wrote f", "evidence", "add f"):
            self.assertIn(fact, rv)

    def test_sigterm_still_closes(self):
        import signal as sig
        if not hasattr(sig, "SIGTERM") or os.name == "nt":
            self.skipTest("POSIX signal")
        with mock.patch.object(engine.Engine, "plan", side_effect=lambda *a, **k: os.kill(os.getpid(), sig.SIGTERM)):
            old = sig.getsignal(sig.SIGTERM)
            sig.signal(sig.SIGTERM, lambda *_: (_ for _ in ()).throw(engine.Blocked("failed: stopped (SIGTERM)")))
            try:
                rc, _ = self.run_engine({})
            finally:
                sig.signal(sig.SIGTERM, old)
        self.assertEqual(rc, 2)
        self.assertIn("stopped (SIGTERM)", self.blocked[0])

    # -- what live runs found: real process trees, real signals, reruns on a branch that already has the work
    SPAWN = "sleep 30 & echo $! > %s; "

    def child_of(self, pidfile):
        for _ in range(100):
            if pidfile.exists() and pidfile.read_text().strip():
                return int(pidfile.read_text())
            time.sleep(0.05)
        self.fail("the check never started its child")

    def assertDead(self, pid):
        for _ in range(60):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.05)
        os.kill(pid, 9)
        self.fail("pid %d outlived the engine's stop" % pid)

    def stoppable(self):
        """The engine's own SIGTERM handler (main() installs it), restored after the test."""
        import contextlib
        import signal as sig
        if os.name == "nt":
            self.skipTest("POSIX signals")

        @contextlib.contextmanager
        def cm():
            old = sig.getsignal(sig.SIGTERM)
            sig.signal(sig.SIGTERM, lambda *_: (_ for _ in ()).throw(engine.Blocked("failed: stopped (SIGTERM)")))
            try:
                yield
            finally:
                sig.signal(sig.SIGTERM, old)
        return cm()

    def test_a_slow_check_that_times_out_is_stopped_with_everything_it_started(self):
        if os.name == "nt":
            self.skipTest("POSIX process groups")
        pidfile = Path(self.tmp.name, "child.pid")
        eng = self.checks_engine(node_timeout_min=0.03)
        t = time.time()
        res = eng.run_checks({"checks": [self.SPAWN % pidfile + "wait"], "files": []}, "s")
        self.assertLess(time.time() - t, 15, "the engine waited for the check's child to end by itself")
        self.assertEqual(res[0]["exit"], 124)
        self.assertIn("timed out", res[0]["tail"])
        self.assertDead(self.child_of(pidfile))

    def test_sigterm_during_a_stage_check_stops_its_tree_and_still_closes(self):
        pidfile = Path(self.tmp.name, "child.pid")
        check = self.SPAWN % pidfile + "kill -TERM $PPID; wait"
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[check])])
        with self.stoppable():
            rc, _ = self.run_engine({"plan": [plan], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 2)
        self.assertIn("stopped (SIGTERM)", self.blocked[0])
        self.assertDead(self.child_of(pidfile))
        self.assertIn("wip (t-1)", tl.git("log", "-1", "--format=%s", "task/t-1", cwd=str(self.wt)))

    def test_sigterm_during_the_land_gate_stops_it_and_pushes_nothing(self):
        pidfile = Path(self.tmp.name, "child.pid")
        with self.stoppable():
            rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]},
                                    gate=self.SPAWN % pidfile + "kill -TERM $PPID; wait")
        self.assertEqual(rc, 2)
        self.assertIn("stopped (SIGTERM)", self.blocked[0])
        self.assertDead(self.child_of(pidfile))
        self.assertEqual(self.closed, [])
        self.assertEqual(tl.git("show", "origin/main:f.txt", cwd=str(self.wt)), "")
        self.assertEqual(tl.git("status", "--porcelain", cwd=str(self.wt)), "")

    def test_a_rerun_after_a_red_land_gate_lands_the_reviewed_work_once(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, gate=FALSE)
        self.assertEqual(rc, 2)
        first = tl.git("rev-parse", "task/t-1", cwd=str(self.wt))
        self.assertEqual(tl.git("show", "task/t-1:f.txt", cwd=str(self.wt)), "d2")
        idle = dict(WRITE, summary="re-proved, no change")
        with mock.patch.object(DelegateScript, "__call__", self.no_write(DelegateScript.__call__)):
            rc, _ = self.run_engine({"plan": [PLAN], "write": [idle], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual(tl.git("show", "origin/main:f.txt", cwd=str(self.wt)), "d2")
        self.assertEqual(tl.git("rev-list", "--count", "origin/main", "^%s~1" % first, cwd=str(self.wt)), "1")
        subjects = tl.git("log", "--format=%s", "origin/main", cwd=str(self.wt)).splitlines()
        self.assertEqual(sum("(t-1)" in x for x in subjects), 1)
        self.assertFalse(any(x.startswith("wip") for x in subjects))

    @staticmethod
    def no_write(real):
        def call(this, route, role, prompt, schema, cwd, *a, **kw):
            before = Path(cwd, "f.txt").read_text() if Path(cwd, "f.txt").exists() else None
            r = real(this, route, role, prompt, schema, cwd, *a, **kw)
            if role == "worker" and before is not None:
                Path(cwd, "f.txt").write_text(before)  # the rerun's writer changes nothing
            return r
        return call

    def test_close_reason_says_what_landed_and_a_refused_close_is_a_warning(self):
        with mock.patch.object(tl, "cmd_close", side_effect=lambda a: self.closed.append(a.reason) or 1):
            rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertIn("to main: do it", self.closed[0])
        self.assertGreater(len(self.closed[0]), 40)
        log = Path(sorted((Path(os.environ["XDG_CONFIG_HOME"]) / "task-loop" / "engine").glob("t-1-*.jsonl"))[-1])
        self.assertIn("bd refused to close", log.read_text())

    def test_owner_question_blocks_with_the_question(self):
        rc, _ = self.run_engine({"plan": [dict(PLAN, question="Which format, A or B?")]})
        self.assertEqual(rc, 2)
        self.assertIn("Which format, A or B?", self.blocked[0])
        self.assertFalse(self.closed)

    def test_invalid_output_retries_once_then_fails_and_still_closes(self):
        rc, s = self.run_engine({"plan": [{"summary": "x"}, {"summary": "x"}]})
        self.assertEqual(rc, 2)
        self.assertEqual([c[:2] for c in s.calls], [("planner", None), ("planner", "ref-plan")])
        self.assertTrue(self.blocked[0].startswith("failed: plan node"))

    def test_rounds_are_bounded(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE] * 2, "review": [review(unmet=["x"])] * 2},
                                max_rounds=2, max_replans=0)
        self.assertEqual(rc, 2)
        self.assertIn("stuck after 2 rounds", self.blocked[0])

    def test_budget_blocks(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE]}, budget_usd=0.6)
        self.assertEqual(rc, 2)
        self.assertIn("over budget", self.blocked[0])

    def test_engine_error_still_closes(self):
        with mock.patch.object(engine.Engine, "plan", side_effect=RuntimeError("boom")):
            rc, _ = self.run_engine({})
        self.assertEqual(rc, 2)
        self.assertIn("engine error RuntimeError: boom", self.blocked[0])

    def test_every_green_stage_gets_a_cross_family_review(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertIn(("reviewer", None, "openai"), s.calls)

    def test_no_sandbox_reaches_every_role_on_delegate_0_21(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, route=ROUTE % "0.21.0",
                                no_sandbox=True)
        self.assertEqual(rc, 0)
        self.assertEqual(s.unsandboxed, [("planner", True), ("worker", True), ("reviewer", True)])
        w = next(p for (c, p) in zip(s.calls, s.prompts) if c[0] == "worker")
        self.assertIn("outside a sandbox", w)
        self.assertTrue(all(x["no_sandbox"] for x in self.eng.sessions))

    def test_no_sandbox_on_delegate_0_20_is_writer_only_with_a_warning(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, route=ROUTE % "0.20.0",
                                no_sandbox=True)
        self.assertEqual(rc, 0)
        self.assertEqual(s.unsandboxed, [("planner", False), ("worker", True), ("reviewer", False)])
        self.assertIn("delegate 0.21", self.eng.log_path.read_text())

    def test_no_sandbox_needs_delegate_0_20(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, route=ROUTE % "0.19.0",
                                no_sandbox=True)
        self.assertEqual(rc, 0)
        self.assertFalse(any(u for _, u in s.unsandboxed))
        self.assertIn("delegate 0.20", self.eng.log_path.read_text())

    def test_sandbox_is_the_default_and_a_bead_label_overrides_the_config(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, route=ROUTE % "0.21.0")
        self.assertFalse(any(u for _, u in s.unsandboxed))
        w = next(p for (c, p) in zip(s.calls, s.prompts) if c[0] == "worker")
        self.assertNotIn("outside a sandbox", w)
        with mock.patch.object(tl, "show", return_value={"id": "t-1", "title": "Add f", "metadata": {},
                                                         "labels": ["no-sandbox"]}):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, route=ROUTE % "0.21.0")
        self.assertTrue(all(u for _, u in s.unsandboxed))
        with mock.patch.object(tl, "show", return_value={"id": "t-1", "title": "Add f", "metadata": {},
                                                         "labels": ["sandbox"]}):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, route=ROUTE % "0.21.0",
                                    no_sandbox=True)
        self.assertFalse(any(u for _, u in s.unsandboxed))

    def test_child_env_drops_session_identity(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_BASE_URL": "x", "CLAUDE_CODE_SESSION_ID": "s"}):
            env = engine.child_env()
        self.assertNotIn("ANTHROPIC_BASE_URL", env)
        self.assertNotIn("CLAUDE_CODE_SESSION_ID", env)
        self.assertEqual(env["DELEGATE_DEPTH"], "1")


class DelegateLauncher(unittest.TestCase):
    setUp, tearDown, fake_bd, run_engine = EngineTest.setUp, EngineTest.tearDown, EngineTest.fake_bd, EngineTest.run_engine

    def test_same_family_review_is_recorded(self):
        same = {"v": 1, "status": "done", "data": CLEAN, "ref": "r", "family": "openai", "flag": "same_family"}
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [same]})
        self.assertEqual(rc, 0)
        self.assertTrue(any(c[:2] == ("comments", "add") and "same family as the writer" in c[3] for c in self.bd_calls))

    def test_lane_out_waits_then_runs(self):
        out = {"v": 1, "status": "lane_out", "retry_after": 0, "say": "codex out"}
        rc, s = self.run_engine({"plan": [PLAN], "write": [out, WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in s.calls].count("worker"), 2)

    def test_delegate_error_is_retried_without_a_schema_reprompt(self):
        err = {"v": 1, "status": "error", "say": "state lock held >10 s"}
        rc, s = self.run_engine({"plan": [PLAN], "write": [err, WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        workers = [p for (c, p) in zip(s.calls, s.prompts) if c[0] == "worker"]
        self.assertEqual(len(workers), 2)
        self.assertNotIn("did not match the required output schema", workers[1])

    def test_network_down_waits_and_retries(self):
        down = {"v": 1, "status": "failed", "say": "API Error: Can't reach the API server — check your internet or DNS (ENOTFOUND)"}
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [down, CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in s.calls].count("reviewer"), 2)
        self.assertIn("network", self.eng.log_path.read_text())

    def test_a_logged_out_worker_pauses_without_retry_and_leaves_the_bead_open(self):
        out = {"v": 1, "status": "failed", "say": "Failed to authenticate: OAuth session expired and could not be refreshed"}
        rc, s = self.run_engine({"plan": [out, out]})
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls], ["planner"])
        self.assertEqual(self.blocked, [])
        self.assertTrue(any(c[:1] == ("update",) and "open" in c for c in self.bd_calls))
        self.assertIn("claude auth login", self.eng.log_path.read_text())

    def test_close_with_an_empty_reason_still_closes(self):
        c = engine.load_cfg(str(self.wt))
        eng = engine.Engine("t-1", str(self.wt), c)
        eng.close("failed", "", "", "")
        self.assertTrue(self.blocked)

    def test_no_lane_for_too_long_blocks(self):
        stop = {"v": 1, "status": "stop", "retry_after": 0, "say": "no adequate model"}
        rc, _ = self.run_engine({"plan": [stop] * 3}, lane_wait_min=2)
        self.assertEqual(rc, 2)
        self.assertEqual(self.blocked, [])  # a machine-wide wait is not the bead's fault: it stays open
        self.assertTrue(any(c[:1] == ("update",) and "open" in c and any("paused: no lane for plan" in x for x in c)
                            for c in self.bd_calls))

    def test_another_contract_version_blocks(self):
        rc, _ = self.run_engine({"plan": [{"v": 2, "status": "done"}]})
        self.assertEqual(rc, 2)
        self.assertIn("worker-run v2", self.blocked[0])

    def test_no_delegate_blocks_with_the_install_command(self):
        c = engine.load_cfg(str(self.wt))
        with mock.patch.object(engine, "find_route", return_value=None):
            rc = engine.Engine("t-1", str(self.wt), c).run()
        self.assertEqual(rc, 2)
        self.assertIn("claude plugin install iorlas-delegate", self.blocked[0])


class DelegateCall(unittest.TestCase):
    def test_call_delegate_runs_route_py_and_reads_its_answer(self):
        with tempfile.TemporaryDirectory() as d:
            route = Path(d, "route.py")
            route.write_text("import json,sys\nprint('chatter', file=sys.stderr)\n"
                             "print(json.dumps({'v': 1, 'status': 'done', 'data': {'argv': sys.argv[1:]}, 'ref': 'r1',"
                             " 'cost': 0, 'family': 'openai'}))\n")
            r, j = engine.call_delegate(str(route), "worker", "do it", {"type": "object"}, d, "r0", 60,
                                        Path(d, "err.log"), writer="claude", parent="p", task="t-1", title="x")
        argv = r.data["argv"]
        self.assertEqual(argv[:2], ["run", "worker"])
        for flag, val in (("--resume", "r0"), ("--authored-by", "claude"), ("--parent", "p"), ("--task", "t-1")):
            self.assertEqual(argv[argv.index(flag) + 1], val)
        self.assertEqual((r.ref, r.backend, r.error), ("r1", "openai", ""))
        self.assertIn("--unattended", argv)
        self.assertNotIn("--timeout", argv)
        self.assertNotIn("--no-sandbox", argv)

    def test_call_delegate_passes_no_sandbox(self):
        with tempfile.TemporaryDirectory() as d:
            route = Path(d, "route.py")
            route.write_text("import json,sys\nprint(json.dumps({'v': 1, 'status': 'done', 'data': {'argv': sys.argv[1:]}}))\n")
            r, _ = engine.call_delegate(str(route), "worker", "x", {"type": "object"}, d, None, 60, Path(d, "e.log"),
                                        no_sandbox=True)
        self.assertIn("--no-sandbox", r.data["argv"])

    def test_headless_args_follow_the_installed_version(self):
        base = "/h/.claude/plugins/cache/m/iorlas-delegate/%s/skills/delegate/route.py"
        self.assertEqual(engine.headless_args(base % "0.17.0", 600), ["--timeout", "600"])
        self.assertEqual(engine.headless_args(base % "0.18.0", 600), ["--headless"])
        self.assertEqual(engine.headless_args(base % "0.19.0", 600), ["--unattended"])
        self.assertEqual(engine.headless_args("/src/delegate/skills/delegate/route.py", 600), ["--unattended"])

    def test_author_flag_follows_the_installed_version(self):
        base = "/h/.claude/plugins/cache/m/iorlas-delegate/%s/skills/delegate/route.py"
        self.assertEqual(engine.author_flag(base % "0.16.0"), "--writer")
        self.assertEqual(engine.author_flag(base % "0.17.0"), "--authored-by")
        self.assertEqual(engine.author_flag(base % "1.2.0"), "--authored-by")
        self.assertEqual(engine.author_flag("/src/delegate/skills/delegate/route.py"), "--authored-by")

    def test_find_route_picks_the_newest_contract_version(self):
        with tempfile.TemporaryDirectory() as home:
            for v in ("0.9.1", "0.14.0", "0.15.2", "0.2.0"):
                p = Path(home, ".claude/plugins/cache/m/iorlas-delegate", v, "skills/delegate")
                p.mkdir(parents=True)
                (p / "route.py").write_text("")
            with mock.patch.object(engine.Path, "home", return_value=Path(home)):
                self.assertIn("0.15.2", engine.find_route())
        with tempfile.TemporaryDirectory() as home, mock.patch.object(engine.Path, "home", return_value=Path(home)):
            self.assertIsNone(engine.find_route())
            self.assertIsNone(engine.find_route(str(Path(home, "missing.py"))))


class Validate(unittest.TestCase):
    def test_schema_subset(self):
        s = engine.SCHEMAS["review"]
        self.assertEqual(engine.validate(review(findings=[finding("high")]), s), [])
        self.assertTrue(engine.validate(review(findings=[dict(finding("high"), severity="maybe")]), s))
        self.assertTrue(engine.validate({"findings": []}, s))
        self.assertTrue(engine.validate(dict(CLEAN, unmet="x"), s))
        self.assertEqual(sorted(engine.SCHEMAS), ["plan", "review", "write"])


if __name__ == "__main__":
    unittest.main()
