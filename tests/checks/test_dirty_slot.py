"""A dirty slot is distinct from a base missing the configured recipe."""
from types import SimpleNamespace
from unittest import mock

import pytest

from taskloop.app.land.gate import FAULTS
from tlgate.clean import isolated
from tlgate.host import CheckFault
from tlkernel.checks import CheckFaultKind
from tltestkit.case import Case


class DirtySlot(Case):
    def test_dirty_slot_has_its_own_fault_before_a_checkout_is_made(self):
        host = SimpleNamespace(wt="slot", git=mock.Mock(), checkout=mock.Mock())
        host.git.rev_parse.side_effect = ["head", "committed-tree"]
        host.checkout.tree_hash.return_value = "dirty-tree"
        with mock.patch("tlgate.clean.clean_tree") as checkout, pytest.raises(CheckFault) as fault, isolated(host):
            pytest.fail("dirty slot accepted")
        assert fault.value.kind == CheckFaultKind.DIRTY_SLOT
        checkout.assert_not_called()

    def test_land_gate_maps_dirty_slot_to_slot_fault(self):
        assert FAULTS[CheckFaultKind.DIRTY_SLOT] == "FAULT_SLOT"
