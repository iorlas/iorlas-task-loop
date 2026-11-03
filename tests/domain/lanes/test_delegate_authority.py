"""Delegate stop facts survive durable pauses; engine budgets and generated roles retain their authority."""

import json
import sys
import unittest
from itertools import product
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401

from taskloop.contracts.bead import Bead
from taskloop.contracts.ids import BeadId
from taskloop.domain.lanes import pauses, policy, roles

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = json.loads((ROOT / "tests/fixtures/delegate3/skills/delegate/contract.json").read_text(encoding="utf-8"))


class ContractParity(unittest.TestCase):
    def test_every_contract_reason_agrees_with_pause_permanence(self):
        # Local synthetic reasons need rows; contract-owned reasons must not be copied into TABLE.
        self.assertTrue(all(producer == "engine" or reason not in CONTRACT["reasons"] for producer, reason in pauses.TABLE))
        bead = Bead(id=BeadId("t-1"), title="work", status="open")
        for reason, facts in CONTRACT["reasons"].items():
            with self.subTest(reason=reason):
                expected = facts["permanence"]
                if reason in pauses.OVERRIDES:
                    expected, explanation = pauses.OVERRIDES[reason]
                    self.assertTrue(explanation.strip())
                # Any engine row sharing a delegate reason must also disclose divergence.
                for (_, name), row in pauses.TABLE.items():
                    if name == reason:
                        self.assertEqual(row.permanence, expected)
                self.assertEqual(pauses.rule(reason, "delegate", facts["permanence"]).permanence, expected)
                saved = pauses.after_pause(None, bead, "r1", 100, reason, lambda: 0.5,
                                           producer="delegate", permanence=facts["permanence"])
                self.assertEqual(saved.permanence, expected)

    def test_grid_is_derived_from_contract_facts_and_schema_enums(self):
        stop = CONTRACT["answer_schema"]["properties"]["stop"]["properties"]
        scopes = stop["scope"]["enum"]
        permanences = stop["permanence"]["enum"]
        retries = stop["retry"]["properties"]["kind"]["enum"]
        self.assertEqual(set(policy.SCOPES), set(scopes))
        self.assertEqual(set(policy.PERMANENCES), set(permanences))
        self.assertEqual(set(policy.RETRY_KINDS), set(retries))
        # The schema lists the vocabulary; reason facts supply the permanence/retry relation.
        combinations = {(row["permanence"], row["retry"]) for row in CONTRACT["reasons"].values()}
        expected = {(scope, permanence, retry) for scope, (permanence, retry) in product(scopes, combinations)}
        self.assertEqual(set(policy.TABLE), expected)
        self.assertEqual(set(policy.LEGAL), expected)
        self.assertTrue(all((row["scope"], row["permanence"], row["retry"]) in expected
                            for row in CONTRACT["reasons"].values()))

    def test_generated_roles_match_the_skill_node_table(self):
        skill = (ROOT / "skills/task-loop/SKILL.md").read_text(encoding="utf-8")
        table = skill.split("| node | delegate role |\n|---|---|\n", 1)[1].split("\n\n", 1)[0]
        cells = [row.strip("|").split("|") for row in table.splitlines()]
        expected = {node.strip(): role.strip() for node, role in cells}
        self.assertEqual(roles.ROLES, expected)
        self.assertEqual(roles.READ_ONLY_NODES, tuple(node for node, role in expected.items() if role == "reviewer"))


class DelegatePauses(unittest.TestCase):
    def setUp(self):
        self.bead = Bead(id=BeadId("t-1"), title="work", status="open")

    def test_unknown_transient_uses_default_backoff_and_exhausts_at_three(self):
        rec = None
        for n, wait in enumerate((60, 120, 240, 0)):
            rec = pauses.after_pause(rec, self.bead, f"r{n}", 100, "future_delegate_reason", lambda: 0.5,
                                     producer="delegate", permanence="transient")
            self.assertEqual((rec.permanence, rec.retry_at), ("transient", 100 + wait) if wait else ("needs_owner", 0))
            self.assertEqual(rec.attempts, {"delegate:future_delegate_reason": n + 1})
        rule = pauses.rule("future_delegate_reason", "delegate", "transient")
        self.assertEqual((rule.base_s, rule.cap_s, rule.max_attempts), (60, 3600, 3))
        self.assertEqual(pauses.delay(rule, 1000, lambda: 0.5), 3600)

    def test_stop_permanence_wins_except_for_documented_engine_overrides(self):
        for reason in ("future_delegate_reason", "busy", "engine_crash"):
            with self.subTest(reason=reason):
                rec = pauses.after_pause(None, self.bead, "r1", 100, reason, lambda: 0.5,
                                         producer="delegate", permanence="needs_owner", not_before=900)
                self.assertEqual((rec.permanence, rec.retry_at), ("needs_owner", 0))
        # Released no_lane/crash owner wakes override even a transient delegate hint.
        for reason in ("no_lane", "crash"):
            with self.subTest(reason=reason):
                self.assertIn(reason, pauses.OVERRIDES)
                self.assertEqual(pauses.rule(reason, "delegate", "transient"), pauses.PauseRule("needs_owner"))
        self.assertEqual(pauses.rule("stage_refused", "engine", "transient").permanence, "needs_owner")

    def test_all_delegate_backoff_budgets_and_network_exemption_are_kept(self):
        for reason, backoff in pauses.BACKOFF.items():
            with self.subTest(reason=reason):
                rec = None
                for n in range(5):
                    rec = pauses.after_pause(rec, self.bead, f"r{n}", 100, reason, lambda: 0.5,
                                             producer="delegate", permanence="transient")
                    transient = not backoff.max_attempts or n < backoff.max_attempts
                    self.assertEqual(rec.permanence, "transient" if transient else "needs_owner")
                    attempt = 0 if reason == "network" else n
                    wait = min(backoff.base_s * 2 ** attempt, backoff.cap_s)
                    self.assertEqual(rec.retry_at, 100 + wait if transient else 0)
                assert rec is not None
                self.assertEqual(rec.attempts, {} if reason == "network" else {f"delegate:{reason}": 5})

    def test_released_backoff_values_and_machine_fixes_are_unchanged(self):
        standard = ("only_family_unready", "timeout", "rate_limited", "hung", "worker_failed", "schema_invalid", "held", "killed")
        quick = ("busy", "vendor_blip", "duplicate_task", "lock")
        expected = dict.fromkeys(standard, pauses.Backoff(60, 3600, 3))
        expected.update(dict.fromkeys(quick, pauses.Backoff(30, 1800, 3)))
        expected["network"] = pauses.Backoff(30, 1800, 0)
        self.assertEqual(pauses.BACKOFF, expected)
        self.assertEqual(pauses.MACHINE_FIXED, {
            "no_lane", "logged_out", "credit_exhausted", "secrets", "setup", "contract_violation", "engine_only_unenforced",
        })
