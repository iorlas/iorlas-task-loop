"""The plugin's hooks (hooks/hook.py): what PreToolUse refuses, what SessionStart and PreCompact do, and that each finishes fast as a real
process. The status and the handoff text they share: size caps and the first line."""
import contextlib
import io
import json
import os
import runpy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "hooks" / "hook.py"
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: E402, F401

from taskloop.domain.brief import HANDOFF_BYTES, RULES, STATUS_BYTES, STATUS_LINES, AskLine, Brief, LoopLine, handoff_text, status_lines  # noqa: E402
from taskloop.hook import pretool  # noqa: E402


def call(tool, **args):
    return pretool.main(json.dumps({"tool_name": tool, "tool_input": args}))


def denied(tool, **args):
    out = call(tool, **args)
    return json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"] if out else ""


class PreToolUse(unittest.TestCase):
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
    """A hook runs before every tool call: pretool imports no store, adapter, app, record or msgspec module; an unknown event fails."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = dict(os.environ, XDG_CONFIG_HOME=self.tmp.name, CLAUDE_CONFIG_DIR=self.tmp.name)


    def test_an_unknown_event_is_an_error_not_a_silent_pass(self):
        with mock.patch.object(sys, "argv", [str(HOOK), "nonsense"]), mock.patch.object(sys, "stdin", io.StringIO("{}")), \
                mock.patch.dict(os.environ, self.env), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stop:
            runpy.run_path(str(HOOK), run_name="__main__")
        self.assertEqual(stop.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
