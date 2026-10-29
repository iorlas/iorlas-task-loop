"""One repo's bad .task-loop.json is a RED row for that repo (file and key named); doctor and the other repos go on."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: F401

from taskloop.adapters import ident
from taskloop.app.doctor import profiles
from taskloop.app.wire import doctor

ROOT = Path(__file__).resolve().parents[1]
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


class BadProfile(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        patch = mock.patch.dict(os.environ, dict(GIT_ENV, XDG_CONFIG_HOME=str(root / "cfg"), CLAUDE_CONFIG_DIR=str(root / "claude")))
        patch.start()
        self.addCleanup(patch.stop)
        self.good, self.bad = root / "good", root / "bad"
        for repo, profile in ((self.good, {"slots": {"count": 0}}), (self.bad, {"engine": {"checks": [{"id": "t", "cmd": "just test"}]}})):
            subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, env=os.environ)
            (repo / ".task-loop.json").write_text(json.dumps(profile))
            subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=os.environ)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "x"], check=True, env=os.environ)
        cfg = root / "cfg" / "task-loop"
        cfg.mkdir(parents=True)
        (cfg / "repos.json").write_text(json.dumps({str(self.good): {}, str(self.bad): {}}))

    def doctor(self, repo: Path, plugin_root: Path = ROOT) -> tuple[int, str]:
        out = io.StringIO()
        old = os.getcwd()
        os.chdir(repo)
        try:
            with contextlib.redirect_stdout(out):
                rc = doctor.run(plugin_root)
        finally:
            os.chdir(old)
        return rc, out.getvalue()

    def test_the_row_names_the_file_and_the_key(self) -> None:
        row = profiles.red_row(self.bad)
        self.assertTrue(row.startswith("RED "), row)
        self.assertIn(str(self.bad / ".task-loop.json"), row)
        self.assertIn("checks", row)
        self.assertEqual(profiles.red_row(self.good), "")

    def test_doctor_in_the_good_repo_succeeds_and_shows_the_bad_repos_row(self) -> None:
        rc, text = self.doctor(self.good)
        self.assertEqual(rc, 0, text)
        self.assertIn(f"RED {self.bad}", text)
        self.assertNotIn("Traceback", text)

    def test_doctor_fails_with_a_FAIL_line_when_the_plugin_has_no_ownership_section(self) -> None:
        bare = self.good.parent / "plugin"
        bare.mkdir()
        (bare / "AGENTS.md").write_text("# no section\n")
        rc, text = self.doctor(self.good, bare)
        self.assertEqual(rc, 1)
        self.assertRegex(text, r"(?m)^FAIL .*Ownership")

    def test_doctor_in_the_bad_repo_is_a_row_and_exit_1_not_a_traceback(self) -> None:
        rc, text = self.doctor(self.bad)
        self.assertEqual(rc, 1)
        self.assertEqual(sum(1 for ln in text.splitlines() if ln.startswith("RED ")), 1)

    def test_walking_the_registered_repos_skips_the_one_asked_from(self) -> None:
        rows = profiles.red_rows(profiles.registered(ident.config_dir() / "repos.json"), but=str(self.good))
        self.assertEqual(len(rows), 1)
        self.assertEqual(profiles.red_rows([str(self.bad)], but=str(self.bad)), [])


STALE: dict[str, object] = {"engine": {"checks": [{"id": "t", "cmd": "just test"}]}}  # a string check: bad
GOOD: dict[str, object] = {"engine": {"checks": [{"id": "t", "argv": ["just", "test"]}]}}


class SourceIsTheBaseCommit(unittest.TestCase):
    """The loop reads the profile off the base commit; doctor must read the same one, not a stale checkout."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patch = mock.patch.dict(os.environ, GIT_ENV)
        patch.start()
        self.addCleanup(patch.stop)
        self.repo = Path(tmp.name).resolve() / "r"
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True, env=os.environ)

    def commit(self, profile: dict[str, object], base: bool) -> None:
        (self.repo / ".task-loop.json").write_text(json.dumps(profile))
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"], check=True, env=os.environ)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "x"], check=True, env=os.environ)
        if base:
            subprocess.run(["git", "-C", str(self.repo), "update-ref", "refs/remotes/origin/main", "HEAD"], check=True, env=os.environ)

    def sha7(self) -> str:
        return subprocess.run(["git", "-C", str(self.repo), "rev-parse", "--short=7", "origin/main"], check=True, env=os.environ,
                              capture_output=True, text=True).stdout.strip()

    def test_a_stale_working_tree_under_a_good_base_commit_is_no_red_row(self) -> None:
        self.commit(GOOD, base=True)
        (self.repo / ".task-loop.json").write_text(json.dumps(STALE))
        self.assertEqual(profiles.red_row(self.repo), "")
        says: list[str] = []
        self.assertFalse(profiles.report(str(self.repo), self.repo / "none.json", says.append))
        self.assertEqual(says, [f"profile: {self.repo} read from base {self.sha7()}"])

    def test_a_bad_base_commit_is_a_row_naming_the_source(self) -> None:
        self.commit(STALE, base=True)
        (self.repo / ".task-loop.json").write_text(json.dumps(GOOD))
        row = profiles.red_row(self.repo)
        self.assertTrue(row.startswith("RED "), row)
        self.assertIn(f"(base {self.sha7()})", row)

    def test_no_base_commit_falls_back_to_the_working_tree(self) -> None:
        self.commit(GOOD, base=False)
        self.assertEqual(profiles.red_row(self.repo), "")
        (self.repo / ".task-loop.json").write_text(json.dumps(STALE))
        self.assertIn("(working tree)", profiles.red_row(self.repo))


if __name__ == "__main__":
    unittest.main()
