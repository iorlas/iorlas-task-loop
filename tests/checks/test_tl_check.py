"""`tl check`: the repo's registry of checks run by a person, in a real worktree, through the engine's own runner."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TL = ROOT / "skills" / "task-loop" / "tl.py"
PY = sys.executable


def argv(code):
    return [PY, "-c", code]


CHECKS = [
    {"id": "fmt", "argv": argv("print('fmt fine')"), "group": "static", "run": "gate"},
    {"id": "unit", "argv": argv("import sys; print('unit saw a failure'); sys.exit(1)"), "run": "gate"},
    {"id": "docs", "argv": argv("print('docs')"), "run": "stage"},
    {"id": "ui", "argv": argv("print('ui')"), "run": "gate", "when": ["ui/**"]},
]


class TlCheck(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name, "repo")
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "t@t")
        self.git("config", "user.name", "t")
        self.profile(CHECKS)
        self.git("add", "-A")
        self.git("commit", "-qm", "init")

    def git(self, *a):
        subprocess.run(["git", *a], cwd=self.repo, check=True, capture_output=True)

    def profile(self, checks):
        (self.repo / ".task-loop.json").write_text(json.dumps({"engine": {"checks": checks, "base": "main"}}))

    def tl(self, *args):
        env = dict(os.environ, XDG_CONFIG_HOME=str(Path(self.tmp.name, "cfg")))
        r = subprocess.run([PY, str(TL), "check", *args], cwd=self.repo, env=env, capture_output=True, text=True, check=False)
        return r.returncode, r.stdout

    def test_it_runs_the_gate_steps_and_exits_1_on_a_red_one(self):
        rc, out = self.tl()
        self.assertEqual(rc, 1)
        self.assertRegex(out, r"fmt\s+ok\s+\d+s")
        self.assertRegex(out, r"unit\s+FAILED\s+\d+s")
        self.assertIn("unit saw a failure", out)  # the tail of the red step
        self.assertNotIn("docs", out)  # run stage: not in the gate
        self.assertRegex(out, r"ui\s+skipped \(no change under ui/\*\*\)")

    def test_all_ignores_when(self):
        _rc, out = self.tl("--all")
        self.assertRegex(out, r"ui\s+ok")

    def test_green_gate_exits_0_and_a_second_run_is_cached(self):
        self.profile(CHECKS[:1])
        self.assertEqual(self.tl()[0], 0)
        rc, out = self.tl()
        self.assertEqual(rc, 0)
        self.assertRegex(out, r"fmt\s+cached")

    def test_named_ids_run_only_those_whatever_their_run(self):
        rc, out = self.tl("docs")
        self.assertEqual(rc, 0)
        self.assertRegex(out, r"docs\s+ok")
        self.assertNotIn("fmt", out)
        self.assertEqual(self.tl("nope")[0], 1)

    def test_list_prints_the_registry_and_exits_0(self):
        rc, out = self.tl("--list")
        self.assertEqual(rc, 0)
        lines = out.splitlines()
        self.assertEqual(len(lines), len(CHECKS))
        self.assertTrue(lines[3].startswith("ui  run=gate  group=tests  when=ui/**  "))
        self.assertIn("run=stage", lines[2])

    def test_it_claims_nothing_and_writes_only_the_check_cache(self):
        self.tl()
        written = {p.relative_to(Path(self.tmp.name, "cfg")).parts[1] for p in Path(self.tmp.name, "cfg").rglob("*") if p.is_file()}
        self.assertLessEqual(written, {"check-cache", "locks"})


if __name__ == "__main__":
    unittest.main()
