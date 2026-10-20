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
                                        "hard": False}], "risks": [], "question": "", "cases": []}
WRITE = {"summary": "wrote f", "checks_run": [{"cmd": "test -f f.txt", "exit": 0}], "question": "", "bad_checks": [],
         "new_cases": [], "unchecked": []}
ROUTE = "/h/.claude/plugins/cache/m/iorlas-delegate/%s/skills/delegate/route.py"
CLEAN = {"findings": [], "unmet": [], "question": "", "leftovers": [], "unchecked": []}
NS = "--no-sandbox"
BEAD = {"id": "t-1", "title": "Add f", "metadata": {}, "acceptance_criteria": "f.txt exists"}


def review(unmet=(), findings=(), question=""):
    return dict(CLEAN, unmet=list(unmet), findings=list(findings), question=question)


def finding(severity):
    return {"file": "f.txt", "line": 1, "severity": severity, "fix": "a %s fix" % severity}


class DelegateScript:
    """Fake `route.py run`: answers per role from a queue; a write creates the file like a real writer."""

    def __init__(self, answers):
        self.answers, self.calls, self.prompts = {k: list(v) for k, v in answers.items()}, [], []
        self.access = []

    def __call__(self, route, role, prompt, schema, cwd, resume, timeout, log_path, writer=None, parent="", task="",
                 title="", access=""):
        node = next(k for k, v in engine.SCHEMAS.items() if v is schema)
        self.calls.append((role, resume, writer))
        self.access.append((role, access))
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
            mock.patch.object(tl, "show", return_value=BEAD),
            mock.patch.object(tl, "comments", return_value=[]),
            mock.patch.object(tl, "cmd_close", side_effect=lambda a: self.closed.append(a.reason) or 0),
            mock.patch.object(tl, "cmd_block", side_effect=lambda a: self.blocked.append(a.why) or 0),
            mock.patch.object(tl, "cmd_land", return_value=0),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def commit_base_cfg(self, engine_cfg):
        base = Path(self.tmp.name, "base-cfg")
        if not base.exists():
            sh("git", "clone", "-q", str(Path(self.tmp.name, "o.git")), str(base), cwd=self.tmp.name)
        sh("git", "pull", "-q", "origin", "main", cwd=base)
        (base / ".task-loop.json").write_text(json.dumps({"engine": engine_cfg}))
        sh("git", "add", "-A", cwd=base)
        sh("git", "commit", "-qm", "engine config", "--allow-empty", cwd=base)
        sh("git", "push", "-q", "origin", "HEAD:main", cwd=base)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def fake_bd(self, *a, **kw):
        self.bd_calls.append(a)
        return mock.Mock(returncode=0, stdout="bead t-1: Add f\n", stderr="")

    def run_engine(self, answers, route="/fake/route.py", raw=None, **cfg):
        """Access keys (host, no_sandbox, host_beads) are committed to origin/main's .task-loop.json first: the engine
        reads them only from there. `raw` puts keys in the loaded config without committing them."""
        access = {k: cfg.pop(k) for k in ("host", "no_sandbox", "host_beads") if k in cfg}
        if access:
            self.commit_base_cfg(access)
        script = DelegateScript(answers)
        c = engine.load_cfg(str(self.wt))
        c.update(cfg)
        c.update(raw or {})
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

    def test_no_prompt_points_outside_the_worktree_the_brief_plan_and_replan_are_inline(self):
        # delegate 0.23 keeps Claude's file tools in the worktree: a path to the run dir is a file no step can read
        rc, s = self.run_engine({"plan": [PLAN, PLAN], "write": [WRITE, WRITE, WRITE],
                                 "review": [review(unmet=["a"]), CLEAN]}, max_rounds=1)
        self.assertEqual(rc, 0)
        run = str(self.eng.run_dir)
        for role, p in zip([c[0] for c in s.calls], s.prompts):
            self.assertNotIn(run, p, role)
        self.assertIn("add f", s.prompts[0] + s.prompts[1])        # the plan, inline in the write
        self.assertIn("the review still sends it back", s.prompts[3])  # the replan's reason, inline

    def test_the_planner_puts_proof_files_under_evidence(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertIn(str(self.eng.evidence_dir), s.prompts[0])
        self.assertIn("screenshots", s.prompts[0])

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
        self.assertIn("Add f", s.prompts[0])  # the brief's text itself: a worker may not read outside its worktree

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

    # lifesim 2026-10-20: `just unity-tests` ran 5-6 times per round, once as the repo check, then again inside each stage
    # check and case that starts with it (`just unity-tests && grep ...`), 2 min each
    def test_a_repo_check_inside_a_stage_check_is_not_run_again_in_the_same_round(self):
        count = Path(self.tmp.name) / "count"
        bump = PY + ' -c "open(%r, \'a\').write(\'1\')"' % str(count)
        eng = self.checks_engine(checks=[{"id": "ut", "cmd": bump, "group": "tests", "cache": False}])
        st = {"checks": [bump + " && " + PY + ' -c "pass"', bump + "; " + PY + ' -c "pass"', bump], "files": []}
        res = eng.run_checks(st, "s")
        self.assertEqual(count.read_text(), "1")
        self.assertEqual([c["exit"] for c in res], [0, 0, 0, 0])
        self.assertIn("already passed", eng.log_path.read_text())
        eng.run_checks(st, "s")  # the next round runs it again: the writer may have changed the tree
        self.assertEqual(count.read_text(), "11")

    def test_a_stage_check_that_deletes_first_or_quotes_the_command_runs_it(self):
        count = Path(self.tmp.name) / "count"
        bump = PY + ' -c "open(%r, \'a\').write(\'1\')"' % str(count)
        eng = self.checks_engine(checks=[{"id": "ut", "cmd": bump, "group": "tests", "cache": False}])
        st = {"checks": ["rm -f nothing.xml; " + bump, "echo '" + bump.replace("'", "") + " && x'"], "files": []}
        eng.run_checks(st, "s")
        self.assertEqual(count.read_text(), "11")  # the repo check, then the one after rm; the quoted text is no command

    def test_a_red_part_after_the_reused_check_still_fails(self):
        eng = self.checks_engine(checks=[{"id": "ut", "cmd": PY + ' -c "pass"', "group": "tests"}])
        res = eng.run_checks({"checks": [PY + ' -c "pass" && ' + FALSE], "files": []}, "s")
        self.assertEqual(res[-1]["exit"], 1)

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
                                worker_rules="docs/agents/codex.md", gate="just check", max_fix_rounds=0)
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
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, gate=FALSE, max_fix_rounds=0)
        self.assertEqual(rc, 2)
        self.assertIn("gate red", self.blocked[0])
        first = tl.git("rev-parse", "task/t-1", cwd=str(self.wt))
        self.assertEqual(tl.git("show", "task/t-1:f.txt", cwd=str(self.wt)), "d2")
        idle = dict(WRITE, summary="re-proved, no change")
        with mock.patch.object(DelegateScript, "__call__", self.no_write(DelegateScript.__call__)), \
                mock.patch.object(tl, "comments", return_value=[{"author": "denis", "text": "Rerun it."}]):
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

    # -- checkpoints: a rerun resumes where the last run stopped, never from scratch
    TWO = {"summary": "two", "stages": [{"goal": "stage one", "files": ["f.txt"], "checks": [HAS_F], "hard": False},
                                        {"goal": "stage two", "files": ["f.txt"], "checks": [HAS_F], "hard": False}],
           "risks": [], "question": "", "cases": []}

    def stop_at(self, role, nth):
        """The nth call of a role is where the engine is stopped (SIGTERM raises Blocked in the main thread)."""
        real, seen = DelegateScript.__call__, {"n": 0}

        def call(this, route, r, *a, **kw):
            if r == role:
                seen["n"] += 1
                if seen["n"] == nth:
                    raise engine.Blocked("failed: stopped (SIGTERM)")
            return real(this, route, r, *a, **kw)
        return mock.patch.object(DelegateScript, "__call__", call)

    def checkpoint(self):
        p = tl.config_dir() / "checkpoints" / "t-1.json"
        return json.loads(p.read_text()) if p.exists() else None

    def test_a_stop_mid_stage_2_resumes_stage_2_at_its_round_with_the_same_thread(self):
        with self.stop_at("reviewer", 3):  # stage 1 accepted; stage 2 sent back once; stopped in its second review
            rc, _ = self.run_engine({"plan": [self.TWO], "write": [WRITE, WRITE, WRITE],
                                     "review": [CLEAN, review(unmet=["more"])]})
        self.assertEqual(rc, 2)
        ck = self.checkpoint()
        self.assertEqual((ck["stage"], ck["rounds"], ck["accepted"]), (1, 1, [0]))
        self.assertEqual(ck["writer"], "ref-write")
        rc, s = self.run_engine({"write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in s.calls], ["worker", "reviewer"])  # no plan, no stage 1
        self.assertEqual(s.calls[0][1], "ref-write")                      # the writer's thread goes on
        self.assertIn("stage two", s.prompts[0])
        self.assertIn("round 2", self.eng.log_path.read_text())
        self.assertIsNone(self.checkpoint())                                # landed: nothing left to resume

    def test_reviewed_work_stopped_in_the_gate_goes_straight_to_land(self):
        with self.stoppable():
            rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, gate="kill -TERM $PPID; sleep 5")
        self.assertEqual(rc, 2)
        self.assertEqual(self.checkpoint()["step"], "land")
        rc, s = self.run_engine({})
        self.assertEqual(rc, 0)
        self.assertEqual(s.calls, [])
        self.assertEqual(tl.git("show", "origin/main:f.txt", cwd=str(self.wt)), "d2")

    def test_a_red_gate_replans_with_its_output_and_keeps_the_accepted_stages(self):
        red = PY + ' -c "import sys; print(\'RS0016 ContentPack ctor\'); sys.exit(1)"'
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE] * 3, "review": [CLEAN] * 3}, gate=red)
        self.assertEqual(rc, 2)  # two fix rounds could not make it green: the next run re-plans with the gate's output
        self.assertEqual(self.checkpoint()["step"], "gate-red")
        fix = dict(PLAN, stages=[dict(PLAN["stages"][0], goal="reconcile the API file")])
        with mock.patch.object(tl, "comments", return_value=[{"author": "denis", "text": "Main moved; reconcile it."}]):
            rc, s = self.run_engine({"plan": [fix], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer"])
        self.assertIn("already accepted", s.prompts[0])
        self.assertIn("RS0016 ContentPack ctor", (self.eng.run_dir / "replan.md").read_text())

    def test_fresh_drops_the_checkpoint(self):
        with self.stop_at("reviewer", 2):
            self.run_engine({"plan": [self.TWO], "write": [WRITE, WRITE], "review": [CLEAN]})
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, fresh=True)
        self.assertEqual(rc, 0)
        self.assertEqual(s.calls[0][0], "planner")
        self.assertNotIn("already accepted", s.prompts[0])

    def test_leftovers_are_filed_once_across_a_resume(self):
        lo = {"title": "Rename x", "why": "found in passing"}
        with self.stop_at("reviewer", 2):
            self.run_engine({"plan": [self.TWO], "write": [WRITE, WRITE], "review": [dict(CLEAN, leftovers=[lo])]})
        self.run_engine({"write": [WRITE], "review": [CLEAN]})
        self.assertEqual(sum(1 for c in self.bd_calls if c[:2] == ("create", "Rename x")), 1)

    def test_a_replan_keeps_the_stages_already_accepted(self):
        one_left = dict(self.TWO, stages=[dict(self.TWO["stages"][1], goal="stage two, again")])
        rc, s = self.run_engine({"plan": [self.TWO, one_left], "write": [WRITE] * 4,
                                 "review": [CLEAN, review(unmet=["a"]), review(unmet=["b"]), CLEAN]}, max_rounds=2)
        self.assertEqual(rc, 0)
        roles = [c[0] for c in s.calls]
        self.assertEqual(roles, ["planner", "worker", "reviewer", "worker", "reviewer", "worker", "reviewer",
                                 "planner", "worker", "reviewer"])
        replan = s.prompts[7]
        self.assertIn("already accepted", replan)
        self.assertIn("stage one", replan)
        self.assertIn("stage two, again", s.prompts[8])

    def test_a_run_killed_before_its_close_still_resumes_its_own_dirty_tree(self):
        with self.stop_at("reviewer", 2):
            self.run_engine({"plan": [self.TWO], "write": [WRITE, WRITE], "review": [CLEAN]})
        p = tl.config_dir() / "checkpoints" / "t-1.json"  # as if kill -9: no close, no wip commit
        ck = json.loads(p.read_text())
        sh("git", "reset", "-q", "--soft", "HEAD~1", cwd=self.wt)
        ck.update(closed=False, head=tl.git("rev-parse", "HEAD", cwd=str(self.wt)))
        p.write_text(json.dumps(ck))
        rc, s = self.run_engine({"write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in s.calls], ["worker", "reviewer"])

    def test_a_tree_changed_since_the_checkpoint_starts_over(self):
        with self.stop_at("reviewer", 2):
            self.run_engine({"plan": [self.TWO], "write": [WRITE, WRITE], "review": [CLEAN]})
        (self.wt / "f.txt").write_text("someone edited it\n")
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual(s.calls[0][0], "planner")
        self.assertIn("changed since", self.eng.log_path.read_text())

    def test_a_changed_bead_keeps_accepted_stages_and_replans_the_rest(self):
        with self.stop_at("reviewer", 2):
            self.run_engine({"plan": [self.TWO], "write": [WRITE, WRITE], "review": [CLEAN]})
        bead = dict(BEAD, description="Add the file f, and say hi.")
        one_left = dict(self.TWO, stages=[self.TWO["stages"][1]])
        with mock.patch.object(tl, "show", return_value=bead):
            rc, s = self.run_engine({"plan": [one_left], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer"])
        self.assertIn("already accepted", s.prompts[0])

    def test_a_failed_run_then_a_rerun_with_no_bead_edits_resumes_without_a_plan(self):
        # lifesim 2026-10-20: the engine's own close lines changed the brief, so every rerun re-planned
        with self.stop_at("reviewer", 3):
            self.run_engine({"plan": [self.TWO], "write": [WRITE, WRITE, WRITE],
                             "review": [CLEAN, review(unmet=["more"])]})
        own = [{"author": "tl-sess1234", "text": "Blocked: failed: stopped (SIGTERM)", "created_at": "2026-10-20T21:11:48Z"},
               {"author": "tl-sess1234", "text": "Reflect (engine): outcome=failed; minutes=83", "created_at": "2026-10-20T21:11:49Z"}]
        labelled = dict(BEAD, labels=["needs-owner-check"])  # the engine's own label
        with mock.patch.object(tl, "comments", return_value=own), mock.patch.object(tl, "show", return_value=labelled):
            rc, s = self.run_engine({"write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["worker", "reviewer"])
        self.assertIn("outcome=failed", s.prompts[0])  # the worker still reads how the last run ended

    def test_an_answered_ask_raised_in_a_conflict_fix_round_resumes_at_land(self):
        # lifesim-6dq0: the fix round's checkpoint was saved mid-rebase (detached HEAD), so the rerun re-planned
        other = Path(self.tmp.name, "other")
        real = DelegateScript.__call__

        def main_moves(this, route, role, *a, **kw):
            if role == "reviewer" and not other.exists():
                sh("git", "clone", "-q", str(Path(self.tmp.name, "o.git")), str(other), cwd=self.tmp.name)
                (other / "f.txt").write_text("theirs\n")
                sh("git", "add", "-A", cwd=other)
                sh("git", "commit", "-qm", "theirs", cwd=other)
                sh("git", "push", "-q", "origin", "HEAD:main", cwd=other)
            return real(this, route, role, *a, **kw)
        denied = {"v": 1, "status": "failed", "data": None, "text": "", "ref": "w1", "family": "openai",
                  "denied": [{"tool": "Bash", "input": "rg -n --glob '!**/.env*' '^<<<<<<<' ."}]}
        with mock.patch.object(DelegateScript, "__call__", main_moves):
            rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE, denied], "review": [CLEAN]}, route=ROUTE % "0.26.0")
        self.assertEqual(rc, 2)
        self.assertEqual(self.ask()["kind"], "verify")
        ck = self.checkpoint()
        self.assertEqual((ck["step"], ck["branch"]), ("land", tl.git("symbolic-ref", "--short", "HEAD", cwd=str(self.wt))))
        answer = [{"author": "denis", "text": "False positive; rerun.", "created_at": "2026-10-20T23:25:00Z"}]
        with mock.patch.object(tl, "comments", return_value=answer):
            rc, s = self.run_engine({"write": [WRITE], "review": [CLEAN]}, route=ROUTE % "0.26.0")
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["worker", "reviewer"])  # the fix round again, no plan
        self.assertIn("conflict", s.prompts[0])

    # -- reclaim: run-task takes back a bead the engine itself left blocked or claimed, never a person's
    def reclaim(self, bead, comments=(), ask=None, live=()):
        if ask:
            p = tl.config_dir() / "asks" / "t-1.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(ask))
        with mock.patch.object(tl, "show", return_value=dict(BEAD, **bead)), \
                mock.patch.object(tl, "comments", return_value=list(comments)), \
                mock.patch.object(tl, "live_actors", return_value=set(live)):
            ok, why = engine.reclaim("t-1", str(self.wt))
        updates = [c for c in self.bd_calls if c[:1] == ("update",)]
        return ok, why, updates

    BLOCKED = {"author": "tl-61ba34e7", "text": "Blocked: failed: write node produced no valid output",
               "created_at": "2026-10-20T21:11:48Z"}

    def test_reclaim_releases_a_dead_engine_claim(self):
        ok, _, up = self.reclaim({"status": "in_progress", "assignee": "tl-61ba34e7",
                                  "lease_expires_at": "2020-01-01T00:00:00Z"})
        self.assertTrue(ok)
        self.assertIn(("update", "t-1", "--assignee", ""), up)

    def test_reclaim_refuses_a_live_claim_and_a_persons_claim(self):
        ok, why, up = self.reclaim({"status": "in_progress", "assignee": "tl-61ba34e7",
                                    "lease_expires_at": "2999-01-01T00:00:00Z"})
        self.assertFalse(ok)
        self.assertIn("tl-61ba34e7", why)
        ok, why, up = self.reclaim({"status": "in_progress", "assignee": "denis"})
        self.assertFalse(ok)
        self.assertEqual(up, [])

    def test_reclaim_reopens_a_bead_the_engine_blocked_on_a_failed_run(self):
        ok, _, up = self.reclaim({"status": "blocked", "assignee": "tl-61ba34e7"}, [self.BLOCKED])
        self.assertTrue(ok)
        self.assertIn(("update", "t-1", "--status", "open", "--assignee", ""), up)

    def test_reclaim_reopens_when_a_comment_answers_the_open_ask(self):
        ask = {"id": "t-1-1", "kind": "verify", "status": "open", "brief": "x", "t": 0}
        ok, _, up = self.reclaim({"status": "blocked"}, [self.BLOCKED, {"author": "denis", "text": "Rerun.",
                                                                      "created_at": "2026-10-20T23:25:00Z"}], ask)
        self.assertTrue(ok)
        self.assertIn(("update", "t-1", "--status", "open", "--assignee", ""), up)

    def test_reclaim_leaves_blocked_what_a_person_parked_or_an_unanswered_ask_holds(self):
        later = {"author": "denis", "text": "Parked until People is designed.", "created_at": "2026-10-21T00:05:00Z"}
        ok, why, up = self.reclaim({"status": "blocked"}, [self.BLOCKED, later])
        self.assertFalse(ok)
        self.assertIn("commented after", why)
        ask = {"id": "t-1-1", "kind": "decision", "status": "open", "brief": "x", "t": 0}
        ok, why, up = self.reclaim({"status": "blocked"}, [self.BLOCKED], ask)
        self.assertFalse(ok)
        self.assertIn("t-1-1", why)
        ok, why, up = self.reclaim({"status": "blocked"}, [])
        self.assertFalse(ok)  # blocked by a person, not by the engine
        ok, why, up = self.reclaim({"status": "blocked", "dependencies": [
            {"id": "t-0", "title": "design", "status": "open", "dependency_type": "blocks"}]}, [self.BLOCKED])
        self.assertFalse(ok)
        self.assertIn("t-0", why)
        self.assertEqual(up, [])

    # -- land: fix loop after a red gate or a conflict, one land at a time, limits across runs
    def test_a_red_gate_goes_to_a_fix_round_and_lands(self):
        gate = PY + ' -c "import sys; t=open(\'f.txt\').read().strip(); print(\'gate saw\', t); sys.exit(1 if t == \'d2\' else 0)"'
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]}, gate=gate)
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "reviewer", "worker", "reviewer"])
        fix = s.prompts[3]
        self.assertIn("gate saw d2", fix)
        self.assertIn("fix", s.prompts[4].lower())
        self.assertEqual(tl.git("show", "origin/main:f.txt", cwd=str(self.wt)), "d4")
        subjects = tl.git("log", "--format=%s", "origin/main", cwd=str(self.wt)).splitlines()
        self.assertEqual(sum("(t-1)" in x for x in subjects), 1)

    def test_fix_rounds_are_limited_then_the_bead_is_stuck(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE] * 3, "review": [CLEAN] * 3}, gate=FALSE)
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls].count("worker"), 3)  # the stage, then 2 fix rounds
        self.assertIn("2 fix rounds", self.blocked[0])

    def test_a_rebase_conflict_goes_to_a_fix_round_not_blocked(self):
        other = Path(self.tmp.name, "other")
        real = DelegateScript.__call__

        def main_moves(this, route, role, *a, **kw):
            if role == "reviewer" and not other.exists():  # another task lands f.txt while this one is reviewed
                sh("git", "clone", "-q", str(Path(self.tmp.name, "o.git")), str(other), cwd=self.tmp.name)
                (other / "f.txt").write_text("theirs\n")
                sh("git", "add", "-A", cwd=other)
                sh("git", "commit", "-qm", "theirs", cwd=other)
                sh("git", "push", "-q", "origin", "HEAD:main", cwd=other)
            return real(this, route, role, *a, **kw)
        with mock.patch.object(DelegateScript, "__call__", main_moves):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("conflict", s.prompts[3])
        log = tl.git("log", "--format=%s", "origin/main", cwd=str(self.wt)).splitlines()
        self.assertEqual(log[:2], ["Add f (t-1)", "theirs"])
        self.assertEqual(tl.git("show", "origin/main:f.txt", cwd=str(self.wt)), "d4")

    def test_land_lock_is_one_per_repo_across_processes(self):
        if os.name == "nt":
            self.skipTest("POSIX flock")
        eng = self.checks_engine()
        probe = ("import fcntl,sys; f=open(sys.argv[1],'a')\n"
                 "try:\n fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB); print('free')\n"
                 "except OSError: print('held')")
        with eng.land_lock() as path:
            held = subprocess.run([sys.executable, "-c", probe, str(path)], capture_output=True, text=True).stdout
        free = subprocess.run([sys.executable, "-c", probe, str(path)], capture_output=True, text=True).stdout
        self.assertEqual((held.strip(), free.strip()), ("held", "free"))

    def test_replans_count_across_runs(self):
        with self.stop_at("reviewer", 3):  # stage 1 sent back twice -> replan; stopped in the new plan's review
            self.run_engine({"plan": [PLAN, PLAN], "write": [WRITE] * 3,
                             "review": [review(unmet=["a"]), review(unmet=["b"])]}, max_rounds=2)
        self.assertEqual(self.checkpoint()["replans"], 1)
        rc, s = self.run_engine({"write": [WRITE] * 2, "review": [review(unmet=["c"]), review(unmet=["d"])]},
                                max_rounds=2)
        self.assertEqual(rc, 2)
        self.assertIn("re-plan", self.blocked[-1])
        self.assertNotIn("planner", [c[0] for c in s.calls])

    # -- acceptance cases: from the bead's criteria, run on the last stage and in fix rounds; the writer may add
    def counter(self, name):
        f = Path(self.tmp.name, name)
        return f, PY + ' -c "open(%r, \'a\').write(\'1\')"' % str(f)

    def test_acceptance_cases_run_on_the_last_stage_only(self):
        seen, case = self.counter("case")
        plan = dict(self.TWO, cases=[{"criterion": "f.txt exists", "check": case}])
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual(seen.read_text(), "1")  # stage 2 of 2, not stage 1
        self.assertIn("f.txt exists", s.prompts[0] + s.prompts[3])

    def test_the_writer_may_add_a_case_it_is_run_and_shown_to_the_review(self):
        seen, extra = self.counter("extra")
        w = dict(WRITE, new_cases=[{"criterion": "f.txt exists", "check": extra, "why": "found an edge"}])
        rc, s = self.run_engine({"plan": [PLAN], "write": [w], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual(seen.read_text(), "1")
        rv = s.prompts[2]
        self.assertIn("added by the writer", rv)
        self.assertIn("found an edge", rv)
        self.assertEqual(self.eng.plan_data["cases"][0]["by"], "writer")

    def test_a_fix_round_runs_the_acceptance_cases_again(self):
        seen, case = self.counter("case")
        plan = dict(PLAN, cases=[{"criterion": "f.txt exists", "check": case}])
        gate = PY + ' -c "import sys; sys.exit(1 if open(\'f.txt\').read().strip() == \'d2\' else 0)"'
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE, WRITE], "review": [CLEAN, CLEAN]}, gate=gate)
        self.assertEqual(rc, 0)
        self.assertEqual(seen.read_text(), "11")

    def test_screenshots_in_evidence_are_kept_outside_the_worktree_and_named_on_the_bead(self):
        real = DelegateScript.__call__

        def shoot(this, route, role, prompt, schema, cwd, *a, **kw):
            if role == "worker":
                ev = Path(cwd, ".task", "t-1", "evidence")
                ev.mkdir(parents=True, exist_ok=True)
                (ev / "traits.png").write_bytes(b"\x89PNG fake")
            return real(this, route, role, prompt, schema, cwd, *a, **kw)
        with mock.patch.object(DelegateScript, "__call__", shoot):
            rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        kept = self.eng.run_dir / "evidence" / "traits.png"
        self.assertTrue(kept.exists())
        self.assertTrue(any(c[:2] == ("comments", "add") and str(kept) in c[3] for c in self.bd_calls))

    # -- asks: every block is an ask the owner answers; an unanswered ask is never asked again
    def ask(self):
        p = tl.config_dir() / "asks" / "t-1.json"
        return json.loads(p.read_text()) if p.exists() else None

    def test_a_planner_question_is_a_decision_ask_on_the_bead(self):
        rc, _ = self.run_engine({"plan": [dict(PLAN, question="Old format or new?")]})
        self.assertEqual(rc, 2)
        a = self.ask()
        self.assertEqual((a["kind"], a["status"], a["question"]), ("decision", "open", "Old format or new?"))
        self.assertTrue(any(c[:2] == ("comments", "add") and "%s (decision)" % a["id"] in c[3] for c in self.bd_calls))

    def test_an_ask_names_its_repo_and_runs_the_owners_notify_command(self):
        out = Path(self.tmp.name, "pushed")
        (tl.config_dir()).mkdir(parents=True, exist_ok=True)
        (tl.config_dir() / "notify").write_text('echo "$TL_ASK_KIND $TL_ASK_BEAD $TL_ASK_TEXT" > %s' % out)
        self.run_engine({"plan": [dict(PLAN, question="Old format or new?")]})
        self.assertEqual(Path(self.ask()["repo"]).resolve(), self.wt.resolve())
        for _ in range(50):
            if out.exists():
                break
            time.sleep(0.1)
        self.assertEqual(out.read_text().strip(), "decision t-1 Old format or new?")

    def test_a_used_up_replan_is_a_stuck_ask(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [review(unmet=["a"])]},
                                max_rounds=1, max_replans=0)
        self.assertEqual(rc, 2)
        self.assertEqual(self.ask()["kind"], "stuck")

    def test_a_machine_pause_is_no_ask(self):
        out = {"v": 1, "status": "failed", "say": "Failed to authenticate: OAuth session expired and could not be refreshed"}
        self.run_engine({"plan": [out]})
        self.assertIsNone(self.ask())

    def test_an_open_ask_with_an_unchanged_bead_waits_without_any_ai_step(self):
        self.run_engine({"plan": [dict(PLAN, question="Old format or new?")]})
        blocks = len(self.blocked)
        rc, s = self.run_engine({})
        self.assertEqual(rc, 2)
        self.assertEqual(s.calls, [])
        self.assertEqual(len(self.blocked), blocks)  # the bead stays blocked as it was; nothing re-asked
        self.assertIn("for the owner's answer", self.eng.log_path.read_text())
        self.assertEqual(self.ask()["status"], "open")

    def test_an_owner_comment_answers_the_ask_and_the_bead_goes_on(self):
        self.run_engine({"plan": [dict(PLAN, question="Old format or new?")]})
        with mock.patch.object(tl, "comments", return_value=[{"author": "denis", "text": "Old format."}]):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual(s.calls[0][0], "planner")
        self.assertEqual(self.ask()["status"], "answered")

    def test_an_unchecked_requirement_stops_the_land_with_a_verify_ask(self):
        r = dict(CLEAN, unchecked=[{"what": "the cited spec link did not open", "kind": "link"}])
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [r]})
        self.assertEqual(rc, 2)
        a = self.ask()
        self.assertEqual(a["kind"], "verify")
        self.assertIn("the cited spec link did not open", a["question"])
        self.assertEqual(tl.git("show", "origin/main:f.txt", cwd=str(self.wt)), "")

    def test_an_answered_verify_ask_goes_straight_to_land(self):
        r = dict(CLEAN, unchecked=[{"what": "the cited spec link did not open", "kind": "link"}])
        self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [r]})
        with mock.patch.object(tl, "comments", return_value=[{"author": "denis", "text": "Link is fine, checked."}]):
            rc, s = self.run_engine({})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(s.calls, [])
        self.assertEqual(tl.git("show", "origin/main:f.txt", cwd=str(self.wt)), "d2")

    def test_what_the_writer_could_not_check_goes_to_the_review_which_decides(self):
        # lifesim-jjso: the writer could not run Unity, the engine's cases then did; the land must not stop on that
        w = dict(WRITE, unchecked=[{"what": "the Unity tests need the host", "kind": "case"}])
        rc, s = self.run_engine({"plan": [PLAN], "write": [w], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertIn("the Unity tests need the host", s.prompts[2])

    def test_an_unchecked_minor_item_lands_and_labels_the_bead_for_a_look(self):
        r = dict(CLEAN, unchecked=[{"what": "the tooltip wording on a phone", "kind": "other"}])
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [r]})
        self.assertEqual(rc, 0)
        self.assertIn(("label", "add", "t-1", "needs-owner-check"), [c[:4] for c in self.bd_calls])

    # -- intake: a bead the engine cannot judge is a ticket ask, before any AI step
    def test_a_bead_without_acceptance_criteria_is_a_ticket_and_never_planned(self):
        with mock.patch.object(tl, "show", return_value={"id": "t-1", "title": "Add f", "metadata": {}, "description": "Add f."}):
            rc, s = self.run_engine({"plan": [PLAN]})
        self.assertEqual(rc, 2)
        self.assertEqual(s.calls, [])
        self.assertEqual(self.ask()["kind"], "ticket")

    def test_criteria_in_a_description_section_count(self):
        bead = {"id": "t-1", "title": "Add f", "metadata": {},
                "description": "Add f.\n\n## Acceptance Criteria\n\nf.txt exists.\n\n## Touches\n\nf.txt"}
        with mock.patch.object(tl, "show", return_value=bead):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)

    def test_a_plan_of_more_than_three_stages_is_a_split_ticket(self):
        four = dict(PLAN, stages=[dict(PLAN["stages"][0], goal="part %d" % k) for k in range(4)])
        rc, s = self.run_engine({"plan": [four]})
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls], ["planner"])
        a = self.ask()
        self.assertEqual(a["kind"], "ticket")
        self.assertIn("part 3", a["question"])

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
        self.assertEqual(s.access, [("planner", NS), ("worker", NS), ("reviewer", NS)])
        w = next(p for (c, p) in zip(s.calls, s.prompts) if c[0] == "worker")
        self.assertIn("You have the host", w)
        self.assertTrue(all(x["host"] for x in self.eng.sessions))

    def test_no_sandbox_on_delegate_0_20_is_writer_only_with_a_warning(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, route=ROUTE % "0.20.0",
                                no_sandbox=True)
        self.assertEqual(rc, 0)
        self.assertEqual(s.access, [("planner", ""), ("worker", NS), ("reviewer", "")])
        self.assertIn("delegate 0.21", self.eng.log_path.read_text())

    def test_no_sandbox_needs_delegate_0_20(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, route=ROUTE % "0.19.0",
                                no_sandbox=True)
        self.assertEqual(rc, 0)
        self.assertFalse(any(u for _, u in s.access))
        self.assertIn("delegate 0.20", self.eng.log_path.read_text())

    def test_sandbox_is_the_default_and_a_bead_label_overrides_the_config(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, route=ROUTE % "0.21.0")
        self.assertFalse(any(u for _, u in s.access))
        w = next(p for (c, p) in zip(s.calls, s.prompts) if c[0] == "worker")
        self.assertNotIn("You have the host", w)
        with mock.patch.object(tl, "show", return_value={"id": "t-1", "title": "Add f", "metadata": {}, "acceptance_criteria": "f.txt exists",
                                                         "labels": ["no-sandbox"]}):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, route=ROUTE % "0.21.0",
                                    host_beads=["t-1"])
        self.assertTrue(all(u for _, u in s.access))
        with mock.patch.object(tl, "show", return_value={"id": "t-1", "title": "Add f", "metadata": {}, "acceptance_criteria": "f.txt exists",
                                                         "labels": ["sandbox"]}):
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, route=ROUTE % "0.21.0",
                                    no_sandbox=True)
        self.assertFalse(any(u for _, u in s.access))

    # -- delegate 0.23: --host on write steps only; --no-sandbox below it
    def test_host_on_delegate_0_23_goes_to_the_write_step_only(self):
        for cfg in ({"host": True}, {"no_sandbox": True}):  # no_sandbox: the 0.6 name, still read
            rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, route=ROUTE % "0.23.0", **cfg)
            self.assertEqual(rc, 0)
            self.assertEqual(s.access, [("planner", ""), ("worker", "--host"), ("reviewer", "")], cfg)
            w = next(p for (c, p) in zip(s.calls, s.prompts) if c[0] == "worker")
            self.assertIn("You have the host", w)
            self.assertEqual([x["host"] for x in self.eng.sessions], [False, True, False])

    def test_host_on_delegate_0_24_goes_to_every_step(self):
        # 0.24: any lane takes --host; Claude read steps get Bash with it (the planner can see what the writer will need)
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, route=ROUTE % "0.24.0", host=True)
        self.assertEqual(rc, 0)
        self.assertEqual(s.access, [("planner", "--host"), ("worker", "--host"), ("reviewer", "--host")])
        self.assertIn("may run commands to check facts", s.prompts[0])

    def test_a_host_label_alone_grants_nothing(self):
        # a worker with Bash can label its own bead: only the committed config on the base branch grants the host
        for label in ("host", "no-sandbox"):
            with mock.patch.object(tl, "show", return_value={"id": "t-1", "title": "Add f", "metadata": {}, "acceptance_criteria": "f.txt exists", "labels": [label]}):
                rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, route=ROUTE % "0.23.0")
            self.assertEqual(s.access[1], ("worker", ""), label)
            self.assertIn("label %s is ignored" % label, self.eng.log_path.read_text())

    def test_host_beads_on_the_base_branch_grant_the_host_to_one_bead(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, route=ROUTE % "0.23.0",
                                host_beads=["t-1"])
        self.assertEqual(s.access[1], ("worker", "--host"))
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, route=ROUTE % "0.23.0",
                                host_beads=["t-2"])
        self.assertEqual(s.access[1], ("worker", ""))

    def test_host_in_a_checkout_config_is_not_enough(self):
        # the main checkout's or the worktree's own .task-loop.json can be edited by a worker; origin/main cannot
        (self.wt / ".task-loop.json").write_text(json.dumps({"engine": {"host": True}}))
        sh("git", "add", "-A", cwd=self.wt)
        sh("git", "commit", "-qm", "local only, never pushed", cwd=self.wt)
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, route=ROUTE % "0.23.0",
                                raw={"host": True, "host_beads": ["t-1"]})
        self.assertEqual(s.access[1], ("worker", ""))

    def test_run_task_refuses_the_main_checkout(self):
        a = mock.Mock(id="t-1", worktree=str(self.wt), slot=None, dry_run=True, fresh=False, quiet=True)
        with mock.patch.object(tl, "repo_root", return_value=str(self.wt)), \
                mock.patch.object(engine, "Engine") as made:
            rc = engine.main(a)
        self.assertEqual(rc, 1)
        made.assert_not_called()

    def test_a_denied_command_with_a_valid_answer_is_a_warning_in_the_trace(self):
        ok = {"v": 1, "status": "done", "data": WRITE, "ref": "w1", "family": "claude",
              "denied": [{"tool": "Bash", "input": "curl -X POST https://x"}]}
        rc, s = self.run_engine({"plan": [PLAN], "write": [ok, WRITE], "review": [CLEAN]}, route=ROUTE % "0.23.0")
        self.assertEqual(rc, 0)  # (a raw answer writes no f.txt: the stage's check sends it to a second write)
        self.assertIn("write was denied `curl -X POST https://x`", self.eng.log_path.read_text())
        self.assertEqual(self.eng.sessions[1]["denied"], ok["denied"])

    def test_a_denied_command_with_no_valid_answer_needs_a_human_at_once(self):
        stuck = {"v": 1, "status": "done", "data": None, "text": "I could not run it", "ref": "w1", "family": "claude",
                 "denied": [{"tool": "Bash", "input": "unity open client"}]}
        rc, s = self.run_engine({"plan": [PLAN], "write": [stuck, WRITE], "review": [CLEAN]}, route=ROUTE % "0.23.0")
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls].count("worker"), 1)
        self.assertIn("needs a human", self.blocked[0])
        self.assertIn("unity open client", self.blocked[0])

    def test_a_second_denied_write_in_a_bead_needs_a_human_with_every_denied_command(self):
        first = {"v": 1, "status": "done", "data": WRITE, "ref": "w1", "family": "claude",
                 "denied": [{"tool": "Bash", "input": "git checkout x && pick"}]}
        second = {"v": 1, "status": "done", "data": WRITE, "ref": "w2", "family": "openai",
                  "denied": [{"tool": "shell", "input": "git restore x; pick"}]}
        rc, s = self.run_engine({"plan": [PLAN], "write": [first, second, WRITE], "review": [CLEAN]}, route=ROUTE % "0.24.0")
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls].count("worker"), 2)
        self.assertIn("needs a human", self.blocked[0])
        for cmd in ("git checkout x && pick", "git restore x; pick"):
            self.assertIn(cmd, self.blocked[0])

    def test_denied_writes_count_across_runs_of_a_bead(self):
        first = {"v": 1, "status": "done", "data": WRITE, "ref": "w1", "family": "claude",
                 "denied": [{"tool": "Bash", "input": "curl -X POST x"}]}
        with self.stop_at("worker", 2):
            self.run_engine({"plan": [PLAN], "write": [first]}, route=ROUTE % "0.24.0")
        again = dict(first, denied=[{"tool": "Bash", "input": "curl --data @f x"}])
        rc, _ = self.run_engine({"write": [again, WRITE], "review": [CLEAN]}, route=ROUTE % "0.24.0")
        self.assertEqual(rc, 2)
        self.assertIn("curl -X POST x", self.blocked[-1])
        self.assertIn("curl --data @f x", self.blocked[-1])

    def test_the_secrets_tripwire_stops_the_bead_for_a_human_at_once(self):
        # delegate 0.25: a Codex command on a credential path stops the worker: failed, the command in denied
        trip = {"v": 1, "status": "failed", "data": None, "text": "", "ref": "w1", "family": "openai",
                "say": "stopped: the command touches a credential file",
                "denied": [{"tool": "shell", "input": "cat .env"}]}
        rc, s = self.run_engine({"plan": [PLAN], "write": [trip, WRITE], "review": [CLEAN]}, route=ROUTE % "0.25.0")
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls].count("worker"), 1)
        self.assertIn("needs a human", self.blocked[0])
        self.assertIn("cat .env", self.blocked[0])
        self.assertEqual(self.ask()["kind"], "verify")

    def test_error_from_0_23_is_permanent(self):
        err = {"v": 1, "status": "error", "say": "--host: the planner chain has no allowed lane"}
        rc, s = self.run_engine({"plan": [err, PLAN]}, route=ROUTE % "0.23.0")
        self.assertEqual(rc, 2)
        self.assertEqual(len(s.calls), 1)
        self.assertIn("no allowed lane", self.blocked[0])

    def test_error_on_a_resume_from_0_23_retries_once_as_a_new_thread(self):
        err = {"v": 1, "status": "error", "say": "--resume: the host flag differs from the original run"}
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, err, WRITE], "review": [review(unmet=["more"]), CLEAN]},
                                route=ROUTE % "0.23.0")
        self.assertEqual(rc, 0)
        workers = [c for c in s.calls if c[0] == "worker"]
        self.assertEqual(len(workers), 3)
        self.assertIsNotNone(workers[1][1])  # the second write resumed the writer's thread
        self.assertIsNone(workers[2][1])     # the error made it start a new one

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

    def test_delegate_error_before_0_23_is_retried_without_a_schema_reprompt(self):
        err = {"v": 1, "status": "error", "say": "state lock held >10 s"}
        rc, s = self.run_engine({"plan": [PLAN], "write": [err, WRITE], "review": [CLEAN]}, route=ROUTE % "0.22.0")
        self.assertEqual(rc, 0)
        workers = [p for (c, p) in zip(s.calls, s.prompts) if c[0] == "worker"]
        self.assertEqual(len(workers), 2)
        self.assertNotIn("did not match the required output schema", workers[1])

    # lifesim 2026-10-20: "never ask about permissions" kept a sandboxed Codex from compiling; each bead lost 1-2 rounds
    # to compile and analyzer errors the engine's checks then found
    def write_prompt(self, version, **cfg):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]}, route=ROUTE % version, **cfg)
        self.assertEqual(rc, 0, self.blocked)
        return next(p for (c, p) in zip(s.calls, s.prompts) if c[0] == "worker")

    def test_a_sandboxed_writer_on_delegate_0_24_runs_the_checks_and_may_escalate_one_command(self):
        p = self.write_prompt("0.26.0")
        self.assertIn("ask once to run that exact command outside it", p)
        self.assertIn("compile", p)
        self.assertNotIn("never ask about permissions", p)
        self.assertNotIn("Run only the quick checks", p)

    def test_a_sandboxed_writer_before_delegate_0_24_keeps_to_quick_checks(self):
        p = self.write_prompt("0.22.0")
        self.assertIn("Run only the quick checks", p)
        self.assertIn("never ask about permissions", p)
        self.assertNotIn("outside it", p)

    def test_a_writer_with_the_host_is_told_it_has_the_host(self):
        with mock.patch.object(engine.Engine, "granted_host", return_value=True):  # as if .task-loop.json granted it
            p = self.write_prompt("0.26.0")
        self.assertIn("You have the host", p)
        self.assertNotIn("never ask about permissions", p)

    def test_network_down_waits_and_retries(self):
        down = {"v": 1, "status": "failed", "say": "API Error: Can't reach the API server — check your internet or DNS (ENOTFOUND)"}
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [down, CLEAN]})
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in s.calls].count("reviewer"), 2)
        self.assertIn("network", self.eng.log_path.read_text())

    # lifesim 2026-10-20: woken from sleep, Codex ended its turn after 12 s with a vendor error and no tokens; delegate
    # 0.26 answered failed and the engine closed two beads as failed
    QUICK = {"v": 1, "status": "failed", "data": None, "ref": "w1", "family": "openai", "tokens": None,
             "say": "failed: codex: workspace routing discovery failed"}

    def test_a_failure_before_any_work_waits_and_retries(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [self.QUICK, self.QUICK, WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual([c[0] for c in s.calls].count("worker"), 3)
        log = self.eng.log_path.read_text()
        self.assertIn("failed before any work", log)
        self.assertNotIn("did not match the required output schema", "".join(s.prompts))

    def test_a_failure_before_any_work_that_keeps_coming_pauses_the_bead_open(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [self.QUICK] * 20}, lane_wait_min=5)
        self.assertEqual(rc, 2)
        self.assertEqual(self.blocked, [])  # paused, not failed: the bead stays open for the next run
        self.assertTrue(any(c[:1] == ("update",) and "open" in c for c in self.bd_calls))
        self.assertIn("workspace routing discovery failed", self.eng.log_path.read_text())
        self.assertLess([c[0] for c in s.calls].count("worker"), 20)

    def test_a_failure_after_work_still_fails(self):
        worked = dict(self.QUICK, tokens={"in": 90000, "cached": 0, "out": 4000})
        rc, s = self.run_engine({"plan": [PLAN], "write": [worked, worked]})
        self.assertEqual(rc, 2)
        self.assertTrue(self.blocked and self.blocked[0].startswith("failed:"))

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

    def test_a_lane_out_for_long_pauses_at_once_and_frees_the_slot(self):
        later = {"v": 1, "status": "lane_out", "retry_after": time.time() + 3 * 3600, "say": "codex out until 21:00"}
        rc, s = self.run_engine({"plan": [PLAN], "write": [later]})
        self.assertEqual(rc, 2)
        self.assertEqual([c[0] for c in s.calls].count("worker"), 1)  # no hour of sleeping in the slot
        self.assertEqual(self.blocked, [])
        self.assertTrue(any(c[:1] == ("update",) and "open" in c and any("paused: no lane for write until" in x for x in c)
                            for c in self.bd_calls))

    def test_a_bead_branch_left_in_another_clean_slot_is_resumed_here(self):
        sh("git", "checkout", "-q", "-b", "task/t-1", cwd=self.wt)
        Path(self.wt, "g.txt").write_text("from slot s2\n")
        sh("git", "add", "-A", cwd=self.wt)
        sh("git", "commit", "-qm", "wip (t-1): paused", cwd=self.wt)
        sh("git", "checkout", "-q", "--detach", cwd=self.wt)
        other = Path(self.tmp.name, "s2")
        sh("git", "worktree", "add", "-q", str(other), "task/t-1", cwd=self.wt)
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 0, self.blocked)
        self.assertEqual(tl.git("show", "origin/main:g.txt", cwd=str(self.wt)), "from slot s2")
        self.assertEqual(tl.git("symbolic-ref", "-q", "HEAD", cwd=str(other)), "")  # s2 let go of the branch

    def test_a_bead_branch_with_uncommitted_work_in_another_slot_is_never_taken(self):
        sh("git", "branch", "task/t-1", cwd=self.wt)
        other = Path(self.tmp.name, "s2")
        sh("git", "worktree", "add", "-q", str(other), "task/t-1", cwd=self.wt)
        Path(other, "dirty.txt").write_text("someone's work\n")
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "review": [CLEAN]})
        self.assertEqual(rc, 2)
        self.assertIn(str(other), self.blocked[0])
        self.assertTrue(Path(other, "dirty.txt").exists())

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

    def test_call_delegate_passes_the_access_flag(self):
        with tempfile.TemporaryDirectory() as d:
            route = Path(d, "route.py")
            route.write_text("import json,sys\nprint(json.dumps({'v': 1, 'status': 'done', 'data': {'argv': sys.argv[1:]}}))\n")
            r, _ = engine.call_delegate(str(route), "worker", "x", {"type": "object"}, d, None, 60, Path(d, "e.log"),
                                        access="--host")
        self.assertIn("--host", r.data["argv"])

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
