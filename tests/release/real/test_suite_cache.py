"""The release gate's suite cache: a hit needs the same tree and the same command, only a green run is remembered."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401  (ROOT/src on sys.path)

from taskloop.adapters.spawner import RealSpawner
from taskloop.app.release import shell, suite
from taskloop.app.release.cache import SuiteCache
from taskloop.app.release.shell import Abort, Shell
from taskloop.contracts.paths import ConfigDir

SH = shell.of(RealSpawner())


class Verify(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.repo = root / "repo"
        self.repo.mkdir()
        self.env = {"XDG_CONFIG_HOME": str(root / "cfg"), "TASK_LOOP_SUITE_HOST": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        saved = {k: os.environ.get(k) for k in self.env}
        os.environ.update(self.env)
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v) for k, v in saved.items()])
        self.git("init", "-q", "-b", "main")
        self.commit("a.txt", "one")
        self.ran: list[str] = []

    def git(self, *a: str) -> None:
        subprocess.run(["git", *a], cwd=self.repo, check=True, capture_output=True)

    def commit(self, name: str, text: str) -> None:
        (self.repo / name).write_text(text)
        self.git("add", "-A")
        self.git("commit", "-qm", text)

    def checks(self, tool_root: Path, repo: Path, sh: Shell) -> None:
        self.ran.append("ran")

    def red(self, tool_root: Path, repo: Path, sh: Shell) -> None:
        self.ran.append("red")
        raise Abort("the suite is red")

    def test_the_same_tree_under_the_same_command_runs_once(self):
        self.assertFalse(suite.verify(self.repo, self.repo, SH, self.checks))
        self.assertTrue(suite.verify(self.repo, self.repo, SH, self.checks))
        self.assertEqual(self.ran, ["ran"])

    def test_a_changed_tree_runs_again(self):
        suite.verify(self.repo, self.repo, SH, self.checks)
        self.commit("a.txt", "two")
        self.assertFalse(suite.verify(self.repo, self.repo, SH, self.checks))
        self.assertEqual(self.ran, ["ran", "ran"])

    def test_a_red_run_is_never_remembered_so_the_next_run_is_real(self):
        with self.assertRaises(Abort):
            suite.verify(self.repo, self.repo, SH, self.red)
        with self.assertRaises(Abort):
            suite.verify(self.repo, self.repo, SH, self.red)
        self.assertEqual(self.ran, ["red", "red"])

    def test_another_command_is_a_miss(self):
        suite.verify(self.repo, self.repo, SH, self.checks)
        del os.environ["TASK_LOOP_SUITE_HOST"]  # the container suite is another command
        self.assertFalse(suite.verify(self.repo, self.repo, SH, self.checks))
        self.assertEqual(self.ran, ["ran", "ran"])

    def test_a_torn_cache_file_is_a_miss_not_a_crash(self):
        suite.verify(self.repo, self.repo, SH, self.checks)
        f = Path(self.tmp.name) / "cfg" / "task-loop" / "releases" / "suite-green.json"
        f.write_text("{torn")
        self.assertFalse(suite.verify(self.repo, self.repo, SH, self.checks))
        greens = json.loads(f.read_text())["greens"]
        self.assertEqual(len(greens), 1)
        self.assertTrue(SuiteCache(ConfigDir(f.parents[1])).hit(greens[0]["tree"], greens[0]["command"]))


if __name__ == "__main__":
    unittest.main()
