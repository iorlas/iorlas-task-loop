"""A slot's git can only touch that slot (tl-bxk.10.12). lifesim-1mm: a core.worktree written into the shared
.git/config pointed every slot's git at another folder. Real git, temp HOME and XDG_CONFIG_HOME, fake delegate."""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

from tlland.testing import FakeLandStage
from tltestkit import fake_route
from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

sys.path.insert(0, str(ROOT / "tests"))
from support import dlcall  # noqa: E402
from support import engine_case as te  # noqa: E402
from support.builders import make_engine  # noqa: E402
from support.fakes import FakeBeadStore  # noqa: E402
from support.spawn import port_git, real_spawner  # noqa: E402
from support.who import who  # noqa: E402

import tltestkit.shellkit  # noqa: E402
from taskloop.adapters import delegate as dl  # noqa: E402
from taskloop.adapters import (  # noqa: E402
    gitrepo,
)
from taskloop.adapters.gitrepo import pinned_env  # noqa: E402
from taskloop.app.doctor import setup_checks  # noqa: E402
from taskloop.app.run import engine  # noqa: E402
from tlkernel.env import snapshot  # noqa: E402
from tlkernel.ids import BeadId  # noqa: E402
from tlslots import config as wslots_config  # noqa: E402
from tlslots.config import cfg_source  # noqa: E402
from tltestkit import procsim  # noqa: E402
from tltestkit.checked import run_checked  # noqa: E402

GIT_KEYS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE")


def env_show(cwd, env):
    return 0, "[" + "|".join(env.get(k, "") for k in GIT_KEYS) + "]"


def env_pair(cwd, env):
    return 0, env.get("GIT_DIR", "") + "|" + env.get("GIT_WORK_TREE", "")


def sh(*a, cwd):
    return run_checked(list(a), str(cwd), text=True).stdout.strip()


