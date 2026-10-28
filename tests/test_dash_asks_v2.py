"""The dash reads and answers both ask file versions: v1 (what the engine writes today) and v2 (taskloop.contracts.ask.Ask)."""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401
from support.dashes import make_dash  # noqa: E402
from taskloop.contracts.ask import Ask  # noqa: E402
from taskloop.contracts.codec import from_json  # noqa: E402
from taskloop_dash.env import Ports  # noqa: E402

V2 = {"v": 2, "id": "b-1-1", "n": 1, "bead": "b-1", "kind": "decision", "question": "Which?", "run": "r", "t": 1.0, "status": "open",
      "detail": {"budget": [], "replans": [], "text": "why"}, "options": [], "repo": "", "title": "t"}


def fake_bd(repo, *args, timeout=30):
    return types.SimpleNamespace(returncode=0, stdout="[]", stderr="")


class AsksV2(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dash = make_dash(Ports(bd=fake_bd), config=self.tmp.name)
        self.path = self.dash.env.config.ask("b-1")
        self.path.parent.mkdir(parents=True)

    def put(self, rec):
        self.path.write_text(json.dumps(rec))

    def test_v2_ask_is_in_the_inbox_with_flat_detail(self):
        self.put(V2)
        rows = self.dash.asks.inbox()
        self.assertEqual([r["id"] for r in rows], ["b-1-1"])
        self.assertEqual(rows[0]["detail"], "why")

    def test_unknown_version_is_skipped(self):
        self.put({**V2, "v": 9})
        self.assertEqual(self.dash.asks.inbox(), [])

    def test_answer_keeps_the_file_a_valid_v2_record(self):
        self.put(V2)
        code, _ = self.dash.asks.answer({"ask": "b-1-1", "text": "go with A"})
        self.assertEqual(code, 200)
        ask = from_json(Ask, json.loads(self.path.read_text()))
        self.assertEqual((ask.answer.text, ask.answer.action), ("go with A", "text"))

    def test_withdraw_keeps_the_file_a_valid_v2_record(self):
        self.put(V2)
        code, _ = self.dash.asks.withdraw({"ask": "b-1-1", "why": "moot"})
        self.assertEqual(code, 200)
        ask = from_json(Ask, json.loads(self.path.read_text()))
        self.assertEqual((ask.status.value, ask.why), ("withdrawn", "moot"))


if __name__ == "__main__":
    unittest.main()
