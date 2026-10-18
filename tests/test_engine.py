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


PLAN = {"summary": "do it", "stages": [{"goal": "add f", "files": ["f.txt"], "checks": ["test -f f.txt"],
                                        "hard": False}], "risks": [], "question": ""}
WRITE = {"summary": "wrote f", "checks_run": [{"cmd": "test -f f.txt", "exit": 0}], "question": ""}
ACCEPT_V = {"verdict": "accept", "checks": [{"cmd": "test -f f.txt", "exit": 0, "tail": ""}], "gaps": [],
            "risk_flags": [], "outside_touches": [], "tests_added": 0, "tests_removed": 0}
GAPS_V = dict(ACCEPT_V, verdict="gaps", gaps=["f.txt is empty"])


def judge(decision, question=""):
    return {"decision": decision, "why": decision + " because", "question": question, "leftovers": []}


class Script:
    """Fake workers: each node pops its next answer; write creates a file like a real writer would."""

    def __init__(self, wt, answers):
        self.wt, self.answers, self.calls = wt, {k: list(v) for k, v in answers.items()}, []

    def __call__(self, model, prompt, schema, cwd, write, resume, timeout, log_path):
        node = next(k for k, v in engine.SCHEMAS.items() if v is schema)
        self.calls.append((node, resume))
        data = self.answers[node].pop(0)
        if node == "write":
            Path(cwd, "f.txt").write_text("x%d\n" % len(self.calls))
        return engine.Result(data=data, ref="thread-%s" % node, cost=0.5, secs=1, backend="codex")


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
            mock.patch.object(engine, "claude_available", return_value=False),
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
        script = Script(self.wt, answers)
        c = engine.load_cfg(str(self.wt))
        c.update(cfg)
        with mock.patch.object(engine, "call_codex", script), mock.patch.object(engine, "call_claude", script):
            rc = engine.Engine("t-1", str(self.wt), c).run()
        return rc, script

    def test_happy_path_lands_and_closes(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE], "verify": [ACCEPT_V], "judge": [judge("accept")]})
        self.assertEqual(rc, 0)
        self.assertEqual([c[0] for c in s.calls], ["plan", "write", "verify", "judge"])
        self.assertTrue(self.closed and self.closed[0].startswith("merged "))
        self.assertEqual(tl.git("show", "origin/main:f.txt", cwd=str(self.wt)), "x2")
        self.assertTrue(any(c[:2] == ("comments", "add") and "Reflect (engine)" in c[3] for c in self.bd_calls))

    def test_rework_resumes_the_same_writer(self):
        rc, s = self.run_engine({"plan": [PLAN], "write": [WRITE, WRITE], "verify": [GAPS_V, ACCEPT_V],
                                 "judge": [judge("rework"), judge("accept")]})
        self.assertEqual(rc, 0)
        writes = [c for c in s.calls if c[0] == "write"]
        self.assertEqual(writes, [("write", None), ("write", "thread-write")])

    def test_replan_starts_over_once_then_blocks(self):
        rc, s = self.run_engine({"plan": [PLAN, PLAN], "write": [WRITE, WRITE], "verify": [ACCEPT_V, ACCEPT_V],
                                 "judge": [judge("replan"), judge("replan")]})
        self.assertEqual(rc, 2)
        self.assertIn("re-plan", self.blocked[0])

    def test_owner_question_blocks_with_the_question(self):
        rc, _ = self.run_engine({"plan": [dict(PLAN, question="Which format, A or B?")]})
        self.assertEqual(rc, 2)
        self.assertIn("Which format, A or B?", self.blocked[0])
        self.assertFalse(self.closed)

    def test_invalid_output_retries_once_then_fails_and_still_closes(self):
        rc, s = self.run_engine({"plan": [{"summary": "x"}, {"summary": "x"}]})
        self.assertEqual(rc, 2)
        self.assertEqual([c for c in s.calls], [("plan", None), ("plan", "thread-plan")])
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
        self.assertIn("review", [c[0] for c in s.calls])

    def test_child_env_drops_session_identity(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_BASE_URL": "x", "CLAUDE_CODE_SESSION_ID": "s"}):
            env = engine.child_env()
        self.assertNotIn("ANTHROPIC_BASE_URL", env)
        self.assertNotIn("CLAUDE_CODE_SESSION_ID", env)
        self.assertEqual(env["DELEGATE_DEPTH"], "1")


class Validate(unittest.TestCase):
    def test_schema_subset(self):
        s = engine.SCHEMAS["judge"]
        self.assertEqual(engine.validate(judge("accept"), s), [])
        self.assertTrue(engine.validate(dict(judge("accept"), decision="maybe"), s))
        self.assertTrue(engine.validate({"decision": "accept"}, s))
        self.assertTrue(engine.validate(dict(ACCEPT_V, tests_added=True), engine.SCHEMAS["verify"]))


if __name__ == "__main__":
    unittest.main()
