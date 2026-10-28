"""Doctor and the engine inspect the same committed base, even from a stale worktree."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import support.paths  # noqa: E402,F401  (ROOT/src on sys.path)
from support import tlbd  # noqa: E402
import engine  # noqa: E402
from taskloop.app.wire import slots as wslots  # noqa: E402
import tl  # noqa: E402
from taskloop.app.wire import doctor  # noqa: E402
from taskloop.adapters import gitrepo  # noqa: E402


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

    def doctor(self, cwd=None):
        result = subprocess.run([sys.executable, str(ROOT / "skills" / "task-loop" / "tl.py"), "doctor"],
                                cwd=cwd or self.wt, env=self.env, capture_output=True, text=True, check=True)
        self.assertEqual(result.stderr, "")
        return result.stdout

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
        self.assertEqual(wslots.load_cfg(str(self.wt)).checks[0].id, "new-base")
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
        self.assertEqual(wslots.load_cfg(str(self.wt)).checks[0].id, "custom")

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
        out = self.doctor()
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
        self.assertEqual(wslots.load_cfg(str(self.wt)).checks[0].id, "fallback")

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
                self.assertEqual(wslots.load_cfg(str(self.wt)).checks, [])

    def test_config_and_paths_use_one_resolved_commit(self):
        commit = self.advance_base(self.config("good", "old.txt"))
        real_git = gitrepo.git
        calls = []

        def moving_ref(*args, **kwargs):
            calls.append(args)
            result = real_git(*args, **kwargs)
            if args[:3] == ("rev-parse", "--verify", "-q"):
                self.git("update-ref", "refs/remotes/origin/main", "main")
            return result

        source = wslots.cfg_source(str(self.wt), moving_ref)
        self.assertEqual(doctor.git_warnings(str(self.wt), source, moving_ref), [])
        self.assertEqual(source[2], commit)
        self.assertIn(("show", commit + ":.task-loop.json"), calls)
        self.assertIn(("ls-tree", "-r", "--name-only", "-z", commit), calls)
        self.assertEqual(sum(c[:3] == ("rev-parse", "--verify", "-q") for c in calls), 1)


if __name__ == "__main__":
    unittest.main()


class DoctorBeads(unittest.TestCase):
    """tl-f52: doctor lists the open beads whose text names material no worktree holds."""

    def test_doctor_lists_the_offenders_and_not_the_clean_or_escaped(self):
        beads = [{"id": "x-1", "description": "see ~/Documents/Drop/arch-study-1025/84-self-hosting.md"},
                 {"id": "x-2", "description": "change engine.py"},
                 {"id": "x-3", "description": "study 84 s.2: facts inline", "labels": ["facts-inline"]},
                 {"id": "x-4", "acceptance_criteria": "matches 79-test-impact-and-land-gate.md"},
                 {"id": "x-5", "issue_type": "epic", "description": "study 49"}]
        with tlbd.bd_boundary(result=tlbd.done(json.dumps(beads))):
            out = doctor.bead_lint_warnings("/work/repo")
        self.assertEqual([w.split(":")[0] for w in out], ["bead x-1", "bead x-4"])
        self.assertTrue(all("needs inlined facts" in w for w in out))
