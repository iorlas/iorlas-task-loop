"""contracts/stores.py ReposStore: repos.json of this version is read and added to; a file of another version (the unversioned
map before STATEFILES) is an error naming the fix, for readers and writers alike, and is never read as empty or overwritten."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.stores import ReposStore


class ReposIndexFile(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.store = ReposStore(ConfigDir(self.dir))

    def test_a_missing_file_is_no_repos_and_an_add_creates_it(self) -> None:
        self.assertEqual(self.store.known(), [])
        self.assertTrue(self.store.add("/r/a", 1.0))
        self.assertFalse(self.store.add("/r/a", 2.0))
        self.assertEqual(ReposStore(ConfigDir(self.dir)).known(), ["/r/a"])

    def test_an_unversioned_file_is_an_error_for_a_reader_and_a_writer_and_stays_as_it_was(self) -> None:
        old = json.dumps({"/r/a": {"added": 1.0}})
        self.store.path.parent.mkdir(parents=True, exist_ok=True)
        self.store.path.write_text(old, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "delete it"):
            self.store.known()
        with self.assertRaisesRegex(ValueError, "delete it"):
            self.store.add("/r/b", 2.0)
        self.assertEqual(self.store.path.read_text(encoding="utf-8"), old)


if __name__ == "__main__":
    unittest.main()
