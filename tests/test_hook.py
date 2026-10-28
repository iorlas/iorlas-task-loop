"""The plugin's hooks (hooks/hook.py): what PreToolUse refuses, what SessionStart and PreCompact do, and that each finishes fast as a real
process. The status and the handoff text they share: size caps and the first line."""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "hook.py"
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
import tl  # noqa: E402
from taskloop.domain.brief import HANDOFF_BYTES, RULES, STATUS_BYTES, STATUS_LINES, AskLine, Brief, LoopLine, handoff_text, status_lines  # noqa: E402
from taskloop.hook import pretool, session  # noqa: E402

BUDGET = 1.0  # seconds for one hook, a real process start included (the bead: a hook finishes under 1 s)


def call(tool, **args):
    return pretool.main(json.dumps({"tool_name": tool, "tool_input": args}))


def denied(tool, **args):
    out = call(tool, **args)
    return json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"] if out else ""


class PreToolUse(unittest.TestCase):
    def test_an_agent_call_without_a_model_is_denied_and_the_reason_lists_the_values(self):
        why = denied("Agent", prompt="do it", description="x")
        for model in ("sonnet", "opus", "haiku"):
            self.assertIn(model, why)
        self.assertEqual(json.loads(call("Agent", prompt="x"))["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(len(why.splitlines()), 1)

    def test_an_agent_call_with_a_model_or_a_fork_is_allowed(self):
        self.assertEqual(call("Agent", prompt="x", model="sonnet"), "")
        self.assertEqual(call("Agent", prompt="x", subagent_type="fork"), "")
        self.assertNotEqual(call("Agent", prompt="x", model=" "), "")

    def test_pkill_and_killall_are_denied_wherever_they_stand_as_a_command(self):
        for cmd in ('pkill -f "unittest discover"', "killall python3", "cd x && pkill -f foo", "sudo pkill foo", "ls; killall node",
                    "sh -c 'pkill -f x'", "bash -c \"cd a && killall b\"", "/usr/bin/pkill -9 x", "echo hi\npkill foo"):
            with self.subTest(cmd=cmd):
                self.assertNotEqual(denied("Bash", command=cmd), "")

    def test_other_commands_are_allowed_even_when_they_mention_the_word(self):
        for cmd in ("ls -la", "echo pkill", "git commit -m 'no pkill here'", "grep -r killall src", "kill 4242", "python3 -m unittest",
                    "unterminated 'quote pkill"):
            with self.subTest(cmd=cmd):
                self.assertEqual(denied("Bash", command=cmd), "")

    def test_other_tools_and_unreadable_input_are_allowed(self):
        self.assertEqual(call("Read", file_path="/x"), "")
        self.assertEqual(pretool.main("not json"), "")
        self.assertEqual(pretool.main(""), "")
        self.assertEqual(pretool.main('{"tool_name": "Bash", "tool_input": "oops"}'), "")


class Sessions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.cfg = self.home / "cfg" / "task-loop"
        env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.home / "cfg"), "CLAUDE_CONFIG_DIR": str(self.home / "claude"),
                                           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
                                           "GIT_COMMITTER_EMAIL": "t@t"})
        env.start()
        self.addCleanup(env.stop)
        self.repo = self.home / "repo"
        self.repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True, capture_output=True)
        self.root = self.home / "plugin"
        (self.root / ".claude-plugin").mkdir(parents=True)
        (self.root / ".claude-plugin" / "plugin.json").write_text('{"version": "9.9.9"}')

    def event(self, **kw):
        return json.dumps({"session_id": "s1", "transcript_path": "/t.jsonl", "cwd": str(self.repo), **kw})

    def test_session_start_indexes_the_session_and_points_the_tl_shim_at_this_install(self):
        self.assertEqual(session.start(self.event(source="startup"), self.root), "")
        self.assertEqual(json.loads((self.cfg / "sessions" / "s1.json").read_text())["transcript"], "/t.jsonl")
        shim = (self.cfg / "bin" / "tl").read_text()
        self.assertIn(str(self.root / "skills" / "task-loop" / "tl.py"), shim)
        self.assertTrue(os.access(self.cfg / "bin" / "tl", os.X_OK))

    def test_session_start_never_fails_on_input_it_cannot_read(self):
        self.assertEqual(session.start("not json", self.root), "")
        self.assertEqual(session.start("", self.root), "")

    def test_a_compaction_writes_the_handoff_and_the_session_that_follows_gets_it_as_context(self):
        self.assertEqual(session.start(self.event(source="compact"), self.root), "")  # nothing written yet
        session.precompact(self.event(), self.root)
        out = json.loads(session.start(self.event(source="compact"), self.root))["hookSpecificOutput"]
        self.assertEqual(out["hookEventName"], "SessionStart")
        text = out["additionalContext"]
        self.assertIn("loop NOT RUNNING", text)
        self.assertIn("running 9.9.9", text)
        self.assertLessEqual(len(text.encode()), HANDOFF_BYTES)
        for rule in RULES:
            self.assertIn(rule, text)
        self.assertEqual(session.start(self.event(source="startup"), self.root), "")  # a fresh session gets no handoff

    def test_a_worktree_shares_the_handoff_of_its_main_checkout(self):
        subprocess.run(["git", "-C", str(self.repo), "commit", "-q", "--allow-empty", "-m", "x"], check=True, capture_output=True)
        wt = self.home / "wt"
        subprocess.run(["git", "-C", str(self.repo), "worktree", "add", "-q", "-b", "b", str(wt)], check=True, capture_output=True)
        session.precompact(self.event(cwd=str(wt)), self.root)
        self.assertIn("loop NOT RUNNING", json.loads(session.start(self.event(source="compact"), self.root))["hookSpecificOutput"]["additionalContext"])

    def test_tl_status_and_handoff_read_the_stores(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(tl.main(["status", "--brief", "--repo", str(self.repo)], here=self.root / "skills" / "task-loop"), 0)
        self.assertTrue(out.getvalue().splitlines()[0].startswith("loop NOT RUNNING"), out.getvalue())
        out = io.StringIO()
        with redirect_stdout(out):
            tl.main(["status", "--json", "--repo", str(self.repo)], here=self.root / "skills" / "task-loop")
        self.assertFalse(json.loads(out.getvalue())["running"])
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(tl.main(["handoff", "show", "--repo", str(self.repo)], here=self.root / "skills" / "task-loop"), 1)
            self.assertEqual(tl.main(["handoff", "write", "--repo", str(self.repo)], here=self.root / "skills" / "task-loop"), 0)
            self.assertEqual(tl.main(["handoff", "show", "--repo", str(self.repo)], here=self.root / "skills" / "task-loop"), 0)
        self.assertIn("standing rules", out.getvalue())


class Texts(unittest.TestCase):
    def brief(self, asks=0, loops=0, slots=30):
        return Brief(repo="/r", now=2_000_000.0, last_beat=1_999_000.0, version="1", installed="1",
                     loops=tuple(LoopLine(100 + i, 1_990_000.0, "tl-x", "s1", "1") for i in range(loops)),
                     asks=tuple(AskLine(f"tl-{i}", "decision", "which way? " * 20, 1_900_000.0) for i in range(asks)),
                     slots=tuple(f"s{i}: free" for i in range(slots)), recent=tuple(f"tl-{i} landed (5 min)" for i in range(5)))

    def test_the_first_line_says_whether_the_loop_runs_and_when_it_last_did_something(self):
        self.assertTrue(status_lines(self.brief(loops=1))[0].startswith("loop RUNNING"))
        first = status_lines(self.brief())[0]
        self.assertTrue(first.startswith("loop NOT RUNNING"))
        self.assertIn("last activity 16 min ago", first)

    def test_a_huge_status_stays_within_40_lines_and_8_kb_and_says_what_it_left_out(self):
        lines = status_lines(self.brief(asks=500, loops=3))
        self.assertLessEqual(len(lines), STATUS_LINES)
        self.assertLessEqual(len("\n".join(lines).encode()), STATUS_BYTES)
        self.assertRegex(lines[-1], r"^\.\.\. \d+ more line")

    def test_a_small_status_is_whole(self):
        lines = status_lines(self.brief(asks=2, slots=2))
        self.assertNotIn("more line", "\n".join(lines))
        self.assertIn("asks: 2 open", lines)

    def test_a_huge_handoff_stays_within_4_kb_and_keeps_the_standing_rules(self):
        text = handoff_text(self.brief(asks=500, loops=3))
        self.assertLessEqual(len(text.encode()), HANDOFF_BYTES)
        for rule in RULES:
            self.assertIn(rule, text)


class Speed(unittest.TestCase):
    """A real process start of each hook, the best of three, against the budget: a hook runs before every tool call."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = dict(os.environ, XDG_CONFIG_HOME=self.tmp.name, CLAUDE_CONFIG_DIR=self.tmp.name)

    def best(self, event, payload):
        runs = []
        for _ in range(3):
            began = time.monotonic()
            r = subprocess.run([sys.executable, str(HOOK), event], input=json.dumps(payload), capture_output=True, text=True, env=self.env,
                               cwd=self.tmp.name, timeout=30)
            runs.append(time.monotonic() - began)
            self.assertEqual(r.returncode, 0, r.stderr)
        return min(runs), r.stdout

    def test_pretool_finishes_within_the_budget_and_denies(self):
        secs, out = self.best("pretool", {"tool_name": "Bash", "tool_input": {"command": "pkill -f x"}})
        self.assertLess(secs, BUDGET)
        self.assertIn("deny", out)

    def test_session_start_and_precompact_finish_within_the_budget(self):
        repo = Path(self.tmp.name) / "repo"
        subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
        for event in ("session-start", "precompact"):
            with self.subTest(event=event):
                secs, _ = self.best(event, {"session_id": "s1", "cwd": str(repo), "source": "compact"})
                self.assertLess(secs, BUDGET)

    def test_pretool_imports_no_store_adapter_or_app_module(self):
        code = ("import sys; sys.path.insert(0, %r); from taskloop.hook import main, pretool; pretool.main('{}'); "
                "print([m for m in sys.modules if m.startswith(('taskloop.app', 'taskloop.adapters', 'taskloop.stores'))])") % str(ROOT / "src")
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
        self.assertEqual(r.stdout.strip(), "[]")

    def test_an_unknown_event_is_an_error_not_a_silent_pass(self):
        r = subprocess.run([sys.executable, str(HOOK), "nonsense"], input="{}", capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
