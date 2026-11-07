"""tl-bxk.10.33.14: a loop holds one slot; a slot it still holds with no run in it is given back before the next take."""

import sys
from pathlib import Path
from unittest import mock

import msgspec

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support.paths  # noqa: F401

from slots.test_slot_pool import ME, Rig
from tlslots import verbs
from tlkernel.ids import BeadId


class Leak(Rig):
    def claim(self, name, assignee=ME):
        sb = self.bd.beads[BeadId("sl-" + name)]
        self.bd.beads[sb.id] = msgspec.structs.replace(sb, status="in_progress", assignee=assignee)

    def test_a_slot_the_actor_holds_with_no_engine_is_a_leak(self):
        self.claim("s1")
        assert [s.name for s in self.pool.leaked()] == ["s1"]

    def test_a_slot_with_a_live_engine_another_actors_slot_or_a_free_one_is_not(self):
        self.claim("s1")
        self.busy_at[self.env.dir_of("s1")] = "engine pid 7"
        self.claim("s2", "someone-else")
        assert self.pool.leaked() == []

    def test_releasing_a_leaked_slot_frees_it(self):
        self.claim("s1")
        for slot in self.pool.leaked():
            slot.release(mine=False)
        assert self.bd.beads[BeadId("sl-s1")].status == "open"


class ListShowsAside(Rig):
    def test_a_slot_set_aside_says_so_in_the_list(self):
        sb = self.bd.beads[BeadId("sl-s1")]
        self.bd.beads[sb.id] = msgspec.structs.replace(sb, metadata={"aside_probe": "pending"})
        with mock.patch.object(verbs, "waiting_line", return_value=[]):
            verbs.listing(self.env, None)
        assert any("s1" in line and "set aside: reset probe pending" in line for line in self.out)

    def test_a_claim_without_a_take_record_says_so_instead_of_question_marks(self):
        sb = self.bd.beads[BeadId("sl-s2")]
        self.bd.beads[sb.id] = msgspec.structs.replace(sb, status="in_progress", assignee=ME)
        with mock.patch.object(verbs, "waiting_line", return_value=[]):
            verbs.listing(self.env, None)
        assert any("claimed, no take record" in line for line in self.out)
