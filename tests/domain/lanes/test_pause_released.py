"""Freeze every 0.23.315 PERMCAP rule from HEAD b7acd1cfe186bb2f917cbf96e343a997822209f0."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import support.paths  # noqa: F401

from taskloop.contracts.bead import Bead
from taskloop.contracts.delegate import Permanence
from taskloop.contracts.ids import BeadId
from taskloop.domain.lanes import pauses
from taskloop.domain.lanes.pause_reasons import Producer
from taskloop.domain.lanes.pauses import PauseRule

# Literal snapshot of the old TABLE, independent of current enums, backoffs and overrides.
RELEASED: dict[tuple[Producer, str], PauseRule] = {
    ("delegate", "no_lane"): PauseRule("needs_owner"),
    ("delegate", "only_family_unready"): PauseRule("transient", 60, 3600, 3),
    ("engine", "same_family"): PauseRule("transient", 60, 3600, 3),
    ("delegate", "busy"): PauseRule("transient", 30, 1800, 3),
    ("delegate", "timeout"): PauseRule("transient", 60, 3600, 3),
    ("delegate", "network"): PauseRule("transient", 30, 1800),
    ("engine", "engine_crash"): PauseRule("transient", 60, 3600, 3),
    ("engine", "stage_refused"): PauseRule("needs_owner"),
    ("engine", "transient_infrastructure"): PauseRule("transient", 60, 3600, 3),
    ("delegate", "rate_limited"): PauseRule("transient", 60, 3600, 3),
    ("delegate", "hung"): PauseRule("transient", 60, 3600, 3),
    ("delegate", "vendor_blip"): PauseRule("transient", 30, 1800, 3),
    ("delegate", "worker_failed"): PauseRule("transient", 60, 3600, 3),
    ("delegate", "schema_invalid"): PauseRule("transient", 60, 3600, 3),
    ("delegate", "held"): PauseRule("transient", 60, 3600, 3),
    ("delegate", "duplicate_task"): PauseRule("transient", 30, 1800, 3),
    ("delegate", "lock"): PauseRule("transient", 30, 1800, 3),
    ("delegate", "crash"): PauseRule("needs_owner"),
    ("engine", "no_answer"): PauseRule("transient", 60, 3600, 3),
    ("delegate", "killed"): PauseRule("transient", 60, 3600, 3),
    ("delegate", "engine_only_unenforced"): PauseRule("needs_owner"),
    ("engine", "overrun"): PauseRule("needs_owner"),
    ("delegate", "secrets"): PauseRule("needs_owner"),
    ("delegate", "credit_exhausted"): PauseRule("needs_owner"),
    ("delegate", "logged_out"): PauseRule("needs_owner"),
    ("delegate", "bad_request"): PauseRule("needs_owner"),
    ("delegate", "caller"): PauseRule("needs_owner"),
    ("delegate", "setup"): PauseRule("needs_owner"),
    ("engine", "profile_ahead"): PauseRule("needs_owner"),
    ("engine", "contract_violation"): PauseRule("needs_owner"),
    ("engine", "pause_lane"): PauseRule("transient", 60, 3600, 3),
    ("engine", "pause_network"): PauseRule("transient", 30, 1800),
    ("engine", "pause_killed"): PauseRule("transient", 60, 3600, 3),
    ("engine", "pause_moved"): PauseRule("transient", 60, 3600, 3),
    ("engine", "fault_infra"): PauseRule("transient", 60, 3600),
    ("engine", "fault_crashed"): PauseRule("transient", 60, 3600),
    ("engine", "fault_stale_base"): PauseRule("transient", 60, 3600),
    ("engine", "fault_slot"): PauseRule("needs_owner"),
    ("engine", "fault_denied"): PauseRule("needs_owner"),
    ("engine", "fault_plan"): PauseRule("needs_owner"),
    ("engine", "fault_land"): PauseRule("needs_owner"),
    ("engine", "fault_engine"): PauseRule("needs_owner"),
    ("engine", "fault_bad_request"): PauseRule("needs_owner"),
    ("engine", "fault_contract_skew"): PauseRule("needs_owner"),
    ("engine", "fault_base_red"): PauseRule("needs_owner"),
    ("engine", "ask_decision"): PauseRule("needs_owner"),
    ("engine", "ask_stuck"): PauseRule("needs_owner"),
    ("engine", "ask_budget"): PauseRule("needs_owner"),
    ("engine", "ask_ticket"): PauseRule("needs_owner"),
    ("engine", "wait_ask"): PauseRule("needs_owner"),
    ("engine", "owner_park"): PauseRule("needs_owner"),
    ("engine", "plan_noop"): PauseRule("needs_owner"),
    ("engine", "lost_run"): PauseRule("transient", 60, 3600, 3),
    ("engine", "bd_push_rejected"): PauseRule("needs_owner"),
    ("engine", "dolt_push_rejected"): PauseRule("needs_owner"),
    ("engine", "forge_5xx"): PauseRule("transient", 30, 1800, 3),
}


class ReleasedPolicy(unittest.TestCase):
    def test_every_released_rule_keeps_its_classification_and_numbers(self):
        contract = Path(__file__).resolve().parents[2] / "fixtures/delegate3/skills/delegate/contract.json"
        reasons = json.loads(contract.read_text())["reasons"]
        for (producer, reason), expected in RELEASED.items():
            with self.subTest(producer=producer, reason=reason):
                permanence: Permanence | None = None
                if producer == "delegate" and reason in reasons:
                    raw = reasons[reason]["permanence"]
                    self.assertIn(raw, ("transient", "needs_owner"))
                    permanence = "transient" if raw == "transient" else "needs_owner"
                    if permanence != expected.permanence:
                        self.assertIn(reason, pauses.OVERRIDES)
                self.assertEqual(pauses.rule(reason, producer, permanence), expected)

    def test_owner_overrides_ignore_transient_hints_and_predicted_times(self):
        bead = Bead(id=BeadId("t-1"), title="work", status="open")
        for reason in ("no_lane", "crash"):
            with self.subTest(reason=reason):
                self.assertEqual(pauses.rule(reason, "delegate", "transient"), PauseRule("needs_owner"))
                rec = pauses.after_pause(None, bead, "r1", 100, reason, lambda: 0.5,
                                         not_before=900, producer="delegate", permanence="transient")
                self.assertEqual((rec.permanence, rec.retry_at), ("needs_owner", 0))

    def test_machine_fixed_reasons_keep_the_released_membership(self):
        self.assertEqual(pauses.MACHINE_FIXED, {
            "no_lane", "logged_out", "credit_exhausted", "secrets", "setup",
            "contract_violation", "engine_only_unenforced",
        })
