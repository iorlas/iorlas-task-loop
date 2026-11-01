"""Installed hooks invoke the real application judge and check service before any remote ref mutation."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: E402, F401

from taskloop.adapters import childenv  # noqa: E402
from taskloop.adapters.check_files import repo_key  # noqa: E402
from taskloop.adapters.git import RealGit  # noqa: E402
from taskloop.app.checks.cache import key_digest  # noqa: E402
from taskloop.app.wire.hook import write_hooks  # noqa: E402
from taskloop.contracts.checks import CheckResult, PassRecord  # noqa: E402
from taskloop.contracts.env import Env  # noqa: E402
from taskloop.contracts.ids import CheckId, TreeSha  # noqa: E402
from taskloop.contracts.paths import ConfigDir  # noqa: E402
from taskloop.contracts.runkey import BaseSha, Digest, RunKey  # noqa: E402
from taskloop.stores.real import real_stores  # noqa: E402

JUDGE_TL = """#!{python}
import argparse
import os
import sys
from pathlib import Path
sys.path[:0] = [{src!r}, {vendor!r}]
from taskloop.adapters.git import RealGit
from taskloop.adapters.spawner import RealSpawner
from taskloop.app.launch.push_judge import cmd_judge_push
from taskloop.contracts.env import Env
from taskloop.contracts.identity import Identity
with Path(os.environ['CALLS']).open('a') as log:
    log.write(' '.join(sys.argv[1:]) + '\\n')
env = Env(dict(os.environ))
who = Identity(actor='hook-test', home={config!r})
args = argparse.Namespace(repo=sys.argv[3])
raise SystemExit(cmd_judge_push(args, who=who, env=env, spawner=RealSpawner(env), git=RealGit(env)))
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
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
        self.env = childenv.tool_env(base, {"CALLS": base["CALLS"]})
        self.origin, self.repo = t / "origin.git", t / "repo"
        self.git(t, "init", "-q", "--bare", "-b", "main", str(self.origin))
        self.git(t, "clone", "-q", str(self.origin), str(self.repo))
        (self.repo / ".task-loop.json").write_text(json.dumps({"engine": {"checks": [{"id": "suite", "argv": ["true"], "run": "gate"}]}}))
        self.commit("a")
        self.git(self.repo, "push", "-q", "--no-verify", "origin", "HEAD:main")
        self.git(self.repo, "fetch", "-q")

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
        key = RunKey(check=CheckId("suite"), cmd=Digest("c"), config=Digest("g"), toolchain=Digest("t"),
                     tree=tree, base=base, inputs=Digest("i"), selected=Digest(""), env=Digest("e"))
        result = CheckResult(id=key.check, cmd="true", group="gate", exit=0, status="passed")
        repo = repo_key(RealGit(Env(self.env)), str(self.repo))
        real_stores(ConfigDir(self.cfg)).results(repo, key.check).of(key_digest(key)).write(
            PassRecord(key=key, result=result, tree=tree, base=base))

    def push(self, *refspecs, env=None):
        return self.git(self.repo, "push", "-q", "origin", *refspecs, env=env, check=False)


