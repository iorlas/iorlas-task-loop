"""A real producer receives the full argv and NUL-delimited paths in the judged checkout."""
import hashlib
import json
import sys
from pathlib import Path

from support import engine_case as te
from support.narrow import must

from taskloop.app.checks.cache import is_green, plan_digest
from taskloop.contracts.ids import CheckId
from taskloop.contracts.runkey import BaseSha
from taskloop.domain.checks.specs import gate_items


class RealGatePlan(te.EngineTest):
    def test_script_receives_argv_cwd_and_nul_paths_and_its_skip_is_stored(self):
        script = Path(self.tmp.name, "producer.py")
        self.eng = self.checks_engine(plan_cmd=[sys.executable, str(script), "steps", "--json"], checks=[
            {"id": "coverage", "cmd": "false", "run": "gate"}])
        base = self.eng.git.rev_parse(str(self.eng.wt), self.eng.cfg.base)
        name = "new file.txt"
        (Path(self.eng.wt) / name).write_text("changed\n")
        (Path(self.eng.wt) / ".gitignore").write_text("ignored.log\n")
        te.sh("git", "add", name, ".gitignore", cwd=str(self.eng.wt))
        te.sh("git", "commit", "-qm", "changed path", cwd=str(self.eng.wt))
        (Path(self.eng.wt) / "ignored.log").write_text("ignored files do not block the plan\n")
        body = {"version": 1, "base": base, "empty": False, "full": False, "full_reasons": [], "steps": [
            {"name": "coverage", "lane": "tests", "run": False, "argv": ["false"], "pre": [],
             "recipe": None, "reason": "producer selected no coverage", "future_field": True}]}
        script.write_text(
            "import os, sys\n"
            f"assert sys.argv[1:] == {['steps', '--json', '--base', base, '--paths-stdin']!r}\n"
            f"assert os.getcwd() == {str(self.eng.wt)!r}\n"
            f"assert {name.encode()!r} in sys.stdin.buffer.read().split(b'\\0')\n"
            f"print({json.dumps(body)!r})\n")
        run = self.eng.checker.run_items(gate_items(self.eng.cfg))
        self.assertEqual([(r.status, r.planned, r.why) for r in run],
                         [("skipped", True, "producer selected no coverage")])
        memo = self.eng.checker._memo(run.tree, base)
        self.assertTrue(is_green(self.eng.stores, memo.repo, CheckId("coverage"), run.tree, BaseSha(base),
                                 plan_digest(self.eng.cfg.plan_cmd)))
        docs = self.eng.stores.results(memo.repo, CheckId("coverage"))
        row = must(docs.of(docs.keys()[0]).get())
        self.assertEqual(row.key.plan, plan_digest(self.eng.cfg.plan_cmd))
        self.assertEqual(row.key.plan_output, hashlib.sha1((json.dumps(body) + "\n").encode()).hexdigest())
