"""`tl check`: the repo's registry of checks run by a person, in a real worktree, through the engine's own runner."""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from support import procsim
from support.tlmain import tl_main

CHECKS = [
    {"id": "fmt", "argv": [procsim.default("fmt-fine", procsim.exits(0, "fmt fine"))], "group": "static", "run": "gate"},
    {"id": "unit", "argv": [procsim.default("unit-red", procsim.exits(1, "unit saw a failure"))], "run": "gate"},
    {"id": "docs", "argv": [procsim.default("docs-out", procsim.exits(0, "docs"))], "run": "stage"},
    {"id": "ui", "argv": [procsim.default("ui-out", procsim.exits(0, "ui"))], "run": "gate", "when": ["ui/**"]},
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
        r = tl_main("check", *args, cwd=self.repo, env={"XDG_CONFIG_HOME": str(Path(self.tmp.name, "cfg"))})
        for line in r.stdout.splitlines():
            if line.startswith("evidence kept in "):
                self.addCleanup(shutil.rmtree, line.removeprefix("evidence kept in "), True)
        return r.returncode, r.stdout

    def test_it_runs_the_gate_steps_and_exits_1_on_a_red_one(self):
        rc, out = self.tl()
        self.assertEqual(rc, 1)
        self.assertRegex(out, r"fmt\s+ok\s+\d+s")
        self.assertRegex(out, r"unit\s+FAILED\s+\d+s")
        self.assertIn("unit saw a failure", out)  # the tail of the red step
        self.assertNotIn("docs", out)  # run stage: not in the gate
        self.assertRegex(out, r"ui\s+skipped \(no change under ui/\*\*\)")

    def test_a_red_run_keeps_its_evidence_and_prints_the_path_a_green_run_removes_it(self):
        _rc, out = self.tl()
        line = next(x for x in out.splitlines() if x.startswith("evidence kept in "))
        kept = Path(line.removeprefix("evidence kept in "))
        self.assertTrue(kept.is_dir())
        self.profile(CHECKS[:1])
        rc, out = self.tl()
        self.assertEqual(rc, 0)
        self.assertNotIn("evidence kept", out)

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

    def test_it_prints_a_diff_check_line_first_and_a_red_one_names_the_file_and_line(self):
        self.profile(CHECKS[:1])
        rc, out = self.tl()
        self.assertEqual(rc, 0)
        self.assertRegex(out.splitlines()[0], r"diff-check\s+ok\s+\d+s")
        (self.repo / "new.txt").write_text("fine\nbad  \n")  # untracked, new: the diff check reads the tree, not the index
        rc, out = self.tl()
        self.assertEqual(rc, 1)
        self.assertRegex(out, r"diff-check\s+FAILED")
        self.assertIn("new.txt:2: trailing whitespace.", out)
        self.assertRegex(out, r"fmt\s+ok")  # the cheap group's other checks still ran

    def test_list_prints_the_registry_and_exits_0(self):
        rc, out = self.tl("--list")
        self.assertEqual(rc, 0)
        lines = out.splitlines()
        self.assertEqual(len(lines), len(CHECKS))
        self.assertTrue(lines[3].startswith("ui  run=gate  group=tests  when=ui/**  "))
        self.assertIn("run=stage", lines[2])

    def test_it_claims_nothing_and_writes_only_the_result_store(self):
        self.tl()
        written = {p.relative_to(Path(self.tmp.name, "cfg")).parts[1] for p in Path(self.tmp.name, "cfg").rglob("*") if p.is_file()}
        self.assertLessEqual(written, {"results", "locks"})


if __name__ == "__main__":
    unittest.main()
