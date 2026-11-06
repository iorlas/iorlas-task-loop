"""The child env is an allowlist (adapters/childenv.py): a check run through `tl check` sees only the allowlist and its declared env.

The probe check dumps its environment; nothing outside ALLOWED and the declared env may reach it. That is the guard. That a real gate
(task-loop's own `just check`, lifesim's checks) still passes under the list is too heavy for the real-test limit:
tests/live/test_allowlist_gates.py."""
import json
import os
import pwd
from pathlib import Path

from support.case import Case
from support.checked import run_checked
from support.tlmain import tl_main
from support.tmpdir import TemporaryDirectory

from taskloop.adapters.childenv import CHECK_HOME_NAMES, allowed, check_caches

ROOT = Path(__file__).resolve().parents[3]
IDENT = ["-c", "user.email=t@t", "-c", "user.name=t"]


def git(cwd: Path, *a: str) -> str:
    return run_checked(["git", *IDENT, *a], cwd, text=True).stdout


class ProbeChecks(Case):
    def setup_method(self):
        self.tmp = TemporaryDirectory()
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
        # `env -0` from the shell, not an interpreter: a loader (nix-ld) may put names like LD_LIBRARY_PATH into any python it starts
        probe = f"env -0 > {out_file}"
        (repo / ".task-loop.json").write_text(json.dumps({"engine": {"base": "main", "checks": [
            {"id": "probe", "argv": ["sh", "-c", probe], "env": {"DECLARED": "1"}, "run": "gate"}]}}))
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "probe")
        os.environ.setdefault("NOT_ON_THE_LIST", "x")
        self.addCleanup(os.environ.pop, "NOT_ON_THE_LIST", None)
        rc, out = self.check(repo, "probe")
        assert rc == 0, out
        seen = [kv.partition("=")[0] for kv in out_file.read_text().split("\0") if kv]
        engine_marks = ("DECLARED", "DELEGATE_DEPTH", "TASK_LOOP_WORKER")  # the check's own env, and what a child of the engine is told
        admitted = (*engine_marks, *CHECK_HOME_NAMES, *check_caches({}), "PWD", "SHLVL", "_", "__CF_USER_TEXT_ENCODING")  # macOS
        stray = [k for k in seen if not allowed(k) and k not in admitted and not k.startswith("XDG_")]
        assert stray == [], "names outside the allowlist reached the child"
        assert "NOT_ON_THE_LIST" not in seen
        assert "DECLARED" in seen