class PrePush(Base):
    def test_the_hooks_path_reaches_git_from_the_child_env(self):
        want = str(Path(self.tmp.name) / "task-loop" / "githooks")
        self.assertEqual(self.git(self.repo, "config", "core.hooksPath").stdout.strip(), want)

    def test_a_green_tip_passes(self):
        self.commit("b")
        self.stamp("HEAD")
        self.assertEqual(self.push("HEAD:refs/heads/x").returncode, 0)

    def test_a_red_or_unknown_tip_is_refused_when_the_worktree_is_not_that_head(self):
        tip = self.commit("b")
        self.commit("c")  # HEAD moved on and nothing is stamped: the tip pushed is neither green nor the checked-out HEAD
        r = self.push(f"{tip}:refs/heads/x")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("is not green", r.stderr)
        self.assertEqual(self.git(self.origin, "branch", "--list", "x").stdout, "")

    def test_the_head_that_is_not_green_runs_the_plan_then_passes(self):
        self.commit("b")
        self.assertEqual(self.push("HEAD:refs/heads/x").returncode, 0)
        self.assertIn("judge-push --repo", self.calls.read_text())
        self.assertTrue(list(self.cfg.rglob("*.json")), "the application check service must retain evidence")

    def test_a_dirty_worktree_does_not_run_the_plan(self):
        self.commit("b")
        (self.repo / "stray").write_text("x")
        self.assertNotEqual(self.push("HEAD:refs/heads/x").returncode, 0)

    def test_a_stack_with_a_stamped_top_passes_and_a_lower_tip_alone_does_not(self):
        low = self.commit("b")
        top = self.commit("c")
        self.stamp(top)
        self.assertEqual(self.push(f"{low}:refs/heads/low", f"{top}:refs/heads/top").returncode, 0)
        self.git(self.repo, "reset", "-q", "--hard", top)
        mid = self.commit("d")
        self.commit("e")  # HEAD is past mid, so the plan cannot run for it
        self.assertNotEqual(self.push(f"{mid}:refs/heads/mid").returncode, 0)

    def test_the_old_marker_cannot_authorize_an_ungreen_dirty_push(self):
        self.commit("b")
        (self.repo / "stray").write_text("x")
        r = self.push("HEAD:refs/heads/x", env={**self.env, "TL_LAND": "1"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("judge-push", self.calls.read_text())
        self.assertEqual(self.git(self.origin, "branch", "--list", "x").stdout, "")

    def test_an_unavailable_judge_refuses_before_remote_mutation(self):
        self.commit("b")
        (Path(self.tmp.name) / "task-loop/bin/tl").unlink()
        self.assertNotEqual(self.push("HEAD:refs/heads/x").returncode, 0)
        self.assertEqual(self.git(self.origin, "branch", "--list", "x").stdout, "")

    def test_an_erroring_judge_refuses_before_remote_mutation(self):
        self.commit("b")
        (Path(self.tmp.name) / "task-loop/bin/tl").write_text("#!/bin/sh\nexit 2\n")
        self.assertNotEqual(self.push("HEAD:refs/heads/x").returncode, 0)
        self.assertEqual(self.git(self.origin, "branch", "--list", "x").stdout, "")

    def test_an_undecodable_profile_refuses_before_remote_mutation(self):
        self.commit("b")
        self.stamp("HEAD")
        (self.repo / ".task-loop.json").write_text("{")
        self.assertNotEqual(self.push("HEAD:refs/heads/x").returncode, 0)
        self.assertEqual(self.git(self.origin, "branch", "--list", "x").stdout, "")

    def test_no_verify_still_beats_the_default(self):
        self.commit("b")
        (self.repo / "stray").write_text("x")
        self.assertEqual(self.push("--no-verify", "HEAD:refs/heads/x").returncode, 0)

    def test_a_repo_without_a_gate_step_has_nothing_to_ask(self):
        (self.repo / ".task-loop.json").write_text("{}")
        self.git(self.repo, "commit", "-qam", "profile")
        self.assertEqual(self.push("HEAD:refs/heads/x").returncode, 0)


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
        self.assertEqual(self.push("HEAD:refs/heads/x").returncode, 0)
        text = self.rec.read_text()
        self.assertIn("args: origin ", text)
        self.assertIn("refs/heads/x", text)

    def test_the_repos_hook_failing_refuses_the_push(self):
        self.recorder(rc=3)
        self.commit("b")
        self.stamp("HEAD")
        self.assertNotEqual(self.push("HEAD:refs/heads/x").returncode, 0)

    def test_tl_refusing_stops_before_the_repos_hook(self):
        self.recorder()
        tip = self.commit("b")
        self.commit("c")
        self.assertNotEqual(self.push(f"{tip}:refs/heads/x").returncode, 0)
        self.assertFalse(self.rec.exists())

    def test_the_old_marker_cannot_skip_the_repos_hook(self):
        self.recorder(rc=3)
        self.commit("b")
        self.stamp("HEAD")
        self.assertNotEqual(self.push("HEAD:refs/heads/x", env={**self.env, "TL_LAND": "1"}).returncode, 0)
        self.assertTrue(self.rec.exists())

    def test_the_original_hooks_path_is_followed(self):
        other = Path(self.tmp.name) / "myhooks"
        self.git(self.repo, "config", "core.hooksPath", str(other))  # the repo's own setting; tl's env value beats it, the chain finds it
        self.own_hook("exit 4\n", where=other)
        self.commit("b")
        self.stamp("HEAD")
        self.assertNotEqual(self.push("HEAD:refs/heads/x").returncode, 0)

    def test_another_hook_name_is_chained_too(self):
        self.own_hook("exit 5\n", name="pre-commit")
        (self.repo / "z").write_text("z")
        self.git(self.repo, "add", "-A")
        self.assertNotEqual(self.git(self.repo, "commit", "-q", "-m", "z", check=False).returncode, 0)

    def test_the_install_is_idempotent_and_writes_a_dispatcher_per_hook(self):
        before = {f.name: f.stat().st_mtime_ns for f in (Path(self.tmp.name) / "task-loop" / "githooks").iterdir()}
        write_hooks(ROOT, Env({"XDG_CONFIG_HOME": self.tmp.name}))
        after = {f.name: f.stat().st_mtime_ns for f in (Path(self.tmp.name) / "task-loop" / "githooks").iterdir()}
        self.assertEqual(before, after)
        self.assertIn("pre-push", after)
        self.assertIn("commit-msg", after)


@unittest.skipUnless(shutil.which("git-lfs") or subprocess.run(["git", "lfs", "version"], capture_output=True, check=False).returncode == 0,
                     "git-lfs is not installed on this box")
class Lfs(Base):
    def setUp(self):
        super().setUp()
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
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.objects(), "the LFS object was skipped")

    def test_a_repo_with_lfs_but_no_pre_push_hook_still_uploads(self):
        (self.repo / ".git" / "hooks" / "pre-push").unlink()
        (self.repo / "big.bin").write_text("payload2")
        self.git(self.repo, "add", "-A")
        self.git(self.repo, "commit", "-qm", "big")
        self.stamp("HEAD")
        self.git(self.repo, "config", "lfs.url", str(self.origin))
        self.assertEqual(self.push("HEAD:refs/heads/x").returncode, 0)
        self.assertTrue(self.objects(), "the LFS object was skipped")


if __name__ == "__main__":
    unittest.main()
