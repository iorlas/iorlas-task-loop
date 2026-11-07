"""Every declared schema part is included in the application composition."""
import ast
from pathlib import Path

from taskloop.app.parts import STAGE_PARTS
from taskloop_dash.parts import DASH_PARTS


def test_stage_parts_include_every_part():
    src = Path(__file__).resolve().parents[2] / "src"
    names = set()
    for package in ("taskloop", "taskloop_dash"):
        for path in (src / package).rglob("*.py"):
            if path.name == "dbparts.py":
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Part":
                    name = next(kw.value for kw in node.keywords if kw.arg == "name")
                    assert isinstance(name, ast.Constant) and isinstance(name.value, str), path
                    names.add(name.value)
    assert names == {part.name for part in STAGE_PARTS}
    assert set(DASH_PARTS) <= set(STAGE_PARTS)
