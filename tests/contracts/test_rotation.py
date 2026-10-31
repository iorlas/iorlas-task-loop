"""Every JsonlStore rotates: past its cap the files shift, at most `keep` exist, and no store has a way to append without it."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401
from jsonl_log import KEEP, ROTATE_BYTES

from taskloop.contracts import paths, stores
from taskloop.contracts.stores import JsonlStore


def decode(data):
    return data


class RotationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "x.jsonl"

    def test_a_store_past_its_cap_rotates_and_keeps_only_keep_files(self):
        class Raw(JsonlStore[dict]):
            pass
        s = Raw(self.path, decode, rotate_bytes=100, keep=3)
        for i in range(40):
            s.file.append({"i": i, "pad": "x" * 20})
        names = sorted(p.name for p in self.path.parent.iterdir())
        self.assertEqual(names, ["x.jsonl", "x.jsonl.1", "x.jsonl.2"])
        self.assertTrue(all(p.stat().st_size <= 100 for p in self.path.parent.iterdir()))
        last = [i.rec["i"] for i in s.read_from(0).items][-1]
        self.assertEqual(last, 39)

    def test_the_real_stores_default_to_the_one_policy(self):
        cfg = paths.ConfigDir(self.tmp.name)
        for store in (stores.RunLog(cfg, "r"), stores.EventLog(cfg), stores.TraceStore(cfg), stores.LoopLog(cfg, "k")):
            log = store.file.log
            self.assertEqual((log._rotate_bytes, log._keep), (ROTATE_BYTES, KEEP))



if __name__ == "__main__":
    unittest.main()
