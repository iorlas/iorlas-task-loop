"""A torn ask file fails closed: it is never read as no ask, so a new ask or an answer cannot overwrite it unseen."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from contracts import samples as S

from taskloop.contracts.ids import BeadId
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.stores import AskStore, Refused


class TornAsk(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cfg = ConfigDir(Path(tmp.name))
        self.asks = AskStore.at(self.cfg)
        self.bead = BeadId("tl-7")
        self.path = self.cfg.ask(self.bead)
        self.path.parent.mkdir(parents=True)
        self.path.write_text('{"v": 3, "id": "tl-7-1", "bead"')

    def test_get_and_a_new_ask_refuse_with_the_path_and_leave_the_file(self) -> None:
        with self.assertRaises(Refused) as ctx:
            self.asks.get(self.bead)
        self.assertIn(str(self.path), str(ctx.exception))
        with self.assertRaises(Refused):
            self.asks.file(S.ASK.replace(bead=self.bead))
        self.assertEqual(self.path.read_text(), '{"v": 3, "id": "tl-7-1", "bead"')

    def test_a_torn_ask_is_no_orphan_to_be_asked_again(self) -> None:
        self.assertEqual(self.asks.orphans(), [])
        self.assertEqual(self.asks.all(), [])


if __name__ == "__main__":
    unittest.main()
