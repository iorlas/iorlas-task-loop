"""Run-end wire spellings have one home in tlkernel.kinds."""
import ast
from pathlib import Path

from tlkernel.kinds import Kind

ROOT = Path(__file__).resolve().parents[2]


def test_no_kind_strings() -> None:
    values = {
        kind.value for kind in Kind
        if kind.value.startswith(("ask_", "wait_", "pause_", "fault_"))
        or kind in (Kind.ENGINE_CRASH, Kind.OWNER_PARK)
    }
    home = ROOT / "packages/kernel/src/tlkernel/kinds.py"
    roots = (ROOT / "src", *sorted((ROOT / "packages").glob("*/src")))
    found = []
    for top in roots:
        for path in sorted(top.rglob("*.py")):
            if path == home:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in values:
                    found.append(f"{path.relative_to(ROOT)}:{node.lineno}: {node.value!r}")
    assert not found, "\n".join(found)
