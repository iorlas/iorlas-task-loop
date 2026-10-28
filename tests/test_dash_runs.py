"""The transcript index (one listing of the project folders)."""

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop" / "dash"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
import server  # noqa: E402


class Runs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.projects = Path(self.tmp.name) / "projects"
        server._cache.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def test_transcript_index_names_the_newest_of_a_session_across_projects(self):
        old, new = self.projects / "-a" / "s9.jsonl", self.projects / "-b" / "s9.jsonl"
        for p in (old, new):
            p.parent.mkdir(parents=True)
            p.write_text("{}\n")
        os.utime(str(old), (1, 1))
        with mock.patch.object(server, "PROJECTS", self.projects):
            self.assertEqual(server.transcript_index()["s9"], str(new))


if __name__ == "__main__":
    unittest.main()
