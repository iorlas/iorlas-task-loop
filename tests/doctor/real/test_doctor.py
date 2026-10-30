"""Doctor and the engine inspect the same committed base, even from a stale worktree."""
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

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: E402, F401
from support.spawn import port_git  # noqa: E402
from support.tlmain import tl_main  # noqa: E402
from support.who import who  # noqa: E402

from taskloop.adapters.git import RealGit  # noqa: E402
from taskloop.app.wire import doctor  # noqa: E402
from taskloop.app.wire import slots as wslots  # noqa: E402
from taskloop.contracts.env import snapshot  # noqa: E402


def shown(p):
    """A path as git and the engine print it: forward slashes and long names on Windows."""
    return Path(p).resolve().as_posix() if os.name == "nt" else str(p)


class DoctorSource(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / "main"
        self.wt = self.root / "worker"
        self.env = dict(os.environ, GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@example.invalid",
                        GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.invalid",
                        GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                        XDG_CONFIG_HOME=str(self.root / "config"), CLAUDE_CONFIG_DIR=str(self.root / "claude"))
        patch = mock.patch.dict(os.environ, self.env)
        patch.start()
        self.addCleanup(patch.stop)
        self.git("init", "-q", "-b", "main", str(self.repo), cwd=self.root)
        self.git("config", "extensions.worktreeConfig", "true")
        self.write_cfg(self.repo, self.config("stale"))
        (self.repo / "old.txt").write_text("old\n")
        self.commit(self.repo)
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")
        self.git("worktree", "add", "-q", "-b", "worker", str(self.wt))

    @staticmethod
    def config(name, inputs="missing/**", **extra):
        return {"engine": dict(checks=[{"id": name, "argv": ["unused"], "inputs": [inputs]}], **extra)}

    @staticmethod
    def write_cfg(repo, data):
        (repo / ".task-loop.json").write_text(json.dumps(data))

    def git(self, *args, cwd=None):
        return subprocess.run(["git", *args], cwd=cwd or self.repo, env=self.env,
                              text=True, capture_output=True, check=True).stdout.strip()

    def commit(self, repo):
        self.git("add", "-A", cwd=repo)
        self.git("commit", "-qm", "fixture", cwd=repo)
        return self.git("rev-parse", "HEAD", cwd=repo)

    def advance_base(self, cfg, ref="refs/remotes/origin/main"):
        self.write_cfg(self.wt, cfg)
        commit = self.commit(self.wt)
        self.git("update-ref", ref, commit)
        return commit

    def doctor(self, cwd=None, cli=False):
        """The doctor's report from `cwd`: through doctor.run, or through `tl doctor` (tl.main) when `cli`."""
        if cli:
            result = tl_main("doctor", cwd=cwd or self.wt, env=self.env)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.stderr, "")
            return result.stdout
        out, here = io.StringIO(), os.getcwd()
        os.chdir(cwd or self.wt)
        try:
            with contextlib.redirect_stdout(out):
                self.assertEqual(doctor.run(ROOT, snapshot(), port_git(), who()), 0)
        finally:
            os.chdir(here)
        return out.getvalue()

    def test_stale_main_newer_base(self):
        commit = self.advance_base(self.config("new-base"))
        # The worker also has stale, uncommitted config; only the base's copy counts.
        self.write_cfg(self.wt, self.config("worker-only"))
        out = self.doctor()
        self.assertIn("check new-base:", out)
        self.assertNotIn("check stale:", out)
        self.assertNotIn("check worker-only:", out)
        self.assertIn("base origin/main at commit " + commit, out)
        self.assertIn("stale", (self.repo / ".task-loop.json").read_text())
        self.assertNotEqual(self.git("rev-parse", "HEAD"), commit)
        self.assertEqual(wslots.load_cfg(str(self.wt), port_git()).checks[0].id, "new-base")
        self.assertIn("check new-base:", self.doctor(self.repo))

    def test_worktree_and_nested_directory_use_base(self):
        commit = self.advance_base(self.config("nested-base"))
        nested = self.wt / "deep" / "folder"
        nested.mkdir(parents=True)
        for cwd in (self.wt, nested):
            with self.subTest(cwd=cwd):
                out = self.doctor(cwd)
                self.assertIn("check nested-base:", out)
                self.assertIn(commit, out)

    def test_custom_base_matches_engine(self):
        commit = self.advance_base(self.config("custom"), "refs/heads/release")
        self.write_cfg(self.wt, self.config("local", base="release"))
        out = self.doctor()
        self.assertIn("base release at commit " + commit, out)
        self.assertIn("check custom:", out)
        self.assertNotIn("check stale:", out)
        self.assertEqual(wslots.load_cfg(str(self.wt), port_git()).checks[0].id, "custom")

    def test_reports_exact_commit_with_warnings(self):
        commit = self.advance_base(self.config("bad-glob"))
        self.git("config", "extensions.worktreeConfig", "false")
        out = self.doctor()
        self.assertIn("base origin/main at commit " + commit, out)
        self.assertIn("WARN check bad-glob:", out)
        self.assertIn("WARN extensions.worktreeConfig", out)
        self.assertNotIn("ok:", out)

    def test_reports_exact_commit_when_ok(self):
        commit = self.advance_base(self.config("good", "old.txt"))
        out = self.doctor(cli=True)  # the one run through tl.main
        self.assertIn("base origin/main at commit " + commit, out)
        self.assertIn("ok: no setup problems found in " + shown(self.wt), out)
        self.assertNotIn("WARN", out)

    def test_trailing_nul_does_not_match_a_directory_glob(self):
        commit = self.advance_base(self.config("directory-only", "**/"))
        for committed in (True, False):
            with self.subTest(committed=committed):
                if not committed:
                    self.git("update-ref", "-d", "refs/remotes/origin/main")
                out = self.doctor()
                self.assertIn("WARN check directory-only: inputs glob **/ matches no tracked file", out)
                if committed:
                    self.assertIn("base origin/main at commit " + commit, out)
                else:
                    self.assertIn("base origin/main unresolved; no commit read", out)

    def test_base_tracked_paths(self):
        (self.wt / "old.txt").unlink()
        (self.wt / "new.txt").write_text("new\n")
        cfg = {"engine": {"checks": [
            {"id": "added", "argv": ["x"], "inputs": ["new.txt"]},
            {"id": "removed", "argv": ["x"], "inputs": ["old.txt"]}]}}
        commit = self.advance_base(cfg)
        # Both the stale main index and worker index now disagree with the base tree.
        (self.wt / "new.txt").unlink()
        (self.wt / "old.txt").write_text("local\n")
        self.git("add", "-A", cwd=self.wt)
        for cwd in (self.repo, self.wt):
            with self.subTest(cwd=cwd):
                out = self.doctor(cwd)
                self.assertIn(commit, out)
                self.assertIn("check removed:", out)
                self.assertNotIn("check added:", out)

    def test_unresolved_base_uses_invoking_worktree(self):
        self.write_cfg(self.wt, self.config("fallback", "local.txt", base="missing-base"))
        (self.wt / "local.txt").write_text("local\n")
        self.git("add", "local.txt", cwd=self.wt)
        nested = self.wt / "nested"
        nested.mkdir()
        out = self.doctor(nested)
        self.assertIn("working tree " + shown(self.wt), out)
        self.assertIn("base missing-base unresolved; no commit read", out)
        self.assertIn("ok:", out)
        self.assertEqual(wslots.load_cfg(str(self.wt), port_git()).checks[0].id, "fallback")

    def test_default_unresolved_base_falls_back(self):
        self.git("update-ref", "-d", "refs/remotes/origin/main")
        self.write_cfg(self.wt, self.config("local-fallback"))
        out = self.doctor()
        self.assertIn("base origin/main unresolved; no commit read", out)
        self.assertIn("check local-fallback:", out)
        self.assertNotIn("check stale:", out)

    def test_missing_or_malformed_base_config_does_not_fall_back(self):
        for contents in (None, "{invalid json"):
            with self.subTest(contents=contents):
                config = self.wt / ".task-loop.json"
                if contents is None:
                    config.unlink()
                else:
                    config.write_text(contents)
                commit = self.commit(self.wt)
                self.git("update-ref", "refs/remotes/origin/main", commit)
                self.write_cfg(self.wt, self.config("local-only"))
                out = self.doctor()
                self.assertIn("base origin/main at commit " + commit, out)
                self.assertIn("ok:", out)
                self.assertNotIn("WARN", out)
                self.assertEqual(wslots.load_cfg(str(self.wt), port_git()).checks, [])

    def test_config_and_paths_use_one_resolved_commit(self):
        commit = self.advance_base(self.config("good", "old.txt"))
        calls = []
        test = self

        class MovingRef(RealGit):
            """A base that moves between the commit's two reads: the answer of the first one must be the one used."""

            def rev_parse(self, d, rev):
                calls.append(("rev-parse", rev))
                out = super().rev_parse(d, rev)
                test.git("update-ref", "refs/remotes/origin/main", "main")
                return out

            def show(self, d, rev, path):
                calls.append(("show", f"{rev}:{path}"))
                return super().show(d, rev, path)

            def ls_tree(self, d, rev, *paths, recursive=False):
                calls.append(("ls-tree", rev))
                return super().ls_tree(d, rev, *paths, recursive=recursive)

        moving_ref = MovingRef(snapshot())
        source = wslots.cfg_source(str(self.wt), moving_ref)
        self.assertEqual(doctor.git_warnings(str(self.wt), source, moving_ref), [])
        self.assertEqual(source[2], commit)
        self.assertIn(("show", commit + ":.task-loop.json"), calls)
        self.assertIn(("ls-tree", commit), calls)
        self.assertEqual(sum(c[0] == "rev-parse" for c in calls), 1)


if __name__ == "__main__":
    unittest.main()


