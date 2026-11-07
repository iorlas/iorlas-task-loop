"""Every pipeline Protocol stays narrow; existing exceptions only shrink."""
import ast
from pathlib import Path

import pytest

OVER = {"checkpoints.CheckpointHost": 18}
PACKAGE = Path(__file__).resolve().parents[1] / "src" / "tlpipeline"


def protocol_counts():
    counts = {}
    for path in sorted(PACKAGE.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.ClassDef):
                continue
            if not any(
                (isinstance(base, ast.Name) and base.id == "Protocol")
                or (isinstance(base, ast.Attribute) and base.attr == "Protocol")
                for base in node.bases
            ):
                continue
            counts[f"{path.stem}.{node.name}"] = sum(
                isinstance(member, (ast.FunctionDef, ast.AnnAssign))
                for member in node.body
            )
    return counts


def test_every_protocol_obeys_the_role_ceiling():
    counts = protocol_counts()
    assert counts, "no pipeline Protocols found"
    problems = []
    for name, ceiling in OVER.items():
        count = counts.get(name)
        if count is None or count <= 16:
            problems.append(f"{name}: gone or at most 16; delete the line from OVER")
        elif count < ceiling:
            problems.append(f"{name}: now {count}; lower it in OVER from {ceiling}")
        elif count > ceiling:
            problems.append(f"{name}: grew to {count} above OVER ceiling {ceiling}")
    for name, count in counts.items():
        if count > 16 and name not in OVER:
            problems.append(f"{name}: {count} own members exceeds 16")
    if problems:
        pytest.fail("\n".join(problems))
