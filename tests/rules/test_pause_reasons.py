"""Every pause has engine policy, a documented override, or delegate contract permanence."""

import ast
import json
import sys
from collections import Counter
from collections.abc import Mapping
from pathlib import Path

from support.case import Case

from rules.gate_rules import parsed

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from taskloop.domain.lanes.pause_reasons import Reason
from taskloop.domain.lanes.pauses import OVERRIDES, TABLE, rule
from tlkernel.delegate import Permanence

ROOT = Path(__file__).resolve().parents[2]


def contract_permanences() -> dict[str, Permanence]:
    contract = ROOT / "src/delegate/data/contract.json"
    policies: dict[str, Permanence] = {}
    for reason, facts in json.loads(contract.read_text())["reasons"].items():
        permanence = facts["permanence"]
        if permanence == "transient":
            policies[reason] = "transient"
        elif permanence == "needs_owner":
            policies[reason] = "needs_owner"
        else:
            raise ValueError(f"{reason}: invalid contract permanence {permanence!r}")
    return policies


def missing_policies(reasons: set[str], contract: Mapping[str, Permanence]) -> set[str]:
    overrides = {reason for reason, override in OVERRIDES.items() if override is not None}
    return reasons - ({reason for _, reason in TABLE} | overrides | set(contract))


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
    return produced_in(ast.parse(source))


def produced_in(tree: ast.Module) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        found.update(declaration(node) | synthesized(node))
    return found


class Complete(Case):
    def test_all_locally_produced_reason_ids_have_a_policy(self):
        reasons: set[str] = set()
        for path in (ROOT / "src").rglob("*.py"):
            reasons.update(produced_in(parsed(path)[1]))
        assert missing_policies(reasons, contract_permanences()) == set()

    def test_all_recorded_delegate_contract_reasons_have_a_policy(self):
        for reason, permanence in contract_permanences().items():
            with self.subTest(reason=reason):
                override = OVERRIDES.get(reason)
                expected = override[0] if override is not None else permanence
                assert rule(reason, "delegate", permanence).permanence == expected

    def test_a_reason_without_any_policy_is_rejected_by_coverage(self):
        assert missing_policies({"new_unclassified_reason"}, contract_permanences()) == {"new_unclassified_reason"}

    def test_overrides_have_explanations_and_do_not_duplicate_table_rows(self):
        for reason, override in OVERRIDES.items():
            if override is None:
                continue
            _, explanation = override
            with self.subTest(reason=reason):
                assert explanation.strip()
                assert ("delegate", reason) not in TABLE

    def test_every_reason_has_exactly_one_policy(self):
        contract = contract_permanences()
        assert missing_policies(set(Reason), contract) == set()
        # Overrides deliberately replace contract permanence; table rows are separate policies.
        counts = Counter(reason for _, reason in TABLE)
        counts.update({reason for reason, override in OVERRIDES.items() if override is not None} | set(contract))
        assert counts == Counter(Reason)

    def test_table_has_no_duplicate_source_keys(self):
        source = ast.parse((ROOT / "src/taskloop/domain/lanes/pauses.py").read_text())
        table = next(n.value for n in source.body if isinstance(n, ast.AnnAssign)
                     and isinstance(n.target, ast.Name) and n.target.id == "TABLE")
        assert isinstance(table, ast.Dict)
        keys = [ast.dump(key) for key in table.keys if key is not None]
        assert len(keys) == len(set(keys))

    def test_every_transient_pause_policy_is_capped_except_network(self):
        policies = dict(TABLE)
        for reason, permanence in contract_permanences().items():
            policies[("delegate", reason)] = rule(reason, "delegate", permanence)
        for key, policy in policies.items():
            with self.subTest(key=key):
                if policy.permanence == "transient":
                    uncapped = key in (("delegate", Reason.NETWORK), ("engine", Reason.PAUSE_NETWORK),
                                       ("engine", Reason.FAULT_INFRA), ("engine", Reason.FAULT_CRASHED),
                                       ("engine", Reason.FAULT_STALE_BASE))
                    if uncapped:
                        assert policy.max_attempts == 0
                    else:
                        assert policy.max_attempts > 0

    def test_scanner_catches_new_constants_enums_and_synthesized_reasons(self):
        source = (
            'REASON_NEW: Final = "new"\nclass End(Enum):\n PAUSE_NEW = "pause_new"\n'
            'FAULT_NEW = "fault_new"\nsynth_for(c, "new_stop", facts)\ne.pause_reason = "own"\nStopFacts(reason="wire")'
        )
        assert produced(source) == {"new", "pause_new", "fault_new", "new_stop", "own", "wire"}


def documented() -> dict[str, tuple[str, ...]]:
    rows: dict[str, tuple[str, ...]] = {}
    for line in (ROOT / "docs/dev/pause-reasons.md").read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and len(cells) == 6 and cells[0] not in ("reason", "---"):
            rows[cells[0]] = tuple(cells[1:])
    return rows


class Documented(Case):
    def test_the_doc_table_holds_every_reason_with_the_class_the_code_gives_it(self):
        contract = contract_permanences()
        expected: dict[str, tuple[str, ...]] = {}
        for reason in Reason:
            producer = "engine" if ("engine", reason) in TABLE else "delegate"
            policy = rule(reason.value, producer, contract.get(reason.value))
            transient = policy.permanence == "transient"
            expected[reason.value] = (producer, policy.permanence, f"{policy.base_s:g}" if transient else "-",
                                      f"{policy.cap_s:g}" if transient else "-", str(policy.max_attempts) if transient else "-")
        assert documented() == expected
