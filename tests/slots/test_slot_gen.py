"""A take's generation is one past the slot bead as it is once the claim is won, never past a read made before it (tl-br2.5)."""
from tlkernel.beadsport import BeadPatch
from tlkernel.fence import SLOT_GEN, gen_of
from tlkernel.ids import BeadId
from tlslots.testing import Rig

SLOT = BeadId("sl-s1")


class StaleRead(Rig):
    def stale_slot(self):
        slot = self.slot()  # its bead is read now, at generation 0
        self.bd.update(SLOT, BeadPatch(set_metadata={SLOT_GEN: "5"}))  # another actor took and freed it since
        return slot

    def test_take_is_a_higher_generation_than_one_made_since_the_read(self):
        self.stale_slot().take_locked("why")
        assert gen_of(self.bd.show(SLOT), SLOT_GEN) == 6
