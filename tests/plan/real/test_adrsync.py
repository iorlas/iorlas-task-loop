"""The ADR files at a commit, read through real git into the cache."""
import subprocess
from pathlib import Path

from support import homes
from support.spawn import port_git

from tlkernel import adrfiles
from tlkernel.adrs import AdrStore
from tlkernel.ledger import Adr
from tlwork.plan import adrsync

REPO = "/r/adrsync-real"


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def repo_with(tmp_path: Path, files: dict[str, str]) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "t@t")
    git(tmp_path, "config", "user.name", "t")
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text(text)
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "adrs")
    return tmp_path


def test_the_files_at_a_commit_fill_the_cache_and_a_repo_without_the_folder_has_none(tmp_path):
    one = Adr(id="ADR-1", n=1, repo=REPO, text="Saves stay v1.", question="q", answer="a", ask="x-1", bead="t-1", key="k", t=1.0)
    wt = repo_with(tmp_path, {"README.md": "x", f"{adrfiles.DIR}/0001-saves-stay-v1.md": adrfiles.render(one)})
    store = AdrStore.at(homes.cfg(), REPO)
    adrsync.refresh(port_git(), str(wt), "HEAD", REPO, store)
    assert store.all() == [one]
    (tmp_path / "e").mkdir()
    empty = repo_with(tmp_path / "e", {"README.md": "x"})
    adrsync.refresh(port_git(), str(empty), "HEAD", REPO, store)
    assert store.all() == []
