"""Dashboard banners and empty states may suggest only verbs registered by the real tl parser."""
import argparse
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.tlmain import tl

STATIC = Path(__file__).resolve().parents[2] / "src" / "taskloop_dash" / "static"


def named_verbs(text):
    return set(re.findall(r"\btl ([a-z][a-z0-9-]*)\b", text))


class DashboardVerbs(unittest.TestCase):
    def test_every_suggested_verb_is_a_real_subcommand(self):
        parser = tl.build_parser()
        registered = {verb for action in parser._actions if isinstance(action, argparse._SubParsersAction)
                      for verb in action.choices}
        found = set()
        for path in [STATIC / "index.html", *sorted((STATIC / "js").rglob("*.js"))]:
            verbs = named_verbs(path.read_text())
            found |= verbs
            with self.subTest(path=path.relative_to(STATIC)):
                self.assertLessEqual(verbs, registered)
        self.assertTrue({"loop", "run-task"} <= found)

    def test_verb_matching_does_not_mistake_run_task_for_the_nonexistent_run(self):
        self.assertEqual(named_verbs("tl run-task ID · tl loop · tl run"), {"run-task", "loop", "run"})
