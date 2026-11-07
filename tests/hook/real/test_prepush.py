"""Installed hooks invoke the real application judge and check service before any remote ref mutation."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: E402, F401

from taskloop.adapters.git import RealGit  # noqa: E402
from taskloop.app.doctor.install import write_hooks  # noqa: E402
from taskloop.stores.real import real_stores  # noqa: E402
from tlgate import authorization  # noqa: E402
from tlgate.cache import InputKeys, RunMemo  # noqa: E402
from tlgate.domain.specs import gate_items  # noqa: E402
from tlgate.execution import check_env  # noqa: E402
from tlkernel import childenv  # noqa: E402
from tlkernel.check_files import repo_key  # noqa: E402
from tlkernel.checks import CheckResult  # noqa: E402
from tlkernel.env import Env  # noqa: E402
from tlkernel.ids import TreeSha  # noqa: E402
from tlkernel.paths import ConfigDir  # noqa: E402
from tlkernel.rowstores import ReposStore  # noqa: E402
from tlkernel.runkey import BaseSha  # noqa: E402

JUDGE_TL = """#!{python}
import argparse
import os
import sys
from pathlib import Path
sys.path[:0] = [{src!r}, {vendor!r}]
from taskloop.adapters.git import RealGit
from taskloop.adapters.spawner import RealSpawner
from taskloop.app.launch.push_judge import cmd_judge_push
from taskloop.cli.ctx import declare_stage_parts
from tlkernel.env import Env
from tlkernel.identity import Identity
declare_stage_parts()
with Path(os.environ['CALLS']).open('a') as log:
    log.write(' '.join(sys.argv[1:]) + '\\n')
