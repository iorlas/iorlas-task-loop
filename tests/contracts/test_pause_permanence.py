"""One permanence per stop reason: the engine's pause policy agrees with delegate's recorded contract (tl-7i9k.26)."""
import json
from pathlib import Path

import pytest

from tlkernel import lanepauses as pauses

REASONS = json.loads((Path(__file__).resolve().parents[2] / "packages/delegate/src/delegate/data/contract.json").read_text(
    encoding="utf-8"))["reasons"]
SYNTHESIZED = {"only_family_unready"}  # a delegate-keyed reason the engine synthesizes, absent from the contract


@pytest.mark.parametrize("reason", sorted(REASONS))
def test_a_contract_reason_pauses_with_its_recorded_permanence(reason):
    recorded = REASONS[reason]["permanence"]
    assert pauses.rule(reason, "delegate", recorded).permanence == recorded
    if ("delegate", reason) in pauses.TABLE:
        assert pauses.TABLE[("delegate", reason)].permanence == recorded


def test_no_lane_and_crash_stay_with_the_owner_whatever_a_stop_says():
    for reason in ("no_lane", "crash"):
        assert pauses.rule(reason, "delegate", "transient").permanence == "needs_owner"


def test_a_delegate_keyed_table_entry_is_in_the_contract_or_declared_synthesized():
    keyed = {reason for producer, reason in pauses.TABLE if producer == "delegate"}
    assert keyed - set(REASONS) <= SYNTHESIZED
