"""Every engine pause/fault enum and locally produced delegate stop has an explicit durable wake policy."""

import ast
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.domain.lanes.pauses import TABLE

ROOT = Path(__file__).resolve().parents[2]


def declaration(node: ast.AST) -> set[str]:
    if isinstance(node, ast.AnnAssign):
        targets, value = [node.target], node.value
    elif isinstance(node, ast.Assign):
        targets, value = node.targets, node.value
    else:
        return set()
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str) or not value.value:
        return set()
    names = [t.id if isinstance(t, ast.Name) else t.attr for t in targets if isinstance(t, (ast.Name, ast.Attribute))]
    return {
        value.value
        for name in names
        if name.startswith(("REASON_", "FAULT_", "PAUSE_", "ASK_")) or name in ("WAIT_ASK", "OWNER_PARK", "pause_reason")
    }


def synthesized(node: ast.AST) -> set[str]:
    if not isinstance(node, ast.Call):
        return set()
    name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
    if name in ("StopFacts", "Stop"):
        return {
            k.value.value
            for k in node.keywords
            if k.arg == "reason" and isinstance(k.value, ast.Constant) and isinstance(k.value.value, str)
        }
    index = 1 if name == "synth_for" else 0
    if name not in ("synth", "synth_for") or len(node.args) <= index:
        return set()
    reason = node.args[index]
    return {reason.value} if isinstance(reason, ast.Constant) and isinstance(reason.value, str) else set()


def produced(source: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        found.update(declaration(node) | synthesized(node))
    return found


class Complete(unittest.TestCase):
    def test_all_locally_produced_reason_ids_have_a_policy(self):
        reasons: set[str] = set()
        for path in (ROOT / "src").rglob("*.py"):
            reasons.update(produced(path.read_text(encoding="utf-8")))
        self.assertEqual(reasons - TABLE.keys(), set())

    def test_all_recorded_delegate_contract_reasons_have_a_policy(self):
        contract = ROOT / "tests/fixtures/delegate3/skills/delegate/contract.json"
        self.assertEqual(set(json.loads(contract.read_text())["reasons"]) - TABLE.keys(), set())

    def test_scanner_catches_new_constants_enums_and_synthesized_reasons(self):
        source = (
            'REASON_NEW: Final = "new"\nclass End(Enum):\n PAUSE_NEW = "pause_new"\n'
            'FAULT_NEW = "fault_new"\nsynth_for(c, "new_stop", facts)\ne.pause_reason = "own"\nStopFacts(reason="wire")'
        )
        self.assertEqual(produced(source), {"new", "pause_new", "fault_new", "new_stop", "own", "wire"})
