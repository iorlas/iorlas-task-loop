"""The injected introduction stays small, portable and independent of session state."""
import unittest

from taskloop.domain import selfdescribe


class SelfDescription(unittest.TestCase):
    def test_text_is_compact_ascii_and_repeatable(self):
        text = selfdescribe.text()
        self.assertTrue(text.isascii())
        self.assertLessEqual(len(text.splitlines()), 35)
        self.assertEqual(text, selfdescribe.text())

    def test_standing_rules_and_procedure_pointer_are_present(self):
        text = selfdescribe.text()
        for rule in ("worktree or slot", "Never edit the main checkout", "plugin cache directory",
                     "dev/release.py", "Never kill by pattern", "Every bd call goes through tl task", "SKILL.md"):
            with self.subTest(rule=rule):
                self.assertIn(rule, text)
