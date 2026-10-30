"""contracts/stores.py ReposStore: repos.json of this version is read and added to; a file of another version (the unversioned
map before STATEFILES) is an error naming the fix, for readers and writers alike, and is never read as empty or overwritten."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.snapshots import ReposIndex
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


    def test_a_file_created_just_after_a_missed_read_is_no_repos_not_an_error(self) -> None:
        # the race tl-3u6.9 left: the read found no file, a writer created it, and a later exists() called it another version
        writer = ReposStore(ConfigDir(self.dir))
        real = type(self.store.path).read_text

        def miss_then_create(path: Path, *a: object, **k: object) -> str:
            if path == self.store.path and not path.exists():
                writer.write(ReposIndex())
                raise FileNotFoundError(path)
            return real(path, *a, **k)  # type: ignore[arg-type]
        with mock.patch.object(type(self.store.path), "read_text", miss_then_create):
            self.assertEqual(self.store.known(), [])

if __name__ == "__main__":
    unittest.main()
