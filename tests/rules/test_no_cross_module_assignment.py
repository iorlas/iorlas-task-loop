"""Imported names cannot be used to assign another module's attributes."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def violations(source: str) -> list[int]:
    tree = ast.parse(source)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.asname or alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.update(alias.asname or alias.name for alias in node.names)
    found = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for attr in ast.walk(target):
                    if isinstance(attr, ast.Attribute) and isinstance(attr.ctx, ast.Store) and isinstance(attr.value, ast.Name) \
                            and attr.value.id in imported:
                        found.append(attr.lineno)
    return found


def test_no_cross_module_assignment():
    found = []
    for path in sorted((ROOT / "src/taskloop").rglob("*.py")):
        found += [f"{path.relative_to(ROOT)}:{line}" for line in violations(path.read_text(encoding="utf-8"))]
    assert found == []


def test_rule_sees_assignments_and_import_aliases():
    for assignment in ('mod.X = 1', 'mod.X += 1', 'mod.X: int = 1', '(mod.X, local) = pair'):
        assert violations('import other as mod\n' + assignment) == [2]
    assert violations('from pkg import mod\nmod.X = 1') == [2]
    assert violations('import pkg.mod\npkg.X = 1') == [2]
    assert violations('import mod\nlocal.X = mod.X') == []
    assert violations('import mod\nx = mod.X') == []
