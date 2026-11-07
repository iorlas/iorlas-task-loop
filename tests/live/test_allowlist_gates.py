"""Live: a real gate still passes under the child-env allowlist (tlkernel/childenv.py).

task-loop's own gate (`just check`: ruff, pyrefly, import-linter, the rule tests) and lifesim's registered static checks (text,
blueprint: its `.task-loop.json` at origin/main, minus the gate keys this engine no longer reads) run through `tl check`. A variable a
real tool needs and the list lacks shows here as a red check; the fix is a line in ALLOWED with the reason. Too heavy for the real-test
time limit, so it runs only through `just test-live`. The guard itself (nothing outside the allowlist reaches a child) is the probe in
tests/checks/real/test_allowlist.py. Skipped where the repo or the tool is not on this machine."""
import json
import os
import pwd
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from support.checked import run_checked
from support.tlmain import tl_main

from tltestkit.case import Case
from tltestkit.tmpdir import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
LIFESIM = Path.home() / "Workspaces" / "lifesim"
LIFESIM_IDS = ("text", "blueprint")
IDENT = ["-c", "user.email=t@t", "-c", "user.name=t"]


def git(cwd: Path, *a: str) -> str:
    return run_checked(["git", *IDENT, *a], cwd, text=True).stdout


class RealGateChecks(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = str(Path(self.tmp.name, "cfg"))

    def check(self, repo: Path, *ids: str) -> tuple[int, str]:
        # the real tools (mise, uv, just) live under the real home; the suite runs with a home of its own
        home = pwd.getpwuid(os.getuid()).pw_dir
        r = tl_main("check", "--repo", str(repo), "--all", *ids, cwd=repo, env={"XDG_CONFIG_HOME": self.cfg, "HOME": home})
        return r.returncode, r.stdout + r.stderr

    def test_task_loops_own_gate_runs_through_the_allowlist(self):
        if not shutil.which("just"):
            pytest.skip("just is not installed")
        repo = Path(self.tmp.name, "task-loop")
        git(ROOT, "rev-parse", "HEAD")
        run_checked(["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(repo)], None)
        (repo / ".task-loop.json").write_text(json.dumps({"engine": {"base": "main", "checks": [
            {"id": "static", "argv": ["just", "check"], "group": "static", "run": "gate"}]}}))
        rc, out = self.check(repo, "static")
        assert rc == 0, out
        assert re.search(r"static\s+ok", out)

    def test_lifesims_registered_static_checks_run_through_the_allowlist(self):
        if not shutil.which("just") or not (LIFESIM / ".git").exists():
            pytest.skip("just or ~/Workspaces/lifesim is not here")
        shown = subprocess.run(["git", "-C", str(LIFESIM), "show", "origin/main:.task-loop.json"], capture_output=True, text=True,
                               check=False)
        if shown.returncode:
            pytest.skip("lifesim has no origin/main profile")
        profile = json.loads(shown.stdout)
        for gone in ("gate", "gate_only"):
            profile["engine"].pop(gone, None)
        repo = Path(self.tmp.name, "lifesim")
        repo.mkdir()
        archive = run_checked(["git", "-C", str(LIFESIM), "archive", "origin/main"], None)
        subprocess.run(["tar", "-x", "-C", str(repo)], input=archive.stdout, check=True)
        (repo / ".task-loop.json").write_text(json.dumps(profile))
        git(repo, "init", "-q", "-b", "main")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "lifesim at origin/main")
        rc, out = self.check(repo, *LIFESIM_IDS)
        assert rc == 0, out
        for check_id in LIFESIM_IDS:
            assert re.search(rf"{check_id}\s+ok", out)
