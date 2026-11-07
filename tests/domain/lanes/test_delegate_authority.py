"""Delegate stop facts survive durable pauses; engine budgets and generated roles retain their authority."""

import json
import sys
from itertools import product
from pathlib import Path

from tltestkit.case import Case

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401

from taskloop.domain.lanes import pauses, policy, roles
from tlkernel.bead import Bead
from tlkernel.ids import BeadId

ROOT = Path(__file__).resolve().parents[3]
CONTRACT = json.loads((ROOT / "src/delegate/data/contract.json").read_text(encoding="utf-8"))


class ContractParity(Case):
    def test_every_contract_reason_agrees_with_pause_permanence(self):
        # Local synthetic reasons need rows; contract-owned reasons must not be copied into TABLE.
        assert all(producer == "engine" or reason not in CONTRACT["reasons"] for producer, reason in pauses.TABLE)
        bead = Bead(id=BeadId("t-1"), title="work", status="open")
        for reason, facts in CONTRACT["reasons"].items():
            with self.subTest(reason=reason):
                expected = facts["permanence"]
                override = pauses.OVERRIDES.get(reason)
                if override is not None:
                    expected, explanation = override
                    assert explanation.strip()
                # Any engine row sharing a delegate reason must also disclose divergence.
                for (_, name), row in pauses.TABLE.items():
                    if name == reason:
                        assert row.permanence == expected
                assert pauses.rule(reason, "delegate", facts["permanence"]).permanence == expected
                saved = pauses.after_pause(None, bead, "r1", 100, reason, lambda: 0.5,
                                           producer="delegate", permanence=facts["permanence"])
                assert saved.permanence == expected

    def test_grid_is_derived_from_contract_facts_and_schema_enums(self):
        stop = CONTRACT["answer_schema"]["properties"]["stop"]["properties"]
        scopes = stop["scope"]["enum"]
        permanences = stop["permanence"]["enum"]
        retries = stop["retry"]["properties"]["kind"]["enum"]
        assert set(policy.SCOPES) == set(scopes)
        assert set(policy.PERMANENCES) == set(permanences)
        assert set(policy.RETRY_KINDS) == set(retries)
        # The schema lists the vocabulary; reason facts supply the permanence/retry relation.
        combinations = {(row["permanence"], row["retry"]) for row in CONTRACT["reasons"].values()}
        expected = {(scope, permanence, retry) for scope, (permanence, retry) in product(scopes, combinations)}
        assert set(policy.TABLE) == expected
        assert set(policy.LEGAL) == expected
        assert all((row["scope"], row["permanence"], row["retry"]) in expected
                            for row in CONTRACT["reasons"].values())

    def test_generated_roles_match_the_skill_node_table(self):
        skill = (ROOT / "skills/task-loop/SKILL.md").read_text(encoding="utf-8")
        table = skill.split("| node | delegate role |\n|---|---|\n", 1)[1].split("\n\n", 1)[0]
        cells = [row.strip("|").split("|") for row in table.splitlines()]
        expected = {node.strip(): role.strip() for node, role in cells}
        assert expected == roles.ROLES
        assert tuple(node for node, role in expected.items() if role == "reviewer") == roles.READ_ONLY_NODES


class DelegatePauses(Case):
    def setup_method(self):
        self.bead = Bead(id=BeadId("t-1"), title="work", status="open")

    def test_unknown_transient_uses_default_backoff_and_exhausts_at_three(self):
        rec = None
        for n, wait in enumerate((60, 120, 240, 0)):
            rec = pauses.after_pause(rec, self.bead, f"r{n}", 100, "future_delegate_reason", lambda: 0.5,
                                     producer="delegate", permanence="transient")
            assert (rec.permanence, rec.retry_at) == (("transient", 100 + wait) if wait else ("needs_owner", 0))
            assert rec.attempts == {"delegate:future_delegate_reason": n + 1}
        rule = pauses.rule("future_delegate_reason", "delegate", "transient")
        assert (rule.base_s, rule.cap_s, rule.max_attempts) == (60, 3600, 3)
        assert pauses.delay(rule, 1000, lambda: 0.5) == 3600

    def test_stop_permanence_wins_except_for_documented_engine_overrides(self):
        for reason in ("future_delegate_reason", "busy", "engine_crash"):
            with self.subTest(reason=reason):
                rec = pauses.after_pause(None, self.bead, "r1", 100, reason, lambda: 0.5,
                                         producer="delegate", permanence="needs_owner", not_before=900)
                assert (rec.permanence, rec.retry_at) == ("needs_owner", 0)
        # Released no_lane/crash owner wakes override even a transient delegate hint.
        for reason in ("no_lane", "crash"):
            with self.subTest(reason=reason):
                assert reason in pauses.OVERRIDES
                assert pauses.rule(reason, "delegate", "transient") == pauses.PauseRule("needs_owner")
        assert pauses.rule("stage_refused", "engine", "transient").permanence == "needs_owner"

    def test_all_delegate_backoff_budgets_and_network_exemption_are_kept(self):
        for reason, backoff in pauses.BACKOFF.items():
            if backoff is None:
                continue
            with self.subTest(reason=reason):
                rec = None
                for n in range(5):
                    rec = pauses.after_pause(rec, self.bead, f"r{n}", 100, reason, lambda: 0.5,
                                             producer="delegate", permanence="transient")
                    transient = not backoff.max_attempts or n < backoff.max_attempts
                    assert rec.permanence == ("transient" if transient else "needs_owner")
                    attempt = 0 if reason == "network" else n
                    wait = min(backoff.base_s * 2 ** attempt, backoff.cap_s)
                    assert rec.retry_at == (100 + wait if transient else 0)
                assert rec is not None
                assert rec.attempts == ({} if reason == "network" else {f"delegate:{reason}": 5})

    def test_released_backoff_values_and_machine_fixes_are_unchanged(self):
        standard = ("only_family_unready", "timeout", "rate_limited", "hung", "worker_failed", "schema_invalid", "held", "killed")
        quick = ("busy", "vendor_blip", "duplicate_task", "lock")
        expected = dict.fromkeys(standard, pauses.Backoff(60, 3600, 3))
        expected.update(dict.fromkeys(quick, pauses.Backoff(30, 1800, 3)))
        expected["network"] = pauses.Backoff(30, 1800, 0)
        assert {reason: backoff for reason, backoff in pauses.BACKOFF.items() if backoff is not None} == expected
        assert {
            "no_lane", "logged_out", "credit_exhausted", "secrets", "setup", "contract_violation", "engine_only_unenforced",
        } == pauses.MACHINE_FIXED