class SlotGitTest(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory(ignore_cleanup_errors=True)
        home = Path(os.path.realpath(self.tmp.name))
        env = {"HOME": str(home), "XDG_CONFIG_HOME": str(home / "cfg"), "APPDATA": str(home / "cfg"),
               "CLAUDE_CODE_SESSION_ID": "sess1234-x", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_NOSYSTEM": "1"}
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(self.tmp.cleanup)
        origin, self.repo, self.wt = home / "o.git", home / "repo", home / "repo" / ".slots" / "s1"
        sh("git", "init", "-q", "--bare", "-b", "main", str(origin), cwd=home)
        sh("git", "clone", "-q", str(origin), str(self.repo), cwd=home)
        (self.repo / "a.txt").write_text("a\n")
        sh("git", "add", "-A", cwd=self.repo)
        sh("git", "commit", "-qm", "init", cwd=self.repo)
        sh("git", "push", "-q", "origin", "HEAD:main", cwd=self.repo)
        sh("git", "worktree", "add", "-q", "--detach", str(self.wt), "origin/main", cwd=self.repo)
        sh("git", "fetch", "-q", cwd=self.wt)
        self.decoy = home / "decoy"
        self.decoy.mkdir()
        (self.decoy / "decoy.txt").write_text("not this slot's\n")
        (self.decoy / "a.txt").write_text("a decoy a\n")

    def plant_decoy(self):
        sh("git", "config", "core.worktree", str(self.decoy), cwd=self.repo)  # the shared .git/config

    def decoy_state(self):
        return sorted((p.name, p.read_text()) for p in self.decoy.iterdir())

    def all_committed_paths(self):
        return sh("git", "--git-dir", str(self.repo / ".git"), "log", "--all", "--name-only", "--format=", cwd=self.repo)

    def test_the_slot_stops_before_its_first_step_when_the_shared_config_redirects_git(self):
        self.plant_decoy()
        before = self.decoy_state()
        script = fake_route.Script({"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]})
        store = FakeBeadStore()
        eng = make_engine(self.wt, script=script, store=store)
        rc = eng.run()
        closed = [c[3] for c in store.said("close")]
        blocked = [c[3] for c in store.said("comments", "add") if c[3].startswith("Blocked: ")]
        assert rc == 2
        assert eng.why.startswith("failed: tree: core.worktree is set"), eng.why
        assert script.calls == []  # no worker, reviewer or planner ever ran
        assert closed == []  # the bead is blocked, not closed
        assert blocked == []  # an engine fault: the bead stays open, nobody is asked
        assert eng.stores.asks.get(BeadId("t-1")) is None  # a wrong tree is the slot's fault, not a question for the owner
        assert "git config --unset core.worktree" in eng.why
        assert str(self.repo) in eng.why
        assert "config" in eng.why  # names the setting and the file it came from
        trace = [json.loads(x) for x in eng.log_path.read_text().splitlines()]
        assert any(r["kind"] == "transition" and r.get("cause") == "wrong_tree" for r in trace)
        assert self.decoy_state() == before
        assert "decoy.txt" not in self.all_committed_paths()
        assert sh("git", "--git-dir", str(self.repo / ".git"), "branch", "--list", "task/*", cwd=self.repo) == ""

    def test_core_bare_true_stops_the_run_too(self):
        sh("git", "config", "core.bare", "true", cwd=self.repo)
        eng = engine.Engine(
            BeadId("t-1"), str(self.wt), wslots_config.load_cfg(str(self.wt), port_git()), env=snapshot(), spawner=real_spawner(),
                git=port_git(), who=who(),
        lander_factory=FakeLandStage)
        with pytest.raises(engine.Blocked) as cm:
            eng.assert_tree("write")
        assert "core.bare" in cm.value.why

    def test_a_clean_slot_passes_the_tree_assert(self):
        eng = engine.Engine(
            BeadId("t-1"), str(self.wt), wslots_config.load_cfg(str(self.wt), port_git()), env=snapshot(), spawner=real_spawner(),
                git=port_git(), who=who(),
        lander_factory=FakeLandStage)
        eng.assert_tree("plan")

    def test_pinned_git_stays_in_the_slot_whatever_the_shared_config_says(self):
        self.plant_decoy()
        eng = engine.Engine(
            BeadId("t-1"), str(self.wt), wslots_config.load_cfg(str(self.wt), port_git()), env=snapshot(), spawner=real_spawner(),
                git=port_git(), who=who(),
        lander_factory=FakeLandStage)
        assert os.path.realpath(eng.git.toplevel(str(self.wt))) == str(self.wt)
        (self.wt / "f.txt").write_text("f\n")
        eng.accepted_new = ["f.txt"]  # an untracked file is staged only when a review accepts it or a plan stage lists it (tl-bxk.10.24)
        assert eng.checkout.stage_all(check=True) == 0
        staged = sh("git", "--git-dir", str(self.repo / ".git" / "worktrees" / "s1"), "--work-tree", str(self.wt),
                    "diff", "--cached", "--name-only", cwd=self.wt)
        assert staged == "f.txt"  # only the slot's own path; nothing from the decoy

    def test_stage_all_takes_only_the_slots_status_paths_deletions_and_untracked_included(self):
        eng = engine.Engine(
            BeadId("t-1"), str(self.wt), wslots_config.load_cfg(str(self.wt), port_git()), env=snapshot(), spawner=real_spawner(),
                git=port_git(), who=who(),
        lander_factory=FakeLandStage)
        (self.wt / "a.txt").unlink()
        (self.wt / "new file.txt").write_text("n\n")
        eng.accepted_new = ["new file.txt"]
        assert eng.checkout.stage_all(check=True) == 0
        assert sh("git", "diff", "--cached", "--name-status", cwd=self.wt).split("\n") == ["D\ta.txt", "A\tnew file.txt"]

    @tltestkit.shellkit.POSIX_CHECK
    def test_workers_and_checks_are_not_pinned_but_the_engines_own_git_is(self):
        def worker(cmd, **kw):  # the delegate call: what git variables its request hands the worker's environment
            env_names = [k for k in GIT_KEYS if k in kw["request"].worker_env]
            return subprocess.CompletedProcess(cmd, 0, json.dumps(fake_route.answer(fake_route.contract(), None, "r1", False,
                                                                                    {"env": env_names})), "")
        show, pair = procsim.fake("env-show", env_show), procsim.fake("env-pair", env_pair)
        with mock.patch.dict(os.environ, {"GIT_DIR": "/x", "GIT_WORK_TREE": "/y", "GIT_INDEX_FILE": "/z"}):
            r = dlcall.call(
                dl.Resolved(Path(self.tmp.name), "delegate.api", fake_route.CONTRACT, "explicit"),
                "worker",
                "p",
                {"type": "object"},
                str(self.wt),
                worker,
                timeout_s=30,
            )
            eng = engine.Engine(
                BeadId("t-1"), str(self.wt), wslots_config.load_cfg(str(self.wt), port_git()), env=snapshot(), spawner=real_spawner(),
                    git=port_git(), who=who(),
            lander_factory=FakeLandStage)
            rc, tail = eng.sh([show])
            assert r.data["env"] == []
            assert (rc, tail) == (0, "[||]")
            rc, tail = eng.sh([pair], pin=True)
        gitdir = os.path.realpath(str(self.repo / ".git" / "worktrees" / "s1"))
        d, w = tail.split("|")
        assert (os.path.realpath(d), os.path.realpath(w)) == (gitdir, str(self.wt))
        assert pinned_env(self.repo)["GIT_DIR"] == str(self.repo / ".git")

    @tltestkit.shellkit.POSIX_CHECK
    def test_a_check_runs_git_on_another_repo(self):
        other = Path(self.tmp.name) / "other"
        sh("git", "init", "-q", "-b", "main", str(other), cwd=self.tmp.name)
        (other / "o.txt").write_text("o\n")
        sh("git", "add", "-A", cwd=other)
        sh("git", "commit", "-qm", "o", cwd=other)
        sha = sh("git", "rev-parse", "HEAD", cwd=other)
        eng = engine.Engine(
            BeadId("t-1"), str(self.wt), wslots_config.load_cfg(str(self.wt), port_git()), env=snapshot(), spawner=real_spawner(),
                git=port_git(), who=who(),
        lander_factory=FakeLandStage)
        rc, tail = eng.sh(["git", "-C", str(other), "rev-parse", "HEAD"])
        assert (rc, tail) == (0, sha)
        rc, tail = eng.sh(["git", "-C", str(other), "cat-file", "-e", sha])
        assert rc == 0

    def test_a_worker_that_redirects_git_is_caught_after_its_node(self):
        decoy = self.decoy

        class Planting(fake_route.Script):
            def reply(self, role, prompt, schema, cwd, *a, **kw):
                out = super().reply(role, prompt, schema, cwd, *a, **kw)
                if role == "worker":
                    sh("git", "config", "core.worktree", str(decoy), cwd=cwd)
                return out

        script = Planting({"plan": [te.PLAN], "write": [te.WRITE], "review": [te.CLEAN]})
        before = self.decoy_state()
        store = FakeBeadStore()
        eng = make_engine(self.wt, script=script, store=store)
        rc = eng.run()
        landed = store.said("close") + store.said("provenance", "record")  # neither a close nor a land record
        assert rc == 2
        assert "after write" in eng.why
        assert eng.why.startswith("failed: tree: core.worktree is set"), eng.why
        assert "review" not in [c[0] for c in script.calls]
        assert landed == []
        assert self.decoy_state() == before
        assert "decoy.txt" not in self.all_committed_paths()
        # only the engine's pinned wip checkpoint of the slot's own file; nothing reached origin
        assert sorted(self.all_committed_paths().split()) == ["a.txt", "f.txt"]
        assert "task/" not in sh("git", "ls-remote", "origin", cwd=self.wt)

    def test_samefile_compares_folders_and_falls_back_to_realpath(self):
        link = Path(self.tmp.name) / "link"
        link.symlink_to(self.wt)
        assert gitrepo.same_dir(link, self.wt)
        assert not gitrepo.same_dir(self.decoy, self.wt)
        assert gitrepo.same_dir(link / "nope", self.wt / "nope")

    def test_doctor_warns_when_worktree_config_is_off(self):
        source = cfg_source(str(self.repo), port_git())
        assert any("extensions.worktreeConfig" in w for w in setup_checks.git_warnings(str(self.repo), source, port_git()))
        sh("git", "config", "extensions.worktreeConfig", "true", cwd=self.repo)
        assert setup_checks.git_warnings(str(self.repo), cfg_source(str(self.repo), port_git()), port_git()) == []
