import json
import os
import subprocess
import sys
import tempfile
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
WRITE = {"summary": "wrote f", "checks_run": [{"cmd": "test -f f.txt", "exit": 0}], "question": ""}
ACCEPT_V = {"verdict": "accept", "checks": [{"cmd": "test -f f.txt", "exit": 0, "tail": ""}], "gaps": [],
            "risk_flags": [], "outside_touches": [], "tests_added": 0, "tests_removed": 0}
GAPS_V = dict(ACCEPT_V, verdict="gaps", gaps=["f.txt is empty"])


def judge(decision, question=""):
    return {"decision": decision, "why": decision + " because", "question": question, "leftovers": []}


class DelegateScript:
    """Fake `route.py run`: answers per role from a queue; a write creates the file like a real writer."""

    def __init__(self, answers):
        self.answers, self.calls, self.prompts = {k: list(v) for k, v in answers.items()}, [], []

    def __call__(self, route, role, prompt, schema, cwd, resume, timeout, log_path, writer=None, parent="", task="",
                 title=""):
        node = next(k for k, v in engine.SCHEMAS.items() if v is schema)
        self.calls.append((role, resume, writer))
        self.prompts.append(prompt)
        a = self.answers[node].pop(0)
        if isinstance(a, dict) and a.get("v") is not None:
            j = a
        else:
            if node == "write":
                Path(cwd, "f.txt").write_text("d%d\n" % len(self.calls))
            j = {"v": 1, "status": "done", "data": a, "ref": "ref-" + node, "cost": 0.5, "secs": 1,
                 "family": "openai" if node in ("write", "verify", "judge") else "claude", "lane": "L", "model": "m",
                 "effort": "e", "git_violation": []}
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

    def run_engine(self, answers, **cfg):
        script = DelegateScript(answers)
        c = engine.load_cfg(str(self.wt))
        c.update(cfg)
        with mock.patch.object(engine, "find_route", return_value="/fake/route.py"), \
                mock.patch.object(engine, "call_delegate", script), mock.patch.object(engine.time, "sleep"):
            rc = engine.Engine("t-1", str(self.wt), c).run()
        return rc, script

    def test_happy_path_lands_and_closes(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "verify": [ACCEPT_V], "judge": [judge("accept")]})
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in s.calls], ["planner", "worker", "light", "light"])
        self.assertTrue(self.closed and self.closed[0].startswith("merged "))
        self.assertEqual(tl.git("show", "origin/main:f.txt", cwd=str(self.wt)), "d2")
        self.assertTrue(any(c[:2] == ("comments", "add") and "Reflect (engine)" in c[3] for c in self.bd_calls))

    def test_a_run_leaves_a_trace_of_every_worker_session(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "verify": [ACCEPT_V], "judge": [judge("accept")]})
        self.assertEqual(rc, 0)
        runs = [json.loads(l) for l in (tl.config_dir() / "traces.jsonl").read_text().splitlines()]
        self.assertEqual(len(runs), 1)
        r = runs[0]
        self.assertEqual((r["bead"], r["outcome"], r["coordinator_session"]), ("t-1", "landed", "sess1234-x"))
        self.assertEqual([x["role"] for x in r["sessions"]], ["planner", "worker", "light", "light"])
        self.assertEqual(r["sessions"][1]["ref"], "ref-write")
        self.assertTrue(any(c[:2] == ("comments", "add") and "trace=" + r["run"] in c[3] for c in self.bd_calls))

    def test_wip_from_an_earlier_run_lands_as_one_titled_commit(self):
        sh("git", "checkout", "-q", "-b", "task/t-1", cwd=self.wt)
        Path(self.wt, "g.txt").write_text("from run 1\n")
        sh("git", "add", "-A", cwd=self.wt)
        sh("git", "commit", "-qm", "wip (t-1): blocked", cwd=self.wt)
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "verify": [ACCEPT_V], "judge": [judge("accept")]})
        self.assertEqual(rc, 0)
        log = tl.git("log", "--format=%s", "origin/main", cwd=str(self.wt)).splitlines()
        self.assertEqual(log, ["Add f (t-1)", "init"])
        self.assertEqual(tl.git("show", "origin/main:g.txt", cwd=str(self.wt)), "from run 1")

    def test_rework_resumes_the_same_writer(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE], "verify": [GAPS_V, ACCEPT_V],
                                 "judge": [judge("rework"), judge("accept")]})
        self.assertEqual(rc, 0)
        self.assertEqual([c[1] for c in s.calls if c[0] == "worker"], [None, "ref-write"])

    def test_replan_starts_over_once_then_blocks(self):
        rc, s = self.run_engine({"plan": [PLAN, PLAN], "write": [WRITE, WRITE], "verify": [ACCEPT_V, ACCEPT_V],
                                 "judge": [judge("replan"), judge("replan")]})
        self.assertEqual(rc, 2)
        self.assertIn("re-plan", self.blocked[0])

    def test_failed_engine_check_is_never_accepted(self):
        plan = dict(PLAN, stages=[dict(PLAN["stages"][0], checks=[FALSE])])
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE] * 2, "verify": [ACCEPT_V] * 2,
                                 "judge": [judge("accept")] * 2}, max_rounds=2)
        self.assertEqual(rc, 2)
        self.assertIn("not accepted after 2 rounds", self.blocked[0])

    def test_blocked_work_is_committed_on_the_task_branch(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "verify": [ACCEPT_V],
                                 "judge": [judge("block", "A or B?")]})
        self.assertEqual(rc, 2)
        self.assertEqual(tl.git("status", "--porcelain", cwd=str(self.wt)), "")
        self.assertIn("wip (t-1)", tl.git("log", "-1", "--format=%s", "task/t-1", cwd=str(self.wt)))

    def test_verifier_diffs_from_the_merge_base(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "verify": [ACCEPT_V], "judge": [judge("accept")]})
        self.assertEqual(rc, 0)
        base = tl.git("rev-parse", "origin/main~0", cwd=str(self.wt))
        self.assertNotIn("git diff HEAD", s.prompts[2])
        self.assertRegex(s.prompts[2], r"git diff [0-9a-f]{40}")

    def test_judge_sees_the_engines_checks_not_the_verifiers_copy(self):
        lying = dict(ACCEPT_V, checks=[{"cmd": "dotnet test", "exit": 124, "tail": "timeout"}])
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "verify": [lying], "judge": [judge("accept")]})
        self.assertEqual(rc, 0)
        self.assertNotIn('"exit": 124', s.prompts[3])

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

    def test_close_reason_says_what_landed_and_a_refused_close_is_a_warning(self):
        with mock.patch.object(tl, "cmd_close", side_effect=lambda a: self.closed.append(a.reason) or 1):
            rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "verify": [ACCEPT_V], "judge": [judge("accept")]})
        self.assertIn("to main: do it", self.closed[0])
        self.assertGreater(len(self.closed[0]), 40)
        log = Path(sorted((Path(os.environ["XDG_CONFIG_HOME"]) / "task-loop" / "engine").glob("t-1-*.jsonl"))[-1])
        self.assertIn("bd refused to close", log.read_text())

    def test_judge_block_without_a_question_is_an_engine_failure(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE], "verify": [ACCEPT_V],
                                 "judge": [judge("block")]})
        self.assertEqual(rc, 2)
        self.assertTrue(self.blocked[0].startswith("failed: judge blocked without an owner question"))

    def test_verifier_and_judge_get_the_facts_in_the_prompt(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "verify": [ACCEPT_V], "judge": [judge("accept")]})
        self.assertEqual(rc, 0)
        verify, judge_prompt = s.prompts[2], s.prompts[3]
        self.assertIn("exit 0", verify)
        self.assertIn("wrote f", verify)
        self.assertIn("evidence", verify)
        self.assertIn('"checks_run_by_engine"', judge_prompt)

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
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE] * 2, "verify": [GAPS_V] * 2,
                                 "judge": [judge("rework")] * 2}, max_rounds=2)
        self.assertEqual(rc, 2)
        self.assertIn("not accepted after 2 rounds", self.blocked[0])

    def test_budget_blocks(self):
        rc, _ = self.run_engine({"plan": [PLAN], "write": [WRITE]}, budget_usd=0.6)
        self.assertEqual(rc, 2)
        self.assertIn("over budget", self.blocked[0])

    def test_engine_error_still_closes(self):
        with mock.patch.object(engine.Engine, "plan", side_effect=RuntimeError("boom")):
            rc, _ = self.run_engine({})
        self.assertEqual(rc, 2)
        self.assertIn("engine error RuntimeError: boom", self.blocked[0])

    def test_risky_stage_gets_a_cross_family_review(self):
        plan = dict(PLAN, risks=[{"what": "saved format", "check": "load old file"}])
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE], "verify": [ACCEPT_V],
                                 "review": [{"findings": []}], "judge": [judge("accept")]})
        self.assertEqual(rc, 0)
        self.assertIn(("reviewer", None, "openai"), s.calls)

    def test_child_env_drops_session_identity(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_BASE_URL": "x", "CLAUDE_CODE_SESSION_ID": "s"}):
            env = engine.child_env()
        self.assertNotIn("ANTHROPIC_BASE_URL", env)
        self.assertNotIn("CLAUDE_CODE_SESSION_ID", env)
        self.assertEqual(env["DELEGATE_DEPTH"], "1")


class DelegateLauncher(unittest.TestCase):
    setUp, tearDown, fake_bd, run_engine = EngineTest.setUp, EngineTest.tearDown, EngineTest.fake_bd, EngineTest.run_engine

    def test_same_family_review_is_recorded(self):
        plan = dict(PLAN, risks=[{"what": "saved format", "check": "load old file"}])
        same = {"v": 1, "status": "done", "data": {"findings": []}, "ref": "r", "family": "openai", "flag": "same_family"}
        rc, s = self.run_engine({"plan": [plan], "write": [WRITE], "verify": [ACCEPT_V], "review": [same],
                                 "judge": [judge("accept")]})
        self.assertEqual(rc, 0)
        self.assertTrue(any(c[:2] == ("comments", "add") and "same family as the writer" in c[3] for c in self.bd_calls))
        self.assertIn('"same_family": true', s.prompts[-1])

    def test_lane_out_waits_then_runs(self):
        out = {"v": 1, "status": "lane_out", "retry_after": 0, "say": "codex out"}
        rc, s = self.run_engine({"plan": [PLAN], "write": [out, WRITE], "verify": [ACCEPT_V], "judge": [judge("accept")]})
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in s.calls].count("worker"), 2)

    def test_delegate_error_is_retried_without_a_schema_reprompt(self):
        err = {"v": 1, "status": "error", "say": "state lock held >10 s"}
        rc, s = self.run_engine({"plan": [PLAN], "write": [err, WRITE], "verify": [ACCEPT_V], "judge": [judge("accept")]})
        self.assertEqual(rc, 0)
        workers = [p for (c, p) in zip(s.calls, s.prompts) if c[0] == "worker"]
        self.assertEqual(len(workers), 2)
        self.assertNotIn("did not match the required output schema", workers[1])

    def test_no_lane_for_too_long_blocks(self):
        stop = {"v": 1, "status": "stop", "retry_after": 0, "say": "no adequate model"}
        rc, _ = self.run_engine({"plan": [stop] * 3}, lane_wait_min=2)
        self.assertEqual(rc, 2)
        self.assertIn("paused: no lane for plan", self.blocked[0])

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
        s = engine.SCHEMAS["judge"]
        self.assertEqual(engine.validate(judge("accept"), s), [])
        self.assertTrue(engine.validate(dict(judge("accept"), decision="maybe"), s))
        self.assertTrue(engine.validate({"decision": "accept"}, s))
        self.assertTrue(engine.validate(dict(ACCEPT_V, tests_added=True), engine.SCHEMAS["verify"]))


if __name__ == "__main__":
    unittest.main()