env = Env(dict(os.environ))
who = Identity(actor='hook-test', home={config!r})
args = argparse.Namespace(repo=sys.argv[3])
raise SystemExit(cmd_judge_push(args, who=who, env=env, spawner=RealSpawner(env), git=RealGit(env)))
"""


class Base(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        self.cfg, self.calls = t / "cfg", t / "calls"
        self.calls.write_text("")
        base = {"PATH": os.environ["PATH"], "HOME": str(t), "XDG_CONFIG_HOME": str(t), "CALLS": str(self.calls),
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        write_hooks(ROOT, Env(base))
        tl = t / "task-loop" / "bin" / "tl"
        tl.parent.mkdir(parents=True)
        tl.write_text(JUDGE_TL.format(python=sys.executable, src=str(ROOT / "src"),
                                     vendor=str(ROOT / "skills/task-loop/_vendor"), config=str(self.cfg)))
        tl.chmod(0o755)
        # tl's own ChildEnv builder hands git the hooks dir; the recorder path rides through `extra`.
        self.plain = base  # no hooks path: what `git lfs install` needs to write into the repo's own hooks
        # the stub shim judges, not this install
        self.env = childenv.without(childenv.tool_env(base, {"CALLS": base["CALLS"]}), "TL_JUDGE_TL")
        self.origin, self.repo = t / "origin.git", t / "repo"
        self.git(t, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.git(t, "clone", "-q", str(self.origin), str(self.repo))
        (self.repo / ".task-loop.json").write_text(json.dumps({"engine": {"checks": [{"id": "suite", "argv": ["true"], "run": "gate"}]}}))
        self.commit("a")
        self.git(self.repo, "push", "-q", "--no-verify", "origin", "HEAD:main")
        self.git(self.repo, "fetch", "-q")
        self.register(self.repo)

    def register(self, *repos):
        """The `repos` row of factory.db beside bin/tl, written by the production store: the hook judges only the repos listed there."""
        store = ReposStore(ConfigDir(Path(self.tmp.name) / "task-loop"))
        for r in repos:
            store.add(str(Path(r).resolve()), 1.0)

    def git(self, cwd, *args, env=None, check=True):
        r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=env or self.env, check=False)
        if check and r.returncode:
            raise AssertionError(r.stderr)
        return r

    def commit(self, name):
        (self.repo / name).write_text(name)
        self.git(self.repo, "add", "-A")
        self.git(self.repo, "commit", "-q", "-m", name)
        return self.git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def stamp(self, rev):
        tree = TreeSha(self.git(self.repo, "rev-parse", rev + "^{tree}").stdout.strip())
        base = BaseSha(self.git(self.repo, "rev-parse", "origin/main").stdout.strip())
        env, wt = Env(self.env), str(self.repo)
        git = RealGit(env)
        cfg = authorization.profile(git, wt, tree)
        engine_env = {**childenv.reaching(childenv.current_env(env)), **check_env()}
        memo = RunMemo(real_stores(ConfigDir(self.cfg)), repo_key(git, wt), InputKeys(git, wt, tree), base, engine_env)
        for step in gate_items(cfg):
            key = memo.key(step)
            assert key is not None
            result = CheckResult(id=step.id, cmd=step.cmd, group=step.group, exit=0, status="passed")
            memo.remember(key, result, 1, "")

    def push(self, *refspecs, env=None):
        return self.git(self.repo, "push", "-q", "origin", *refspecs, env=env, check=False)


class PrePush(Base):
    def test_the_hooks_path_reaches_git_from_the_child_env(self):
        want = str(Path(self.tmp.name) / "task-loop" / "githooks")
        assert self.git(self.repo, "config", "core.hooksPath").stdout.strip() == want

    def test_a_green_tip_passes(self):
        self.commit("b")
        self.stamp("HEAD")
        assert self.push("HEAD:refs/heads/x").returncode == 0

    def test_a_task_push_needs_no_receipts_even_with_a_dirty_worktree(self):
        self.commit("b")
        (self.repo / "stray").write_text("x")
        assert self.push("HEAD:refs/heads/task/x").returncode == 0
        assert "judge-push --repo" in self.calls.read_text()
        assert not list(self.cfg.rglob("*.json")), "a task push must not run the check service"

    def test_a_red_or_unknown_tip_is_refused_when_the_worktree_is_not_that_head(self):
        tip = self.commit("b")
        self.commit("c")  # HEAD moved on and nothing is stamped: the tip pushed is neither green nor the checked-out HEAD
        r = self.push(f"{tip}:refs/heads/main")
        assert r.returncode != 0
        assert "is not green" in r.stderr
        assert self.git(self.origin, "rev-parse", "main").stdout.strip() != tip

    def test_the_head_that_is_not_green_is_refused_without_running_the_plan_then_passes_once_stamped(self):
        self.commit("b")
        refused = self.push("HEAD:refs/heads/main")
        assert refused.returncode != 0
        assert "is not green" in refused.stderr
        assert not list(self.cfg.rglob("*.json")), "the judge reads receipts and never runs the gate"
        self.stamp("HEAD")
        assert self.push("HEAD:refs/heads/main").returncode == 0
        assert "judge-push --repo" in self.calls.read_text()

    def test_a_dirty_worktree_does_not_run_the_plan(self):
        self.commit("b")
        (self.repo / "stray").write_text("x")
        assert self.push("HEAD:refs/heads/main").returncode != 0

    def test_a_mixed_push_with_a_stamped_base_passes_and_an_unproven_base_does_not(self):
        low = self.commit("b")
        top = self.commit("c")
        self.stamp(top)
        assert self.push(f"{low}:refs/heads/low", f"{top}:refs/heads/main").returncode == 0
        self.git(self.repo, "reset", "-q", "--hard", top)
        mid = self.commit("d")
        self.commit("e")  # HEAD is past mid, so the plan cannot run for it
        assert self.push(f"{mid}:refs/heads/main").returncode != 0

    def test_the_old_marker_cannot_authorize_an_ungreen_dirty_push(self):
        self.commit("b")
        (self.repo / "stray").write_text("x")
        tip = self.git(self.repo, "rev-parse", "HEAD").stdout.strip()
        r = self.push("HEAD:refs/heads/main", env={**self.env, "TL_LAND": "1"})
        assert r.returncode != 0
        assert "judge-push" in self.calls.read_text()
        assert self.git(self.origin, "rev-parse", "main").stdout.strip() != tip

    def test_an_unavailable_judge_refuses_before_remote_mutation(self):
        self.commit("b")
        (Path(self.tmp.name) / "task-loop/bin/tl").unlink()
        assert self.push("HEAD:refs/heads/x").returncode != 0
        assert self.git(self.origin, "branch", "--list", "x").stdout == ""

    def test_an_erroring_judge_refuses_before_remote_mutation(self):
        self.commit("b")
        (Path(self.tmp.name) / "task-loop/bin/tl").write_text("#!/bin/sh\nexit 2\n")
        assert self.push("HEAD:refs/heads/x").returncode != 0
        assert self.git(self.origin, "branch", "--list", "x").stdout == ""

    def test_an_undecodable_profile_refuses_before_remote_mutation(self):
        (self.repo / ".task-loop.json").write_text("{")
        self.commit("b")
        assert self.push("HEAD:refs/heads/x").returncode != 0
        assert self.git(self.origin, "branch", "--list", "x").stdout == ""

    def test_no_verify_still_beats_the_default(self):
        self.commit("b")
        (self.repo / "stray").write_text("x")
        assert self.push("--no-verify", "HEAD:refs/heads/x").returncode == 0

    def test_a_tip_cannot_remove_the_base_gate(self):
        (self.repo / ".task-loop.json").write_text("{}")
        self.git(self.repo, "commit", "-qam", "profile")
        result = self.push("HEAD:refs/heads/x")
        assert result.returncode != 0
        assert "profile_changed:" in result.stderr
        assert self.git(self.origin, "branch", "--list", "x").stdout == ""


class Foreign(Base):
    """A repo tl does not manage (no .task-loop.json, not registered) inherits tl's core.hooksPath from a child env: its pushes pass."""

    def fresh(self, name="foreign"):
        t = Path(self.tmp.name)
        origin, work = t / f"{name}-origin.git", t / name
        self.git(t, "init", "-q", "--bare", "-b", "main", str(origin))
        work.mkdir()
        self.git(work, "init", "-q", "-b", "main")
        (work / "a").write_text("a")
        self.git(work, "add", "-A")
        self.git(work, "commit", "-q", "-m", "a")
        self.git(work, "remote", "add", "origin", str(origin))
        return work

    def test_the_first_push_to_a_fresh_origin_passes(self):
        work = self.fresh()
        r = self.git(work, "push", "-q", "-u", "origin", "main", check=False)
        assert r.returncode == 0, r.stderr

    def judge(self, work):
        tip = self.git(work, "rev-parse", "HEAD").stdout.strip()
        tl = Path(self.tmp.name) / "task-loop" / "bin" / "tl"
        return subprocess.run([str(tl), "judge-push", "--repo", str(work)], input=f"refs/heads/main {tip} refs/heads/main {'0' * 40}\n",
                              capture_output=True, text=True, env=self.env, check=False)

    def test_the_judge_alone_allows_a_first_push_without_a_profile_or_a_base(self):
        r = self.judge(self.fresh())
        assert r.returncode == 0, r.stderr

    def test_the_judge_refuses_a_first_push_that_carries_a_profile(self):
        work = self.fresh("owned")
        (work / ".task-loop.json").write_text("{}")
        self.git(work, "add", "-A")
        self.git(work, "commit", "-q", "-m", "profile")
        assert self.judge(work).returncode != 0

    def test_a_registered_repo_is_still_judged(self):
        work = self.fresh("mine")
        self.register(self.repo, work)
        (work / ".task-loop.json").write_text("{")
        self.git(work, "add", "-A")
        self.git(work, "commit", "-q", "-m", "bad profile")
        assert self.git(work, "push", "-q", "-u", "origin", "main", check=False).returncode != 0


