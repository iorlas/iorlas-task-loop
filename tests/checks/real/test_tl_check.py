"""`tl check`: the repo's registry of checks run by a person, in a real worktree, through the engine's own runner."""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from support import procsim
from support.case import Case
from support.checked import run_checked
from support.tlmain import tl_main
from support.tmpdir import TemporaryDirectory

CHECKS = [
    {"id": "fmt", "argv": [procsim.default("fmt-fine", procsim.exits(0, "fmt fine"))], "group": "static", "run": "gate"},
    {"id": "unit", "argv": [procsim.default("unit-red", procsim.exits(1, "unit saw a failure"))], "run": "gate"},
    {"id": "docs", "argv": [procsim.default("docs-out", procsim.exits(0, "docs"))], "run": "stage"},
    {"id": "ui", "argv": [procsim.default("ui-out", procsim.exits(0, "ui"))], "run": "gate", "when": ["ui/**"]},
]


class TlCheck(Case):
    def test_clean_repo_check_records_the_repo_plans_skip_for_green(self):
        producer = Path(self.tmp.name, "plan.py")
        body = {"version": 1, "base": None, "empty": True, "full": False, "full_reasons": [], "steps": [
            {"name": "selected", "lane": "tests", "run": False, "argv": ["false"], "pre": [],
             "recipe": None, "reason": "no relevant paths"}]}
        producer.write_text(f"print({json.dumps(body)!r})\n")
        profile = {"engine": {"base": "main", "plan_cmd": [sys.executable, str(producer), "steps", "--json"],
                               "checks": [{"id": "selected", "argv": ["false"], "run": "gate"}]}}
        (self.repo / ".task-loop.json").write_text(json.dumps(profile))
        self.git("add", "-A")
        self.git("commit", "-qm", "repo plan")
        rc, out = self.tl("--repo", str(self.repo))
        assert rc == 0, out
        assert "skipped (no relevant paths)" in out
        base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()
        tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=self.repo, text=True).strip()
        green = tl_main("green", "selected", "--repo", str(self.repo), "--tree", tree, "--base", base,
                        cwd=self.repo, env={"XDG_CONFIG_HOME": str(Path(self.tmp.name, "cfg"))})
        assert green.returncode == 0, green.stdout
        assert "skipped-by-plan: no relevant paths" in green.stdout

    def setup_method(self):
        self.tmp = TemporaryDirectory()
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
        run_checked(["git", *a], self.repo)

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
        assert rc == 1
        assert re.search(r"fmt\s+ok\s+\d+s", out)
        assert re.search(r"unit\s+FAILED\s+\d+s", out)
        assert "unit saw a failure" in out  # the tail of the red step
        assert "docs" not in out  # run stage: not in the gate
        assert re.search(r"ui\s+skipped \(no change under ui/\*\*\)", out)

    def test_a_red_run_keeps_its_evidence_and_prints_the_path(self):
        _rc, out = self.tl()
        line = next(x for x in out.splitlines() if x.startswith("evidence kept in "))
        kept = Path(line.removeprefix("evidence kept in "))
        assert kept.is_dir()
        self.profile(CHECKS[:1])
        rc, out = self.tl()
        assert rc == 0
        assert "evidence kept" not in out

    def test_all_ignores_when(self):
        _rc, out = self.tl("--all")
        assert re.search(r"ui\s+ok", out)

    def test_green_gate_exits_0_and_a_second_run_is_cached(self):
        self.profile(CHECKS[:1])
        assert self.tl()[0] == 0
        rc, out = self.tl()
        assert rc == 0
        assert re.search(r"fmt\s+cached", out)

    def test_named_ids_run_only_those_whatever_their_run(self):
        rc, out = self.tl("docs")
        assert rc == 0
        assert re.search(r"docs\s+ok", out)
        assert "fmt" not in out
        assert self.tl("nope")[0] == 1

    def test_it_prints_a_diff_check_line_first_and_a_red_one_names_the_file_and_line(self):
        self.profile(CHECKS[:1])
        rc, out = self.tl()
        assert rc == 0
        assert re.search(r"diff-check\s+ok\s+\d+s", out.splitlines()[0])
        (self.repo / "new.txt").write_text("fine\nbad  \n")  # untracked, new: the diff check reads the tree, not the index
        rc, out = self.tl()
        assert rc == 1
        assert re.search(r"diff-check\s+FAILED", out)
        assert "new.txt:2: trailing whitespace." in out
        assert re.search(r"fmt\s+ok", out)  # the cheap group's other checks still ran

    def test_list_prints_the_registry_and_exits_0(self):
        rc, out = self.tl("--list")
        assert rc == 0
        lines = out.splitlines()
        assert len(lines) == len(CHECKS)
        assert lines[3].startswith("ui  run=gate  group=tests  when=ui/**  ")
        assert "run=stage" in lines[2]

    def test_it_claims_nothing_and_writes_results_and_run_evidence(self):
        self.tl()
        written = {p.relative_to(Path(self.tmp.name, "cfg")).parts[1] for p in Path(self.tmp.name, "cfg").rglob("*") if p.is_file()}
        assert written <= {"results", "locks", "runs", "factory.db", "factory.db-wal", "factory.db-shm"}
        assert {"runs"} <= written
