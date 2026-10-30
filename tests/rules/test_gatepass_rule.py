"""Only the gate can make a GatePass: under src no module but app/land/gate.py builds one (`GatePass(...)`, `mint`, the seal), so a
push that holds a pass holds the gate's word. pyrefly rejects a build without the seal; this test rejects a build with it."""
import ast
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

SRC = Path(__file__).resolve().parents[2] / "src" / "taskloop"
MAKERS = {"mint", "_Seal"}
HOME = SRC / "app" / "land" / "gate.py"


def named(path: Path, names: set[str]) -> set[str]:
    found = set()
    for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Attribute) and n.attr in names:
            found.add(n.attr)
        elif isinstance(n, ast.Name) and n.id in names:
            found.add(n.id)
        elif isinstance(n, ast.alias) and n.name in names:
            found.add(n.name)
    return found


def called(path: Path, name: str) -> bool:
    return any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == name
               for n in ast.walk(ast.parse(path.read_text(encoding="utf-8"))))


class OnlyTheGateMints(unittest.TestCase):
    def test_no_module_but_the_gate_names_the_makers(self):
        found = {str(f.relative_to(SRC)): named(f, MAKERS) for f in sorted(SRC.rglob("*.py")) if f != HOME and "_vendor" not in f.parts}
        self.assertEqual({k: v for k, v in found.items() if v}, {}, "a GatePass is made by taskloop.app.land.gate only (mint, _Seal)")

    def test_no_module_but_the_gate_builds_a_gatepass(self):
        others = [f for f in sorted(SRC.rglob("*.py")) if f != HOME and "_vendor" not in f.parts]
        built = [str(f.relative_to(SRC)) for f in others if called(f, "GatePass")]
        self.assertEqual(built, [])

    def test_the_gate_does_build_one(self):
        self.assertTrue(called(HOME, "GatePass"))
