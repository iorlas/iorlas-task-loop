"""One repo's bad .task-loop.json is a RED row for that repo (file and key named); doctor and the other repos go on."""
import argparse
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "task-loop"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401
import tl  # noqa: E402
from taskloop.app.doctor import profiles  # noqa: E402

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


class BadProfile(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        patch = mock.patch.dict(os.environ, dict(GIT_ENV, XDG_CONFIG_HOME=str(root / "cfg")))
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

    def doctor(self, repo: Path) -> tuple[int, str]:
        out = io.StringIO()
        old = os.getcwd()
        os.chdir(repo)
        try:
            with contextlib.redirect_stdout(out):
                rc = tl.cmd_doctor(argparse.Namespace())
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

    def test_doctor_in_the_bad_repo_is_a_row_and_exit_1_not_a_traceback(self) -> None:
        rc, text = self.doctor(self.bad)
        self.assertEqual(rc, 1)
        self.assertEqual(sum(1 for ln in text.splitlines() if ln.startswith("RED ")), 1)

    def test_walking_the_registered_repos_skips_the_one_asked_from(self) -> None:
        rows = profiles.red_rows(profiles.registered(tl.config_dir() / "repos.json"), but=str(self.good))
        self.assertEqual(len(rows), 1)
        self.assertEqual(profiles.red_rows([str(self.bad)], but=str(self.bad)), [])


if __name__ == "__main__":
    unittest.main()
