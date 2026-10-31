"""A real producer receives the full argv and NUL-delimited paths in the judged checkout."""
import json
import sys
from pathlib import Path

from support import engine_case as te

from taskloop.app.checks.cache import repo_green
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
        self.assertTrue(repo_green(self.eng.stores, self.eng.git, str(self.eng.wt), CheckId("coverage"),
                                   run.tree, BaseSha(base)))
