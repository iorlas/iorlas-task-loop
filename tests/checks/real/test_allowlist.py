"""The child env is an allowlist (adapters/childenv.py): a check run through `tl check` sees only the allowlist and its declared env.

The probe check dumps its environment; nothing outside ALLOWED and the declared env may reach it. That is the guard. That a real gate
(task-loop's own `just check`, lifesim's checks) still passes under the list is too heavy for the real-test limit:
tests/live/test_allowlist_gates.py."""
import json
import os
import pwd
import subprocess
import tempfile
import unittest
from pathlib import Path

from support.tlmain import tl_main

from taskloop.adapters.childenv import allowed

ROOT = Path(__file__).resolve().parents[3]
IDENT = ["-c", "user.email=t@t", "-c", "user.name=t"]


def git(cwd: Path, *a: str) -> str:
    return subprocess.run(["git", *IDENT, *a], cwd=cwd, check=True, capture_output=True, text=True).stdout


class ProbeChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cfg = str(Path(self.tmp.name, "cfg"))

    def check(self, repo: Path, *ids: str) -> tuple[int, str]:
        # the real tools (mise, uv, just) live under the real home; the suite runs with a home of its own
        home = pwd.getpwuid(os.getuid()).pw_dir
        r = tl_main("check", "--repo", str(repo), "--all", *ids, cwd=repo, env={"XDG_CONFIG_HOME": self.cfg, "HOME": home})
        return r.returncode, r.stdout + r.stderr

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
