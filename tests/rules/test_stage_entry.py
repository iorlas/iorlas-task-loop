"""The loop and hand run-task share the stage execution and lifecycle entry."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def calls(path, name):
    tree = ast.parse((ROOT / path).read_text())
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call)
            and ((isinstance(node.func, ast.Name) and node.func.id == name)
                 or (isinstance(node.func, ast.Attribute) and node.func.attr == name))]


class SharedStageEntry(unittest.TestCase):
    def test_engine_and_run_task_route_through_shared_stage_lifecycle(self):
        engine = "src/taskloop/app/run/engine.py"
        entry = "src/taskloop/app/run/entry.py"
        shared = "src/taskloop/app/run/stages.py"
        self.assertEqual(len(calls(engine, "run_stages")), 1)
        self.assertFalse(calls(engine, "RunOnce"))
        self.assertEqual(len(calls(shared, "stage_run")), 1)
        self.assertEqual(len(calls(shared, "one_stage")), 1)
        self.assertEqual(len(calls(shared, "RunOnce")), 2)
        run = calls(entry, "run")
        self.assertTrue(any(ast.unparse(node.func) == "eng.run" and {k.arg for k in node.keywords} == {"stage", "continuous"}
                            for node in run))
        loop = (ROOT / "src/taskloop/app/launch/loop.py").read_text()
        self.assertIn('"run-task", bead, "--loop"', loop)
