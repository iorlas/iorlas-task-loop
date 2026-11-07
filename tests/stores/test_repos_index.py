"""contracts/stores.py ReposStore: repos.json of this version is read and added to; a file of another version (the unversioned
map before STATEFILES) is an error naming the fix, for readers and writers alike, and is never read as empty or overwritten."""
import sys
from pathlib import Path

import pytest

from tltestkit.case import Case
from tltestkit.tmpdir import mkdtemp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tlkernel.paths import ConfigDir
from tlkernel.rowstores import ReposStore


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
