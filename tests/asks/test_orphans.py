"""A bead parked on an ask that was dropped at upgrade (a v1 or unreadable file) stays visible and is asked again."""
import json
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from support.tiers import domain

from taskloop.adapters.fake_beads import FakeBeads
from taskloop.app.asks import sweeps
from taskloop.cli import asks as cli
from taskloop.contracts.bead import Bead
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.stores import HAD_PICK, ORPHAN, AskStore

T = 1000.0


@domain
class OrphanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = ConfigDir(Path(self.tmp.name))
        self.cfg.ask("tl-7").parent.mkdir(parents=True)
        self.cfg.ask("tl-7").write_text(json.dumps({"v": 1, "id": "tl-7-2", "bead": "tl-7", "status": "open", "kind": "verify"}))
        self.asks = AskStore.at(self.cfg)
        self.store = FakeBeads()
        self.store.beads["tl-7"] = Bead(id="tl-7", title="t", status="blocked", labels=["needs-info"])

    def test_it_is_listed_with_the_one_typed_line(self) -> None:
        self.assertEqual((self.asks.get("tl-7"), self.asks.orphans()), (None, ["tl-7"]))
        out: list[str] = []
        self.assertEqual(cli.age(self.asks, T, out.append), 0)
        self.assertEqual(out, [sweeps.orphan_lines(self.asks)[0]])
        self.assertIn(ORPHAN, out[0])
        listed: list[str] = []
        cli.run(Namespace(op="list"), self.asks, lambda repo: self.store, lambda: T, "denis", listed.append)
        self.assertIn(ORPHAN, listed[0])

    def test_the_loop_reopens_it_into_the_pick_queue_once(self) -> None:
        self.store.beads["tl-7"].metadata[HAD_PICK] = "auto"  # the park took the label off
        marker = self.cfg.ask_marker("orphans")
        self.assertEqual(sweeps.reask_orphans(self.asks, self.store, marker, T, "auto", "needs-info"), ["tl-7"])
        b = self.store.beads["tl-7"]
        self.assertEqual((b.status, "auto" in b.labels, "needs-info" in b.labels), ("open", True, False))
        self.assertEqual(sweeps.reask_orphans(self.asks, self.store, marker, T + 1, "auto", "needs-info"), [])  # throttled
        self.assertEqual(sweeps.reask_orphans(self.asks, self.store, marker, T + 1e4, "auto", "needs-info"), [])  # no longer blocked

    def test_the_sweep_never_adds_a_pick_label_the_bead_did_not_have(self) -> None:
        marker = self.cfg.ask_marker("orphans")
        self.assertEqual(sweeps.reask_orphans(self.asks, self.store, marker, T, "auto", "needs-info"), ["tl-7"])
        b = self.store.beads["tl-7"]
        self.assertEqual((b.status, b.labels), ("open", []))

    def test_answer_rerun_reopens_it_and_a_closed_bead_drops_the_dead_file(self) -> None:
        out: list[str] = []
        code = cli.run(
            Namespace(op="answer", bead="tl-7", text=[], rerun=True), self.asks, lambda repo: self.store, lambda: T, "denis", out.append
        )
        self.assertEqual((code, self.store.beads["tl-7"].status), (0, "open"))
        self.store.beads["tl-7"] = Bead(id="tl-7", title="t", status="closed")
        sweeps.reopen(self.asks, self.store, "tl-7")
        self.assertEqual(self.asks.orphans(), [])


if __name__ == "__main__":
    unittest.main()
