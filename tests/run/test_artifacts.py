"""Artifacts: plain files per bead, copied by `ingest`, listed on the bead page and served read only."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.dashes import make_dash
from support.narrow import must

from taskloop.app.run import artifacts
from taskloop.app.run.steps import Steps
from taskloop.contracts.ids import BeadId
from taskloop.stores.memory import fake_stores
from taskloop.stores.runlog import RunLog


class Ingest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.src, self.dest = Path(self.tmp.name, "src"), Path(self.tmp.name, "dest", "tl-1")
        self.src.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_plain_files_are_copied_secrets_symlinks_and_big_files_are_not(self):
        (self.src / "shot.png").write_bytes(b"png")
        (self.src / "report.pdf").write_bytes(b"%PDF")
        for bad in (".env", ".env.local", "id_rsa", "deploy.pem", "api.key", "my-token.txt", "client_secret.json", ".hidden"):
            (self.src / bad).write_text("x")
        os.symlink("/etc/passwd", self.src / "link.txt")
        (self.src / "dir").mkdir()
        with mock.patch.object(artifacts, "MAX_BYTES", 3):
            (self.src / "big.bin").write_bytes(b"1234")
            got = artifacts.ingest(self.src, self.dest)
        self.assertEqual(got, ["shot.png"])
        self.assertEqual(sorted(p.name for p in self.dest.iterdir()), ["shot.png"])  # %PDF is 4 bytes: over the patched cap

    def test_ingest_is_idempotent_and_never_raises(self):
        (self.src / "a.png").write_bytes(b"1")
        self.assertEqual(artifacts.ingest(self.src, self.dest), ["a.png"])
        (self.src / "a.png").write_bytes(b"2")
        self.assertEqual(artifacts.ingest(self.src, self.dest), ["a.png"])
        self.assertEqual((self.dest / "a.png").read_bytes(), b"2")
        self.assertEqual(artifacts.ingest(self.src / "missing", self.dest), [])


class AtStepEnd(unittest.TestCase):
    """The engine ingests as a step ends: one Artifacts record under that step, only for files new since the last step, no model call."""

    def test_a_step_that_left_files_logs_one_record_before_its_end_and_a_later_step_logs_only_new_ones(self):
        with tempfile.TemporaryDirectory() as d:
            src, dest = Path(d, "src"), Path(d, "dest")
            src.mkdir()
            stores = fake_stores()
            rl = RunLog(stores.run_log("r"), None, frozenset(), None, lambda: 5.0, 0)
            steps = Steps(rl, lambda: 5.0, None, None, artifacts.StepArtifacts("tl-1", src, dest, rl))
            steps.begin("write", "write")
            (src / "a.png").write_bytes(b"1")
            steps.begin("checks", "checks")  # ends `write`
            steps.end()  # ends `checks`: nothing new
            steps.begin("write", "write")
            (src / "b.pdf").write_bytes(b"2")
            steps.end()
            kinds = [(r.kind, getattr(r, "names", None)) for r in (i.rec for i in stores.run_log("r").read_from().items)]
            self.assertEqual([k for k in kinds if k[1]], [("artifacts", ["a.png"]), ("artifacts", ["b.pdf"])])
            self.assertEqual([k[0] for k in kinds[:3]], ["step_start", "artifacts", "step_end"])
            self.assertEqual(sorted(p.name for p in dest.iterdir()), ["a.png", "b.pdf"])


class Page(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dash = make_dash(config=self.tmp.name)
        self.dir = self.dash.env.config.artifacts(BeadId("tl-1"))
        self.dir.mkdir(parents=True)
        (self.dir / "shot.png").write_bytes(b"png")
        (self.dir / "r.pdf").write_bytes(b"%PDF")
        (self.dir / "page.html").write_text("<script>alert(1)</script>")
        os.symlink("/etc/passwd", self.dir / "link.txt")

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_file_is_served_with_a_safe_type_and_bad_names_are_refused(self):
        self.assertEqual(self.dash.artifacts.file("tl-1", "shot.png"), (b"png", "image/png"))
        self.assertEqual(self.dash.artifacts.file("tl-1", "r.pdf"), (b"%PDF", "application/pdf"))
        self.assertEqual(must(self.dash.artifacts.file("tl-1", "page.html"))[1], "application/octet-stream")  # never run as a page
        for bad in ("link.txt", "../shot.png", "a/b", ".x", "", "missing.png"):
            self.assertIsNone(self.dash.artifacts.file("tl-1", bad), bad)
        self.assertIsNone(self.dash.artifacts.file("../tl-1", "shot.png"))


if __name__ == "__main__":
    unittest.main()
