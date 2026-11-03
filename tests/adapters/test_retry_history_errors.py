"""An absent retry history is empty; an unreadable one must reach the caller's warning."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.adapters.storm import recent_closes


class RetryHistoryErrors(unittest.TestCase):
    def test_absent_history_is_empty(self):
        with mock.patch.object(Path, "read_text", side_effect=FileNotFoundError("absent")):
            self.assertEqual(recent_closes(Path("traces.jsonl"), "repo", 100), [])

    def test_unreadable_history_is_not_an_empty_retry_budget(self):
        with mock.patch.object(Path, "read_text", side_effect=PermissionError("unreadable")), self.assertRaises(PermissionError):
            recent_closes(Path("traces.jsonl"), "repo", 100)
