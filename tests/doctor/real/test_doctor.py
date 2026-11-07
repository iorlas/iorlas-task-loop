"""Doctor and the engine inspect the same committed base, even from a stale worktree."""
import contextlib
import io
import json
import os
import sys
from pathlib import Path
from unittest import mock

import pytest

from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: E402, F401
from support.spawn import port_git  # noqa: E402
from support.tlmain import tl_main  # noqa: E402
from support.who import who  # noqa: E402

from taskloop.adapters.git import RealGit  # noqa: E402
from taskloop.app.doctor import (  # noqa: E402
    install,
    setup_checks,
)
from taskloop.app.slots import config as wslots_config  # noqa: E402
from taskloop.app.wire import doctor  # noqa: E402
from tlkernel.env import snapshot  # noqa: E402
from tltestkit.checked import run_checked  # noqa: E402


def shown(p):
    """A path as git and the engine print it: forward slashes and long names on Windows."""
    return Path(p).resolve().as_posix() if os.name == "nt" else str(p)


class DoctorSource(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.repo = self.root / "main"
        self.wt = self.root / "worker"
        stubs = self.root / "stubs"  # a bd that runs and opens: this repo has no beads database
        stubs.mkdir()
        (self.root / "gitconfig").write_text("[user]\n\tname = test\n\temail = test@example.invalid\n")
        (self.root / "scratch").mkdir()
        script = '#!/bin/sh\ncase "$1" in --version) echo "bd version 1.3.1";; *) echo "[]";; esac\n'
        (stubs / "bd").write_text(script)
        (stubs / "bd").chmod(0o755)
        # any bd of the host (the suite's failing one, a mise shim) would be a second build next to the stub
        others = [d for d in os.environ["PATH"].split(os.pathsep) if d and "tl-nobd-" not in d and not (Path(d) / "bd").exists()]
        self.env = dict(os.environ, PATH=os.pathsep.join([str(stubs), *others]),
                        GIT_AUTHOR_NAME="test", GIT_AUTHOR_EMAIL="test@example.invalid",
                        GIT_COMMITTER_NAME="test", GIT_COMMITTER_EMAIL="test@example.invalid",
                        GIT_CONFIG_GLOBAL=str(self.root / "gitconfig"), TMPDIR=str(self.root / "scratch"), GIT_CONFIG_NOSYSTEM="1",
                        XDG_CONFIG_HOME=str(self.root / "config"), CLAUDE_CONFIG_DIR=str(self.root / "claude"),
                        HOME=str(self.root / "home"))  # the PATH link the doctor reports is under HOME, not the host's ~/.local/bin
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
        return {"engine": dict(checks=[{"id": name, "argv": ["unused", "$TL_ARTIFACT_DIR"], "inputs": [inputs]}],
                               **{"writer_exec_allow": [["unused"]], **extra})}  # a repo that lists what may run has no WARN about it

    @staticmethod
    def write_cfg(repo, data):
        (repo / ".task-loop.json").write_text(json.dumps(data))

    def git(self, *args, cwd=None):
        return run_checked(["git", *args], cwd or self.repo, env=self.env, text=True).stdout.strip()

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
            assert result.returncode == 0
            assert result.stderr == ""
            return result.stdout
        out, here = io.StringIO(), os.getcwd()
        os.chdir(cwd or self.wt)
        try:
            with contextlib.redirect_stdout(out):
                assert doctor.run(ROOT, snapshot(), port_git(), who()) == 0
        finally:
            os.chdir(here)
        return out.getvalue()

    def test_stale_main_newer_base(self):
        commit = self.advance_base(self.config("new-base"))
        # The worker also has stale, uncommitted config; only the base's copy counts.
        self.write_cfg(self.wt, self.config("worker-only"))
        out = self.doctor()
        assert "check new-base:" in out
        assert "check stale:" not in out
        assert "check worker-only:" not in out
        assert "base origin/main at commit " + commit in out
        assert "stale" in (self.repo / ".task-loop.json").read_text()
        assert self.git("rev-parse", "HEAD") != commit
        assert wslots_config.load_cfg(str(self.wt), port_git()).checks[0].id == "new-base"
        assert "check new-base:" in self.doctor(self.repo)

    def test_worktree_and_nested_directory_use_base(self):
        commit = self.advance_base(self.config("nested-base"))
        nested = self.wt / "deep" / "folder"
        nested.mkdir(parents=True)
        for cwd in (self.wt, nested):
            with self.subTest(cwd=cwd):
                out = self.doctor(cwd)
                assert "check nested-base:" in out
                assert commit in out

    def test_custom_base_matches_engine(self):
        commit = self.advance_base(self.config("custom"), "refs/heads/release")
        self.write_cfg(self.wt, self.config("local", base="release"))
        out = self.doctor()
        assert "base release at commit " + commit in out
        assert "check custom:" in out
        assert "check stale:" not in out
        assert wslots_config.load_cfg(str(self.wt), port_git()).checks[0].id == "custom"

    def test_reports_exact_commit_with_warnings(self):
        commit = self.advance_base(self.config("bad-glob"))
        self.git("config", "extensions.worktreeConfig", "false")
        out = self.doctor()
        assert "base origin/main at commit " + commit in out
        assert "WARN check bad-glob:" in out
        assert "WARN extensions.worktreeConfig" in out
        assert "ok:" not in out

    def test_prints_the_effective_writer_family(self):
        self.advance_base(self.config("good", "old.txt", writer_family=["openai"]))
        assert "engine: writer_family: openai (every worker call carries --only-family" in self.doctor()
        self.advance_base(self.config("good", "old.txt"))
        assert "engine: writer_family: none" in self.doctor()

    def test_reports_exact_commit_when_ok(self):
        commit = self.advance_base(self.config("good", "old.txt"))
        install.write_hooks(ROOT, snapshot())  # the pre-push judge is installed: the doctor fails without it
        out = self.doctor(cli=True)  # the one run through tl.main
        assert "base origin/main at commit " + commit in out
        assert "ok: no setup problems found in " + shown(self.wt) in out
        assert "WARN" not in out

    def test_a_repo_with_no_exec_allow_list_is_warned_that_plan_check_argv_is_unrestricted(self):
        self.advance_base({"engine": {"checks": []}})
        out = self.doctor()
        assert "WARN plan check argv unrestricted" in out
        assert "ok: no setup problems" not in out

    def test_trailing_nul_does_not_match_a_directory_glob(self):
        commit = self.advance_base(self.config("directory-only", "**/"))
        for committed in (True, False):
            with self.subTest(committed=committed):
                if not committed:
                    self.git("update-ref", "-d", "refs/remotes/origin/main")
                out = self.doctor()
                assert "WARN check directory-only: inputs glob **/ matches no tracked file" in out
                if committed:
                    assert "base origin/main at commit " + commit in out
                else:
                    assert "base origin/main unresolved; no commit read" in out

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
                assert commit in out
                assert "check removed:" in out
                assert "check added:" not in out

    def test_unresolved_base_uses_invoking_worktree(self):
        self.write_cfg(self.wt, self.config("fallback", "local.txt", base="missing-base"))
        (self.wt / "local.txt").write_text("local\n")
        self.git("add", "local.txt", cwd=self.wt)
        nested = self.wt / "nested"
        nested.mkdir()
        out = self.doctor(nested)
        assert "working tree " + shown(self.wt) in out
        assert "base missing-base unresolved; no commit read" in out
        assert "ok:" in out
        assert wslots_config.load_cfg(str(self.wt), port_git()).checks[0].id == "fallback"

    def test_default_unresolved_base_falls_back(self):
        self.git("update-ref", "-d", "refs/remotes/origin/main")
        self.write_cfg(self.wt, self.config("local-fallback"))
        out = self.doctor()
        assert "base origin/main unresolved; no commit read" in out
        assert "check local-fallback:" in out
        assert "check stale:" not in out

    def test_a_missing_base_config_means_defaults_and_a_malformed_one_is_refused(self):
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
                if contents is None:
                    out = self.doctor()
                    assert "base origin/main at commit " + commit in out
                    assert out.count("WARN") == 1 and "WARN plan check argv unrestricted" in out  # defaults list nothing
                    assert wslots_config.load_cfg(str(self.wt), port_git()).checks == []
                else:
                    for refused_call in (self.doctor, lambda: wslots_config.load_cfg(str(self.wt), port_git())):
                        with pytest.raises(SystemExit) as refused:
                            refused_call()
                        assert refused.value.code == 78

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
        source = wslots_config.cfg_source(str(self.wt), moving_ref)
        assert setup_checks.git_warnings(str(self.wt), source, moving_ref) == []
        assert source[2] == commit
        assert ("show", commit + ":.task-loop.json") in calls
        assert ("ls-tree", commit) in calls
        assert sum(c[0] == "rev-parse" for c in calls) == 1


