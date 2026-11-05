"""The release gate's cache: a hit needs the same tree and the same test selection, only a green run is remembered."""
import json
import os
import sys
import tempfile
from pathlib import Path

import pytest
from support.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support.checked import run_checked

from taskloop.adapters.git import RealGit
from taskloop.adapters.spawner import RealSpawner
from taskloop.app.release import gate, shell
from taskloop.app.release.cache import SuiteCache
from taskloop.app.release.shell import Abort, Shell
from taskloop.contracts.env import snapshot
from taskloop.contracts.paths import ConfigDir


class Verify(Case):
    def setup_method(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.repo = root / "repo"
        self.repo.mkdir()
        self.env = {"XDG_CONFIG_HOME": str(root / "cfg"), "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        saved = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v) for k, v in saved.items()])
        self.sh = self.shell_now()  # taken now: with the environment above
        self.git("init", "-q", "-b", "main")
        self.commit("a.txt", "one")
        self.ran: list[str] = []

    @staticmethod
    def shell_now() -> Shell:
        return shell.of(RealSpawner(snapshot()), RealGit(snapshot()), snapshot())

    def git(self, *a: str) -> None:
        run_checked(["git", *a], self.repo)

    def commit(self, name: str, text: str) -> None:
        (self.repo / name).write_text(text)
        self.git("add", "-A")
        self.git("commit", "-qm", text)

    def checks(self, repo: Path, sh: Shell) -> None:
        self.ran.append("ran")

    def red(self, repo: Path, sh: Shell) -> None:
        self.ran.append("red")
        raise Abort("the suite is red")

    def test_the_same_tree_under_the_same_command_runs_once(self):
        assert not gate.verify(self.repo, self.sh, self.checks)
        assert gate.verify(self.repo, self.sh, self.checks)
        assert self.ran == ["ran"]

    def test_a_changed_tree_runs_again(self):
        gate.verify(self.repo, self.sh, self.checks)
        self.commit("a.txt", "two")
        assert not gate.verify(self.repo, self.sh, self.checks)
        assert self.ran == ["ran", "ran"]

    def test_a_red_run_is_never_remembered_so_the_next_run_is_real(self):
        with pytest.raises(Abort):
            gate.verify(self.repo, self.sh, self.red)
        with pytest.raises(Abort):
            gate.verify(self.repo, self.sh, self.red)
        assert self.ran == ["red", "red"]

    def test_another_test_selection_is_a_miss(self):
        (self.repo / "dev").mkdir()
        (self.repo / "dev" / "affected.py").write_text("print(open('selection').read())\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "selector")
        (self.repo / "selection").write_text("tests/a.py\n")  # untracked: the tree stays, the selection (a moved origin/main) changes
        gate.verify(self.repo, self.sh, self.checks)
        (self.repo / "selection").write_text("tests/a.py\ntests/b.py\n")
        assert not gate.verify(self.repo, self.sh, self.checks)
        assert self.ran == ["ran", "ran"]

    def test_a_torn_cache_file_is_a_miss_not_a_crash(self):
        gate.verify(self.repo, self.sh, self.checks)
        f = Path(self.tmp.name) / "cfg" / "task-loop" / "releases" / "suite-green.json"
        f.write_text("{torn")
        assert not gate.verify(self.repo, self.sh, self.checks)
        greens = json.loads(f.read_text())["greens"]
        assert len(greens) == 1
        assert SuiteCache(ConfigDir(f.parents[1])).hit(greens[0]["tree"], greens[0]["command"])