class Chain(Base):
    """The repo's own hooks still run behind tl's (git-lfs's shim, prek): same arguments, same stdin, the first failure's exit code."""

    def own_hook(self, body, name="pre-push", where=None):
        d = Path(where) if where else self.repo / ".git" / "hooks"
        d.mkdir(parents=True, exist_ok=True)
        f = d / name
        f.write_text("#!/bin/sh\n" + body)
        f.chmod(0o755)

    def recorder(self, rc=0):
        self.rec = Path(self.tmp.name) / "rec"
        self.own_hook(f'echo "args: $@" >> {self.rec}; cat >> {self.rec}; exit {rc}\n')

    def test_the_repos_pre_push_gets_the_arguments_and_the_refs_on_stdin(self):
        self.recorder()
        self.commit("b")
        self.stamp("HEAD")
        assert self.push("HEAD:refs/heads/x").returncode == 0
        text = self.rec.read_text()
        assert "args: origin " in text
        assert "refs/heads/x" in text

    def test_the_repos_hook_does_not_inherit_tls_hooks_path(self):
        """A repo hook that runs a test suite must not hand tl's core.hooksPath to the tmp repos that suite pushes in."""
        seen = Path(self.tmp.name) / "seen"
        self.own_hook(f'git config --get core.hooksPath > {seen}\nexit 0\n')
        self.commit("b")
        self.stamp("HEAD")
        assert self.push("HEAD:refs/heads/x").returncode == 0
        assert "githooks" not in seen.read_text(), seen.read_text()

    def test_the_repos_hook_failing_refuses_the_push(self):
        self.recorder(rc=3)
        self.commit("b")
        self.stamp("HEAD")
        assert self.push("HEAD:refs/heads/x").returncode != 0

    def test_tl_refusing_stops_before_the_repos_hook(self):
        self.recorder()
        tip = self.commit("b")
        self.commit("c")
        assert self.push(f"{tip}:refs/heads/main").returncode != 0
        assert not self.rec.exists()

    def test_the_old_marker_cannot_skip_the_repos_hook(self):
        self.recorder(rc=3)
        self.commit("b")
        self.stamp("HEAD")
        assert self.push("HEAD:refs/heads/x", env={**self.env, "TL_LAND": "1"}).returncode != 0
        assert self.rec.exists()

    def test_the_original_hooks_path_is_followed(self):
        other = Path(self.tmp.name) / "myhooks"
        self.git(self.repo, "config", "core.hooksPath", str(other))  # the repo's own setting; tl's env value beats it, the chain finds it
        self.own_hook("exit 4\n", where=other)
        self.commit("b")
        self.stamp("HEAD")
        assert self.push("HEAD:refs/heads/x").returncode != 0

    def test_another_hook_name_is_chained_too(self):
        self.own_hook("exit 5\n", name="pre-commit")
        (self.repo / "z").write_text("z")
        self.git(self.repo, "add", "-A")
        assert self.git(self.repo, "commit", "-q", "-m", "z", check=False).returncode != 0

    def test_the_install_is_idempotent_and_writes_a_dispatcher_per_hook(self):
        before = {f.name: f.stat().st_mtime_ns for f in (Path(self.tmp.name) / "task-loop" / "githooks").iterdir()}
        write_hooks(ROOT, Env({"XDG_CONFIG_HOME": self.tmp.name}))
        after = {f.name: f.stat().st_mtime_ns for f in (Path(self.tmp.name) / "task-loop" / "githooks").iterdir()}
        assert before == after
        assert "pre-push" in after
        assert "commit-msg" in after


