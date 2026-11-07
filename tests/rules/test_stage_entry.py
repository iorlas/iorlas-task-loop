"""The loop and hand run-task share the stage execution and lifecycle entry."""
import ast
from pathlib import Path

from tltestkit.case import Case

ROOT = Path(__file__).resolve().parents[2]


def calls(path, name):
    tree = ast.parse((ROOT / path).read_text())
    return [node for node in ast.walk(tree) if isinstance(node, ast.Call)
            and ((isinstance(node.func, ast.Name) and node.func.id == name)
                 or (isinstance(node.func, ast.Attribute) and node.func.attr == name))]


class SharedStageEntry(Case):
    def test_engine_and_run_task_route_through_shared_stage_lifecycle(self):
        engine = "src/taskloop/app/run/engine.py"
        entry = "src/taskloop/app/run/entry.py"
        binder = "src/taskloop/app/run/stages.py"
        shared = "packages/pipeline/src/tlpipeline/standalone.py"
        assert len(calls(engine, "run_stages")) == 1
        assert not calls(engine, "RunOnce")
        assert len(calls(shared, "stage_run")) == 1
        assert len(calls(shared, "one_stage")) == 1
        assert len(calls(binder, "RunOnce")) == 1
        assert len(calls(binder, "Standalone")) == 1
        assert len(calls(binder, "run_stages")) == 1
        run = calls(entry, "run")
        assert any(ast.unparse(node.func) == "eng.run" and {k.arg for k in node.keywords} == {"stage", "continuous"}
                            for node in run)
        loop = (ROOT / "src/taskloop/app/launch/loop.py").read_text()
        assert '"run-task", bead, "--loop"' in loop
