"""The host suite leaves no tl-suite-* dir behind, green or red, and sweeps an old one a killed suite left."""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: F401

from taskloop.app.release import suite
from taskloop.app.release.shell import Abort

PLAN = json.dumps({"shards": [["t.A.test_a"]], "serial": []})


class SuiteTmp(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmpdir = Path(self.tmp.name)
        for p in (mock.patch.object(tempfile, "tempdir", str(self.tmpdir)), mock.patch.object(suite, "say"),
                  mock.patch.object(suite, "workers", return_value=1), mock.patch.object(suite, "available_mb", return_value=None),
                  mock.patch.object(suite, "run", return_value=mock.Mock(stdout=PLAN, stderr=""))):
            p.start()
            self.addCleanup(p.stop)

    def dirs(self):
        return sorted(p.name for p in self.tmpdir.glob("tl-suite-*"))

    def run_suite(self, shards, green=True):
        seen = []

        def fake_shards(*a):
            seen.append(self.dirs())  # the work dir exists while the shards run
            return shards()
        with mock.patch.object(suite, "run_shards", side_effect=fake_shards), \
                mock.patch.object(suite, "merge_outputs", return_value=("out\n", green)):
            try:
                suite._host_suite(Path("/tool"), Path("/repo"), False)
            finally:
                self.seen = seen

    def test_a_green_suite_removes_its_tmp_dir(self):
        self.run_suite(lambda: [])
        self.assertEqual(len(self.seen[0]), 1)
        self.assertEqual(self.dirs(), [])

    def test_a_red_suite_removes_its_tmp_dir(self):
        with self.assertRaises(Abort):
            self.run_suite(lambda: [], green=False)
        self.assertEqual(self.dirs(), [])

    def test_a_suite_that_dies_with_an_exception_removes_its_tmp_dir(self):
        def boom():
            raise RuntimeError("shard pool broke")
        with self.assertRaises(RuntimeError):
            self.run_suite(boom)
        self.assertEqual(self.dirs(), [])

    def test_a_dir_left_by_a_killed_suite_is_swept_and_a_young_one_stays(self):
        old, young = self.tmpdir / "tl-suite-old", self.tmpdir / "tl-suite-young"
        for d in (old, young):
            (d / "shard1").mkdir(parents=True)
        long_ago = time.time() - suite.STALE_TMP_S - 60
        os.utime(old, (long_ago, long_ago))
        suite.sweep_stale_tmp()
        self.assertEqual(self.dirs(), ["tl-suite-young"])


if __name__ == "__main__":
    unittest.main()
