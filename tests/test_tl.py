import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
import tl  # noqa: E402


def sh(*args, cwd):
    subprocess.run(list(args), cwd=cwd, check=True, capture_output=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        env = {"XDG_CONFIG_HOME": str(self.home / "cfg"), "APPDATA": str(self.home / "cfg"),
               "CLAUDE_CODE_SESSION_ID": "abcdef12-3456", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        os.environ.pop("TASK_LOOP_ACTOR", None)

    def tearDown(self):
        self.env.stop()

        def force(fn, path, _):  # Windows: git's pack files are read-only
            os.chmod(path, stat.S_IWRITE)
            fn(path)
        shutil.rmtree(self.tmp.name, onerror=force)
        try:
            self.tmp.cleanup()
        except OSError:
            pass


class Identity(Base):
    def test_actor_is_per_session(self):
        self.assertEqual(tl.actor(), "tl-abcdef12")

    def test_actor_without_session_id_is_still_per_process(self):
        os.environ.pop("CLAUDE_CODE_SESSION_ID")
        os.environ["CLAUDE_PID"] = "4242"
        self.assertTrue(tl.actor().endswith("-4242"))

    def test_actor_override(self):
        os.environ["TASK_LOOP_ACTOR"] = "me"
        self.assertEqual(tl.actor(), "me")

    def test_config_dir_is_created(self):
        self.assertTrue(tl.config_dir().is_dir())


class Records(Base):
    def test_event_appends_and_registers_repo(self):
        tl.event("claim", "x-1", repo=str(self.home), worktree="/w")
        tl.event("close", "x-1", repo=str(self.home))
        lines = (tl.config_dir() / "events.jsonl").read_text().splitlines()
        self.assertEqual([json.loads(l)["kind"] for l in lines], ["claim", "close"])
        self.assertEqual(json.loads(lines[0])["session"], "abcdef12-3456")
        self.assertIn(str(self.home), json.loads((tl.config_dir() / "repos.json").read_text()))

    def test_prune_keeps_recent(self):
        f = tl.config_dir() / "events.jsonl"
        old = json.dumps({"t": 0, "kind": "old"})
        new = json.dumps({"t": tl.now(), "kind": "new"})
        f.write_text((old + "\n") * 120000 + new + "\n")
        tl.prune_events()
        self.assertEqual([json.loads(l)["kind"] for l in f.read_text().splitlines()], ["new"])

    def test_hook_indexes_session(self):
        with mock.patch("sys.stdin", io.StringIO(json.dumps({"session_id": "s1", "transcript_path": "/t.jsonl"}))):
            self.assertEqual(tl.main(["hook", "session-start"]), 0)
        d = json.loads((tl.config_dir() / "sessions" / "s1.json").read_text())
        self.assertEqual(d["transcript"], "/t.jsonl")

    def test_hook_never_fails(self):
        with mock.patch("sys.stdin", io.StringIO("not json")):
            self.assertEqual(tl.main(["hook", "session-start"]), 0)


class SlotReset(Base):
    """A slot reset must never lose a dead session's work."""

    def setUp(self):
        super().setUp()
        self.origin = self.home / "origin.git"
        self.repo = self.home / "repo"
        sh("git", "init", "-q", "--bare", "-b", "main", str(self.origin), cwd=self.home)
        sh("git", "clone", "-q", str(self.origin), str(self.repo), cwd=self.home)
        (self.repo / "a.txt").write_text("a\n")
        (self.repo / ".gitignore").write_text("ignored/\n")
        sh("git", "add", "-A", cwd=self.repo)
        sh("git", "commit", "-qm", "init", cwd=self.repo)
        sh("git", "push", "-q", "origin", "HEAD:main", cwd=self.repo)
        (self.repo / ".task-loop.json").write_text(json.dumps({"slots": {"count": 1}}))
        self.slot = self.repo / ".slots" / "s1"
        sh("git", "worktree", "add", "-q", "--detach", str(self.slot), "origin/main", cwd=self.repo)
        self.cwd = os.getcwd()
        os.chdir(self.repo)

    def tearDown(self):
        os.chdir(self.cwd)
        super().tearDown()

    def reset(self, bead):
        return tl.main(["slot", "reset", "s1", "--bead", bead])

    def test_clean_reset_makes_task_branch_and_keeps_ignored(self):
        (self.slot / "ignored").mkdir()
        (self.slot / "ignored" / "big").write_text("setup output")
        (self.slot / "junk.tmp").write_text("x")
        sh("git", "add", "junk.tmp", cwd=self.slot)
        sh("git", "commit", "-qm", "junk", cwd=self.slot)  # committed work on a detached head is not our concern
        self.assertEqual(self.reset("t-1"), 0)
        self.assertEqual(tl.git("symbolic-ref", "--short", "HEAD", cwd=str(self.slot)), "task/t-1")
        self.assertTrue((self.slot / "ignored" / "big").exists())

    def test_dirty_slot_work_is_committed_not_wiped(self):
        sh("git", "checkout", "-q", "-b", "task/t-0", cwd=self.slot)
        (self.slot / "a.txt").write_text("changed by a dead session\n")
        (self.slot / "new.txt").write_text("new\n")
        self.assertEqual(self.reset("t-1"), 0)
        self.assertEqual(tl.git("status", "--porcelain", cwd=str(self.slot)), "")
        self.assertEqual(tl.git("show", "task/t-0:new.txt", cwd=str(self.slot)), "new")
        self.assertEqual(tl.git("show", "task/t-0:a.txt", cwd=str(self.slot)), "changed by a dead session")

    def test_loop_folders_are_excluded_from_git_add(self):
        tl.exclude_local(str(self.repo), ".slots/", ".task/")
        tl.exclude_local(str(self.repo), ".slots/")
        exclude = (self.repo / ".git" / "info" / "exclude").read_text()
        self.assertEqual(exclude.split().count(".slots/"), 1)
        self.assertNotIn(".slots", tl.git("status", "--porcelain", "--untracked-files=all", cwd=str(self.repo)))

    def test_detached_dirty_work_goes_to_wip_branch(self):
        (self.slot / "new.txt").write_text("new\n")
        self.assertEqual(self.reset("t-2"), 0)
        wip = [b for b in tl.git("branch", "--list", "wip/*", cwd=str(self.slot)).split() if b.startswith("wip/")]
        self.assertEqual(len(wip), 1)
        self.assertEqual(tl.git("show", wip[0] + ":new.txt", cwd=str(self.slot)), "new")

    def test_setup_runs_only_when_inputs_change(self):
        cfg = {"slots": {"count": 1, "setup": "echo run >> setup.log", "setup_inputs": ["a.txt"], "keep": ["setup.log"]}}
        (self.repo / ".task-loop.json").write_text(json.dumps(cfg))
        (self.slot / ".gitignore").write_text("ignored/\nsetup.log\n")
        sh("git", "add", "-A", cwd=self.slot)
        sh("git", "commit", "-qm", "ignore log", cwd=self.slot)
        sh("git", "push", "-q", "origin", "HEAD:main", cwd=self.slot)
        self.assertEqual(self.reset("t-1"), 0)
        self.assertEqual(self.reset("t-2"), 0)
        self.assertEqual((self.slot / "setup.log").read_text().count("run"), 1)


if __name__ == "__main__":
    unittest.main()
