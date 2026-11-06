"""contracts/stores.py ReposStore: repos.json of this version is read and added to; a file of another version (the unversioned
map before STATEFILES) is an error naming the fix, for readers and writers alike, and is never read as empty or overwritten."""
import json
import sys
from pathlib import Path
from unittest import mock

import pytest
from support.case import Case
from support.tmpdir import mkdtemp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.contracts import wire
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.snapshots import ReposIndex
from taskloop.contracts.stores import ReposStore


class ReposIndexFile(Case):
    def setup_method(self) -> None:
        self.dir = Path(mkdtemp())
        self.store = ReposStore(ConfigDir(self.dir))

    def test_a_missing_file_is_no_repos_and_an_add_creates_it(self) -> None:
        assert self.store.known() == []
        assert self.store.add("/r/a", 1.0)
        assert not self.store.add("/r/a", 2.0)
        assert ReposStore(ConfigDir(self.dir)).known() == ["/r/a"]
        assert list(self.store.index().repos) == ["a"]

    def test_a_v1_file_is_converted_on_first_read_to_names_and_a_taken_name_keeps_the_first(self) -> None:
        a, b = self.repo("x/one"), self.repo("y/one")
        self.store.path.parent.mkdir(parents=True, exist_ok=True)
        self.store.path.write_text(json.dumps({"v": 1, "repos": {a: {"added": 1.0}, b: {"added": 2.0}}}), encoding="utf-8")
        assert self.store.known() == [a]
        assert wire.dump(self.store.index()) == {"v": 2, "repos": {"one": {"path": a, "added": 1.0}}}
        assert not self.store.path.exists() and ReposStore(ConfigDir(self.dir)).known() == [a]  # adopted into the row

    def test_the_name_is_the_origin_owner_and_name_or_the_folder_name(self) -> None:
        r = self.repo("work/tl", origin="git@github.com:iorlas/task-loop.git")
        assert self.store.add(r, 1.0)
        assert list(self.store.index().repos) == ["iorlas/task-loop"]
        assert self.store.path_of("iorlas/task-loop") == r
        assert self.store.path_of("task-loop") == r

    def test_an_add_under_a_taken_name_is_refused_and_says_the_holder(self) -> None:
        a, b = self.repo("x/one"), self.repo("y/one")
        assert self.store.add(a, 1.0)
        with pytest.raises(ValueError, match=r"taken by .*x/one"):
            self.store.add(b, 2.0)
        assert self.store.known() == [a]

    def test_a_lookup_refuses_an_unknown_and_an_ambiguous_name_and_says_the_fix(self) -> None:
        a = self.repo("w/a", origin="https://github.com/o1/shared.git")
        b = self.repo("w/b", origin="https://github.com/o2/shared.git")
        self.store.add(a, 1.0)
        self.store.add(b, 2.0)
        with pytest.raises(ValueError, match=r"ambiguous.*owner/name"):
            self.store.path_of("shared")
        with pytest.raises(ValueError, match=r"not registered.*tl register"):
            self.store.path_of("nope")
        assert self.store.path_of("o2/shared") == b

    def test_drop_missing_removes_only_the_entries_whose_folder_is_gone(self) -> None:
        a, b = self.repo("x/a"), self.repo("x/b")
        self.store.add(a, 1.0)
        self.store.add(b, 2.0)
        Path(b).rename(b + "-moved")
        assert self.store.drop_missing(lambda p: Path(p).is_dir()) == ["b"]
        assert self.store.known() == [a]

    def repo(self, rel: str, origin: str | None = None) -> str:
        folder = self.dir / "repos" / rel
        (folder / ".git").mkdir(parents=True)
        if origin:
            (folder / ".git" / "config").write_text(f'[remote "origin"]\n\turl = {origin}\n', encoding="utf-8")
        return str(folder)

    def test_an_unversioned_file_is_an_error_for_a_reader_and_a_writer_and_stays_as_it_was(self) -> None:
        old = json.dumps({"/r/a": {"added": 1.0}})
        self.store.path.parent.mkdir(parents=True, exist_ok=True)
        self.store.path.write_text(old, encoding="utf-8")
        with pytest.raises(ValueError, match="delete it"):
            self.store.known()
        with pytest.raises(ValueError, match="delete it"):
            self.store.add("/r/b", 2.0)
        assert self.store.path.read_text(encoding="utf-8") == old


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
            assert self.store.known() == []
