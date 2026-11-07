"""Release manifests identify missing or changed tracked files."""
from pathlib import Path

from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

from tlrelease import manifest


class Manifest(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "plugin"
        (self.root / "skills").mkdir(parents=True)
        (self.root / "a.txt").write_bytes(b"alpha\n")
        (self.root / "skills" / "tl.py").write_bytes(b"print(1)\n")
        manifest.write(self.root, ["a.txt", "skills/tl.py", manifest.NAME, "dangling"])

    def test_the_manifest_lists_each_file_once_and_not_itself(self):
        lines = (self.root / manifest.NAME).read_text().splitlines()
        assert [x.split("  ")[1] for x in lines] == ["a.txt", "skills/tl.py"]

    def test_a_clean_tree_verifies(self):
        assert manifest.verify(self.root) == []

    def test_one_flipped_byte_names_the_exact_file(self):
        (self.root / "skills" / "tl.py").write_bytes(b"print(2)\n")
        assert manifest.verify(self.root) == ["skills/tl.py differs from MANIFEST.sha256"]

    def test_a_removed_file_and_a_missing_manifest_are_reported(self):
        (self.root / "a.txt").unlink()
        assert manifest.verify(self.root) == ["a.txt is listed in MANIFEST.sha256 but missing"]
        (self.root / manifest.NAME).unlink()
        assert "MANIFEST.sha256 is missing" in manifest.verify(self.root)[0]

    def test_a_file_the_manifest_does_not_list_is_left_alone(self):
        (self.root / "__pycache__").mkdir()
        (self.root / "__pycache__" / "x.pyc").write_bytes(b"\0")
        assert manifest.verify(self.root) == []
