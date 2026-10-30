"""The child env is an allowlist (adapters/childenv.py): the repos' own registered checks still run through it.

task-loop's own gate (`just check`: ruff, pyrefly, import-linter, the rule tests) and lifesim's registered static checks (text,
blueprint: its `.task-loop.json` at origin/main, minus the gate keys this engine no longer reads) run through `tl check`, which builds
every check's environment from the process's with `tool_env`. A variable a real tool needs and the list lacks shows here as a red check;
the fix is a line in ALLOWED with the reason. Skipped where the repo or the tool is not on this machine."""
import json
import os
import pwd
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from support.tlmain import tl_main

from taskloop.adapters.childenv import allowed

ROOT = Path(__file__).resolve().parents[3]
LIFESIM = Path.home() / "Workspaces" / "lifesim"
LIFESIM_IDS = ("text", "blueprint")
IDENT = ["-c", "user.email=t@t", "-c", "user.name=t"]


def git(cwd: Path, *a: str) -> str:
    return subprocess.run(["git", *IDENT, *a], cwd=cwd, check=True, capture_output=True, text=True).stdout


class RealRepoChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = str(Path(self.tmp.name, "cfg"))

    def check(self, repo: Path, *ids: str) -> tuple[int, str]:
        # the real tools (mise, uv, just) live under the real home; the suite runs with a home of its own
        home = pwd.getpwuid(os.getuid()).pw_dir
        r = tl_main("check", "--repo", str(repo), "--all", *ids, cwd=repo, env={"XDG_CONFIG_HOME": self.cfg, "HOME": home})
        return r.returncode, r.stdout + r.stderr

    def test_task_loops_own_gate_runs_through_the_allowlist(self):
        if not shutil.which("just"):
            self.skipTest("just is not installed")
        repo = Path(self.tmp.name, "task-loop")
        git(ROOT, "rev-parse", "HEAD")
        subprocess.run(["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(repo)], check=True, capture_output=True)
        (repo / ".task-loop.json").write_text(json.dumps({"engine": {"base": "main", "checks": [
            {"id": "static", "argv": ["just", "check"], "group": "static", "run": "gate"}]}}))
        rc, out = self.check(repo, "static")
        self.assertEqual(rc, 0, out)
        self.assertRegex(out, r"static\s+ok")

    def test_lifesims_registered_static_checks_run_through_the_allowlist(self):
        if not shutil.which("just") or not (LIFESIM / ".git").exists():
            self.skipTest("just or ~/Workspaces/lifesim is not here")
        shown = subprocess.run(["git", "-C", str(LIFESIM), "show", "origin/main:.task-loop.json"], capture_output=True, text=True,
                               check=False)
        if shown.returncode:
            self.skipTest("lifesim has no origin/main profile")
        profile = json.loads(shown.stdout)
        for gone in ("gate", "gate_only"):
            profile["engine"].pop(gone, None)
        repo = Path(self.tmp.name, "lifesim")
        repo.mkdir()
        archive = subprocess.run(["git", "-C", str(LIFESIM), "archive", "origin/main"], capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(repo)], input=archive.stdout, check=True)
        (repo / ".task-loop.json").write_text(json.dumps(profile))
        git(repo, "init", "-q", "-b", "main")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "lifesim at origin/main")
        rc, out = self.check(repo, *LIFESIM_IDS)
        self.assertEqual(rc, 0, out)
        for check_id in LIFESIM_IDS:
            self.assertRegex(out, rf"{check_id}\s+ok")

    def test_the_child_sees_the_allowlist_and_nothing_else(self):
        repo = Path(self.tmp.name, "probe")
        repo.mkdir()
        git(repo, "init", "-q", "-b", "main")
        out_file = Path(self.tmp.name, "seen.json")
        probe = f"import json,os; json.dump(sorted(os.environ), open({str(out_file)!r}, 'w'))"
        (repo / ".task-loop.json").write_text(json.dumps({"engine": {"base": "main", "checks": [
            {"id": "probe", "argv": ["python3", "-c", probe], "env": {"DECLARED": "1"}, "run": "gate"}]}}))
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "probe")
        os.environ.setdefault("NOT_ON_THE_LIST", "x")
        self.addCleanup(os.environ.pop, "NOT_ON_THE_LIST", None)
        rc, out = self.check(repo, "probe")
        self.assertEqual(rc, 0, out)
        seen = json.loads(out_file.read_text())
        engine_marks = ("DECLARED", "DELEGATE_DEPTH", "TASK_LOOP_WORKER")  # the check's own env, and what a child of the engine is told
        stray = [k for k in seen if not allowed(k) and k not in (*engine_marks, "PWD", "SHLVL", "_")]  # PWD and the like: set by the shell
        self.assertEqual(stray, [], "names outside the allowlist reached the child")
        self.assertNotIn("NOT_ON_THE_LIST", seen)
        self.assertIn("DECLARED", seen)


if __name__ == "__main__":
    unittest.main()
