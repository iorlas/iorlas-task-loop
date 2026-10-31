"""The git pre-push hook with real git: tl's hooks dir comes from the ChildEnv builder (core.hooksPath through GIT_CONFIG_*), the hook
asks `tl green` per pushed tip (a stand-in tl here: green when the tree is listed), and the engine's push (TL_LAND) needs no --no-verify."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: E402, F401

from taskloop.adapters import childenv  # noqa: E402
from taskloop.app.wire.hook import write_hooks  # noqa: E402
from taskloop.contracts.env import Env  # noqa: E402

FAKE_TL = """#!/bin/sh
# green STEP --repo D --tree T --base B: green when T is a line of $GREEN; check --repo D: stamps D's HEAD tree (the plan ran)
echo "$@" >> "$CALLS"
if [ "$1" = green ]; then grep -qx "$6" "$GREEN"; exit $?; fi
if [ "$1" = check ]; then git -C "$3" rev-parse 'HEAD^{tree}' >> "$GREEN"; exit 0; fi
"""


class PrePush(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        t = Path(self.tmp.name)
        self.cfg, self.green, self.calls = t / "cfg", t / "green", t / "calls"
        self.green.write_text("")
        self.calls.write_text("")
        base = {"PATH": os.environ["PATH"], "HOME": str(t), "XDG_CONFIG_HOME": str(t), "GREEN": str(self.green), "CALLS": str(self.calls),
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        write_hooks(ROOT, Env(base))
        tl = t / "task-loop" / "bin" / "tl"
        tl.parent.mkdir(parents=True)
        tl.write_text(FAKE_TL)
        tl.chmod(0o755)
        # tl's own ChildEnv builder is what hands git the hooks dir: GREEN and CALLS ride through `extra`
        self.env = childenv.tool_env(base, {"GREEN": base["GREEN"], "CALLS": base["CALLS"]})
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
        with self.green.open("a") as f:
            f.write(self.git(self.repo, "rev-parse", rev + "^{tree}").stdout)

    def push(self, *refspecs, env=None):
        return self.git(self.repo, "push", "-q", "origin", *refspecs, env=env, check=False)

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
        self.assertIn("check --repo", self.calls.read_text())

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

    def test_the_engines_push_carries_tl_land_and_needs_no_no_verify(self):
        self.commit("b")
        (self.repo / "stray").write_text("x")  # not green, dirty: only TL_LAND lets it through
        r = self.push("HEAD:refs/heads/x", env={**self.env, "TL_LAND": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls.read_text(), "")

    def test_no_verify_still_beats_the_default(self):
        self.commit("b")
        (self.repo / "stray").write_text("x")
        self.assertEqual(self.push("--no-verify", "HEAD:refs/heads/x").returncode, 0)

    def test_a_repo_without_a_gate_step_has_nothing_to_ask(self):
        (self.repo / ".task-loop.json").write_text("{}")
        self.git(self.repo, "commit", "-qam", "profile")
        self.assertEqual(self.push("HEAD:refs/heads/x").returncode, 0)


if __name__ == "__main__":
    unittest.main()
