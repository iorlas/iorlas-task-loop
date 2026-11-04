"""The tl.py launcher: its verbs and output."""
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

import pytest
from support.case import Case

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "skills" / "task-loop"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: E402, F401
from support import homes  # noqa: E402

# isort: split
import contextlib  # noqa: E402

import tl  # noqa: E402
from support import (  # noqa: E402
    gitq,
    looptest,
    procsim,
    tlbd,
)
from support.engine_locks import put_lock  # noqa: E402
from support.spawn import port_git  # noqa: E402
from support.tlmain import tl_main  # noqa: E402

from taskloop.adapters import (  # noqa: E402
    pidcheck,
)
from taskloop.app.track import trail  # noqa: E402
from taskloop.app.wire import slots as wslots  # noqa: E402


def sh(*args, cwd):
    subprocess.run(list(args), cwd=cwd, check=True, capture_output=True)


class Base(Case):
    def setup_method(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        env = {"XDG_CONFIG_HOME": str(self.home / "cfg"), "APPDATA": str(self.home / "cfg"),
               "CLAUDE_CODE_SESSION_ID": "abcdef12-3456", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        os.environ.pop("TASK_LOOP_ACTOR", None)

    def teardown_method(self):
        self.env.stop()

        def force(fn, path, _):  # Windows: git's pack files are read-only
            os.chmod(path, stat.S_IWRITE)
            fn(path)
        shutil.rmtree(self.tmp.name, onerror=force)
        with contextlib.suppress(OSError):
            self.tmp.cleanup()


class RegisterCLI(Base):
    def setup_method(self):
        super().setup_method()
        self.repo = self.home / "repo"
        sh("git", "init", "-q", str(self.repo), cwd=self.home)
        self.config = self.home / "cfg" / "task-loop"
        self.registry = self.config / "repos.json"

    def cli(self, *args, cwd=None):
        return tl_main(*args, cwd=cwd or self.home)

    def assert_registered(self, result):
        assert result.returncode == 0, result.stderr
        assert result.stdout == "REGISTERED " + str(self.repo.resolve()) + "\n"
        assert result.stderr == ""
        repos = json.loads(self.registry.read_text())["repos"]
        assert str(self.repo.resolve()) in repos
        assert isinstance(repos[str(self.repo.resolve())]["added"], (int, float))

    def test_default_directory(self):
        self.assert_registered(self.cli("register", cwd=self.repo))
        assert [p for p in self.config.iterdir() if p.name != "locks"] == [self.registry]  # no tmp left

    def test_explicit_relative_subdirectory(self):
        (self.repo / "nested dir").mkdir()
        self.assert_registered(self.cli("register", "repo/nested dir"))

    def test_worktree_default_and_explicit_share_main_checkout(self):
        sh("git", "commit", "-qm", "init", "--allow-empty", cwd=self.repo)
        worktree = self.home / "linked"
        sh("git", "worktree", "add", "-q", "--detach", str(worktree), cwd=self.repo)
        self.assert_registered(self.cli("register", str(self.repo)))
        original = self.registry.read_bytes()
        self.assert_registered(self.cli("register", cwd=worktree))
        self.assert_registered(self.cli("register", str(worktree)))
        assert self.registry.read_bytes() == original
        assert len(json.loads(original)["repos"]) == 1

    def test_repeated_registration_preserves_entries_and_metadata(self):
        self.config.mkdir(parents=True)
        existing = {str(self.home / "other"): {"added": 123}}
        self.registry.write_text(json.dumps({"v": 1, "repos": existing}))
        self.assert_registered(self.cli("register", str(self.repo)))
        original = self.registry.read_bytes()
        self.assert_registered(self.cli("register", str(self.repo)))
        assert self.registry.read_bytes() == original
        repos = json.loads(original)["repos"]
        assert len(repos) == 2
        for path, metadata in existing.items():
            assert repos[path] == metadata

    def in_process(self, *args):
        out, err, cwd = io.StringIO(), io.StringIO(), os.getcwd()
        os.chdir(self.home)
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = tl.main(list(args))
        finally:
            os.chdir(cwd)
        return rc, out.getvalue(), err.getvalue()

    def test_invalid_input_leaves_configuration_unchanged(self):
        ordinary = self.home / "ordinary"
        ordinary.mkdir()
        file = self.home / "file"
        file.write_text("not a directory")
        original = b""
        for configured in (False, True):
            if configured:
                self.config.mkdir(parents=True)
                self.registry.write_text('{"existing": {"added": 123}}\n')
                original = self.registry.read_bytes()
            cases = [("register",), ("register", str(ordinary)),
                     ("register", str(self.home / "missing")), ("register", str(file)),
                     ("register", str(self.home / "missing\nwith newline"))]
            for args in cases:
                with self.subTest(configured=configured, args=args):
                    rc, out, err = self.in_process(*args)
                    assert rc == 1
                    assert out == ""
                    assert len(err.splitlines()) == 1
                    assert err.startswith("tl: "), err
                    if configured:
                        assert self.registry.read_bytes() == original
                        assert [p for p in self.config.iterdir() if p.name != "locks"] == [self.registry]  # no tmp left
                    else:
                        assert not self.config.parent.exists()

    def test_invalid_input_exits_1_with_one_tl_line_on_stderr_and_no_traceback(self):
        result = self.cli("register", str(self.home / "missing"))
        assert result.returncode == 1
        assert result.stdout == ""
        assert len(result.stderr.splitlines()) == 1
        assert result.stderr.startswith("tl: "), result.stderr
        assert "Traceback" not in result.stderr

    def test_help_documents_register_and_optional_directory(self):
        result = self.cli("--help")
        assert result.returncode == 0
        assert "register [DIR]" in result.stdout
        result = self.cli("register", "--help")
        assert result.returncode == 0
        assert "[DIR]" in result.stdout
        assert "current directory" in result.stdout
        assert not self.config.parent.exists()


class SlotReset(Base):
    """A slot reset must never lose a dead session's work."""

    def setup_method(self):
        super().setup_method()
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
        # a reset is about git; the slot-bead lookup gets an empty bd, so no real bd (absent on CI) is needed
        tlbd.install(self, result=tlbd.done("[]"))

    def teardown_method(self):
        os.chdir(self.cwd)
        super().teardown_method()

    def reset(self, bead):
        return tl.main(["slot", "reset", "s1", "--bead", bead])

    def test_clean_reset_makes_task_branch_and_keeps_ignored(self):
        (self.slot / "ignored").mkdir()
        (self.slot / "ignored" / "big").write_text("setup output")
        (self.slot / "junk.tmp").write_text("x")
        sh("git", "add", "junk.tmp", cwd=self.slot)
        sh("git", "commit", "-qm", "junk", cwd=self.slot)  # committed work on a detached head is not our concern
        assert self.reset("t-1") == 0
        assert gitq.git("symbolic-ref", "--short", "HEAD", cwd=str(self.slot)) == "task/t-1"
        assert (self.slot / "ignored" / "big").exists()

    def test_dirty_slot_work_is_committed_not_wiped(self):
        sh("git", "checkout", "-q", "-b", "task/t-0", cwd=self.slot)
        (self.slot / "a.txt").write_text("changed by a dead session\n")
        (self.slot / "new.txt").write_text("new\n")
        assert self.reset("t-1") == 0
        assert gitq.git("status", "--porcelain", cwd=str(self.slot)) == ""
        assert gitq.git("show", "task/t-0:new.txt", cwd=str(self.slot)) == "new"
        assert gitq.git("show", "task/t-0:a.txt", cwd=str(self.slot)) == "changed by a dead session"

    def test_reset_for_a_bead_keeps_its_existing_branch(self):
        sh("git", "checkout", "-q", "-b", "task/t-1", cwd=self.slot)
        (self.slot / "work.txt").write_text("reviewed work\n")
        sh("git", "add", "-A", cwd=self.slot)
        sh("git", "commit", "-qm", "wip (t-1): blocked", cwd=self.slot)
        sh("git", "checkout", "-q", "--detach", "origin/main", cwd=self.slot)
        assert self.reset("t-1") == 0
        assert gitq.git("symbolic-ref", "--short", "HEAD", cwd=str(self.slot)) == "task/t-1"
        assert (self.slot / "work.txt").read_text() == "reviewed work\n"

    def test_loop_folders_are_excluded_from_git_add(self):
        wslots.exclude_local(port_git(),str(self.repo), ".slots/", ".task/")
        wslots.exclude_local(port_git(),str(self.repo), ".slots/")
        exclude = (self.repo / ".git" / "info" / "exclude").read_text()
        assert exclude.split().count(".slots/") == 1
        assert ".slots" not in gitq.git("status", "--porcelain", "--untracked-files=all", cwd=str(self.repo))

    def test_detached_dirty_work_goes_to_wip_branch(self):
        (self.slot / "new.txt").write_text("new\n")
        assert self.reset("t-2") == 0
        wip = [b for b in gitq.git("branch", "--list", "wip/*", cwd=str(self.slot)).split() if b.startswith("wip/")]
        assert len(wip) == 1
        assert gitq.git("show", wip[0] + ":new.txt", cwd=str(self.slot)) == "new"

    def test_setup_runs_only_when_inputs_change(self):
        cfg = {
            "slots": {
                "count": 1,
                "setup": ["sh", "-c", "echo run >> setup.log"],
                "setup_inputs": ["a.txt"],
                "keep": ["setup.log"],
            }
        }
        def setup(cwd, env):
            with (cwd / "setup.log").open("a") as f:
                f.write("run\n")
            return 0, ""
        procsim.fake("sh -c 'echo run >> setup.log'", setup)
        (self.repo / ".task-loop.json").write_text(json.dumps(cfg))
        (self.slot / ".gitignore").write_text("ignored/\nsetup.log\n")
        sh("git", "add", "-A", cwd=self.slot)
        sh("git", "commit", "-qm", "ignore log", cwd=self.slot)
        sh("git", "push", "-q", "origin", "HEAD:main", cwd=self.slot)
        assert self.reset("t-1") == 0
        assert self.reset("t-2") == 0
        assert (self.slot / "setup.log").read_text().count("run") == 1


@pytest.mark.skipif(os.name == "nt", reason="the fixture's live process is a POSIX ps lookup")
class CutoverCheck(Base):
    def setup_method(self):
        super().setup_method()
        self.repo = self.home / "repo"
        self.repo.mkdir()
        sh("git", "init", "-q", cwd=self.repo)
        trail.register_repo(str(self.repo), homes.cfg())
        p = mock.patch.object(wslots, "slot_beads", return_value=[])
        p.start()
        self.addCleanup(p.stop)

    def check(self, *args):
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            rc = tl.main(["cutover", "check", *args])
        return rc, out.getvalue()

    def test_nothing_live_exits_0(self):
        rc, out = self.check()
        assert (rc, out.split()[0]) == (0, "CLEAR:")
    def test_a_live_loop_and_a_live_run_exit_1_and_are_listed_a_dead_one_is_not(self):
        child = subprocess.Popen(["sleep", "60"])
        self.addCleanup(child.wait)  # cleanups run last-in first-out: kill, then wait
        self.addCleanup(child.kill)
        looptest.write_state(str(self.repo), pid=child.pid, started=time.time(), t=time.time(), bead="x-9")
        put_lock(str(self.repo), {"pid": child.pid, "start": pidcheck.proc_start(child.pid), "bead": "x-7",
                                              "by": "engine", "started": time.time()})
        rc, out = self.check()
        assert rc == 1, out
        assert f"LIVE loop pid {child.pid} on {self.repo} running x-9" in out
        assert f"LIVE run in {self.repo}: engine pid {child.pid} runs x-7" in out
        rc, out = self.check("--json")
        assert (rc, sorted(x["kind"] for x in json.loads(out)["live"])) == (1, ["loop", "run"])
        child.kill()
        child.wait()
        assert self.check()[0] == 0


