"""One code path: an answer from the dashboard and `tl answer` leave the same ask record and the same bead comments."""
import dataclasses
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.dashes import make_dash
from support.narrow import must

from asks.dash_ports import answering
from asks.samples import MOCKS
from taskloop.adapters.fake_beads import FakeBeads
from taskloop.cli import asks as cli_asks
from taskloop.contracts.bead import Bead
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.stores import AskStore

ASK = dataclasses.replace(MOCKS["lifesim-22b3"], bead="b-1", id="b-1-1")


def world(root: str):
    store = FakeBeads()
    store.beads["b-1"] = Bead(id="b-1", title="", status="blocked")
    asks = AskStore.at(ConfigDir(root))
    asks.put(ASK)
    return store, asks


class SameIntake(unittest.TestCase):
    def test_the_dash_and_tl_answer_file_the_same_record_and_comments(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            tl_store, tl_asks = world(a)
            dash_store, dash_asks = world(b)
            args = Namespace(op="answer", bead="b-1", text=["go", "with", "A"], amend=False, option=None, rerun=False, confirm=False,
                             split=False, verdict=None)
            cli_asks.run(args, tl_asks, lambda repo: tl_store, lambda: 1000.0, "dash", lambda _line: None)
            dash = make_dash(answering(lambda repo: dash_store, b), config=b)
            req = {"project": "b", "ask": "b-1-1", "kind": "answer", "text": "go with A"}
            self.assertEqual(dash.writes.post("answer", req), (200, {"ok": True, "message": ""}))
            self.assertEqual([c.text for c in dash_store.comments("b-1")], [c.text for c in tl_store.comments("b-1")])
            self.assertIn("Owner (tl) answer", dash_store.comments("b-1")[0].text)
            self.assertEqual(dash_store.beads["b-1"].status, tl_store.beads["b-1"].status)
            mine, theirs = dash_asks.get("b-1"), tl_asks.get("b-1")
            self.assertEqual(dataclasses.replace(must(must(mine).answer), t=0), dataclasses.replace(must(must(theirs).answer), t=0))


if __name__ == "__main__":
    unittest.main()
