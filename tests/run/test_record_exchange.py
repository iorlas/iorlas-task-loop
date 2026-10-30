"""dev/record_exchange.py turns a run folder into a replayable case folder."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("record_exchange", ROOT / "dev" / "record_exchange.py")
assert spec and spec.loader
rec: Any = importlib.util.module_from_spec(spec)
sys.modules["record_exchange"] = rec
spec.loader.exec_module(rec)


class Record(unittest.TestCase):
    def test_a_run_folder_becomes_a_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, root = Path(tmp, "run"), Path(tmp, "ex")
            run.mkdir()
            (run / "plan.json").write_text('{"summary": "p"}')
            (run / "review-1.json").write_text('{"v": 1}')
            (run / "review-2.json").write_text('{"v": 2}')
            bead = Path(tmp, "bead.json")
            bead.write_text('[{"id": "b-1"}]')
            rec.EXCHANGES = root
            self.assertEqual(rec.main([str(run), "reviewer", "c", "--bead", str(bead)]), 0)
            case = root / "reviewer" / "c"
            self.assertEqual(json.loads((case / "answer.json").read_text()), {"v": 2})  # the last round's answer
            self.assertEqual(json.loads((case / "plan.json").read_text()), {"summary": "p"})
            self.assertEqual(json.loads((case / "bead.json").read_text()), {"id": "b-1"})
            meta = json.loads((case / "meta.json").read_text())
            self.assertEqual((meta["node"], meta["answer"], meta["input"]), ("review", "real", "synthetic"))

    def test_the_sent_prompt_is_kept_with_its_worktree_as_a_placeholder(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, root = Path(tmp, "run"), Path(tmp, "ex")
            run.mkdir()
            (run / "plan-1.json").write_text("{}")
            bead, prompt = Path(tmp, "bead.json"), Path(tmp, "p.txt")
            bead.write_text("{}")
            prompt.write_text("work in /home/u/wt now")
            rec.EXCHANGES = root
            rec.main([str(run), "planner", "c", "--bead", str(bead), "--prompt", str(prompt), "--wt", "/home/u/wt"])
            self.assertEqual((root / "planner" / "c" / "input.txt").read_text(), "work in <WT> now")


if __name__ == "__main__":
    unittest.main()
