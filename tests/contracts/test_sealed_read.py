"""JsonStore.read says which of four it found, and a caller that must not read a damaged file as empty refuses it by name."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.contracts.run import NetPause
from taskloop.contracts.stores import Absent, ForeignVersion, JsonStore, Present, Refused, Torn


class SealedRead(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "n.json"
        self.store = JsonStore(self.path, NetPause)

    def test_four_results(self) -> None:
        self.assertEqual(self.store.read(), Absent())
        rec = NetPause(run="r", bead="b", t=1.0)
        self.store.write(rec)
        self.assertEqual(self.store.read(), Present(rec))
        self.path.write_text('{"v": 1, "run": "r"')
        self.assertIsInstance(self.store.read(), Torn)
        self.path.write_text('{"v": 99, "run": "r", "bead": "b", "t": 1.0}')
        self.assertEqual(self.store.read(), ForeignVersion(self.path, 99, NetPause.V))

    def test_get_is_lossy_and_need_refuses_with_the_path(self) -> None:
        self.assertIsNone(self.store.need())
        self.path.write_text("{")
        self.assertIsNone(self.store.get())
        with self.assertRaises(Refused) as ctx:
            self.store.need()
        self.assertIn(str(self.path), str(ctx.exception))
        self.path.write_text('{"v": 99}')
        with self.assertRaises(Refused) as ctx:
            self.store.need()
        self.assertIn(str(self.path), str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
