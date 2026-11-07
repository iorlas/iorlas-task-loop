"""Stage path names belong to their owning modules, never the kernel path API."""
import ast
from pathlib import Path

STAGE_MODULES = {
    "land": "taskloop.app.land.paths",
    "slot": "tlslots.paths",
    "ask": "taskloop.app.asks.paths",
    "release": "tlrelease.paths",
    "suite": "taskloop.app.prune.paths",
    "dash": "tldash.paths",
    "layout": "taskloop.adapters.layout_paths",
    "retired": "taskloop.adapters.layout_paths",
    "check_dirs": "tlartifacts.paths",
    "engine_take": "tlslots.paths",
    "engine_lock": "tlslots.paths",
}


def test_kernel_paths_have_no_stage_names():
    source = Path(__file__).resolve().parents[2] / "packages/kernel/src/tlkernel/paths.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    problems = [
        f"{node.name}: use {module} instead of tlkernel.paths"
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        for stem, module in STAGE_MODULES.items()
        if stem in node.name.lower()
    ]
    assert not problems, "\n".join(problems)