HAS_LFS = shutil.which("git-lfs") or subprocess.run(["git", "lfs", "version"], capture_output=True, check=False).returncode == 0


@pytest.mark.skipif(not HAS_LFS, reason="git-lfs is not installed on this box")
class Lfs(Base):
    def setup_method(self):
        super().setup_method()
        self.git(self.repo, "lfs", "install", "--local", env=self.plain)  # writes the git-lfs shims into .git/hooks, the repo's own hooks
        (self.repo / ".gitattributes").write_text("*.bin filter=lfs diff=lfs merge=lfs -text\n")
        self.git(self.repo, "add", "-A")
        self.git(self.repo, "commit", "-qm", "attrs")
        self.stamp("HEAD")

    def objects(self):
        return [p for p in (self.origin / "lfs" / "objects").rglob("*") if p.is_file()]

    def test_a_plain_push_of_an_lfs_pointer_uploads_the_object(self):
        (self.repo / "big.bin").write_text("payload")
        self.git(self.repo, "add", "-A")
        self.git(self.repo, "commit", "-qm", "big")
        self.stamp("HEAD")
        self.git(self.repo, "config", "lfs.url", str(self.origin))
        r = self.push("HEAD:refs/heads/x")
        assert r.returncode == 0, r.stderr
        assert self.objects(), "the LFS object was skipped"

    def test_a_repo_with_lfs_but_no_pre_push_hook_still_uploads(self):
        (self.repo / ".git" / "hooks" / "pre-push").unlink()
        (self.repo / "big.bin").write_text("payload2")
        self.git(self.repo, "add", "-A")
        self.git(self.repo, "commit", "-qm", "big")
        self.stamp("HEAD")
        self.git(self.repo, "config", "lfs.url", str(self.origin))
        assert self.push("HEAD:refs/heads/x").returncode == 0
        assert self.objects(), "the LFS object was skipped"
