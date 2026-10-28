"""Artifacts: plain files per bead, copied by `ingest`, listed on the bead page and served read only."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
from support.dashes import make_dash  # noqa: E402
from support.narrow import must  # noqa: E402
from taskloop.app.run import artifacts  # noqa: E402


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


class Page(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dash = make_dash(config=self.tmp.name)
        self.dir = self.dash.env.config.artifacts("tl-1")
        self.dir.mkdir(parents=True)
        (self.dir / "shot.png").write_bytes(b"png")
        (self.dir / "r.pdf").write_bytes(b"%PDF")
        (self.dir / "page.html").write_text("<script>alert(1)</script>")
        os.symlink("/etc/passwd", self.dir / "link.txt")

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_list_names_files_and_kinds_without_symlinks(self):
        got = {a["name"]: a["kind"] for a in self.dash.artifacts.listing("tl-1")}
        self.assertEqual(got, {"shot.png": "image", "r.pdf": "file", "page.html": "file"})
        self.assertEqual(self.dash.artifacts.listing("../x"), [])

    def test_a_file_is_served_with_a_safe_type_and_bad_names_are_refused(self):
        self.assertEqual(self.dash.artifacts.file("tl-1", "shot.png"), (b"png", "image/png"))
        self.assertEqual(self.dash.artifacts.file("tl-1", "r.pdf"), (b"%PDF", "application/pdf"))
        self.assertEqual(must(self.dash.artifacts.file("tl-1", "page.html"))[1], "application/octet-stream")  # never run as a page
        for bad in ("link.txt", "../shot.png", "a/b", ".x", "", "missing.png"):
            self.assertIsNone(self.dash.artifacts.file("tl-1", bad), bad)
        self.assertIsNone(self.dash.artifacts.file("../tl-1", "shot.png"))


if __name__ == "__main__":
    unittest.main()
