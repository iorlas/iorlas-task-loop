"""A hand run and a loop never share a slot (tl-bxk.9.5): run-task --slot takes the slot bead, a live engine in a slot's
worktree keeps it busy whatever its bead says, a hold reserves a slot for a person, and a stopped engine's worker dies
with it."""
import os
import threading
import time
from unittest import mock

import support.paths  # noqa: F401  (ROOT/src on sys.path)
from support import slots as sl
from support import tlbd
from support.fakes import as_bead
from support.spawn import port_git, real_spawner
from support.who import who

from slots.real.test_slots import NO_FCNTL, Slots
from taskloop.app.slots import (
    marks,
)
from taskloop.app.wire import slots as wslots
from taskloop.contracts.config import SlotsConfig


class SlotListLogic(Slots):
    def test_slot_list_names_the_waiters_in_the_order_they_are_served(self):
        """tl-43k: P0 first, then arrival; the list says so."""
        self.beads({"x-1": []})
        a, b = sl.take_ticket(self.repo, "run-task late-p2", 2), sl.take_ticket(self.repo, "run-task hclf.34", 0)
        try:
            _rc, out = self.cli("slot", "list")
        finally:
            sl.drop_ticket(self.repo, a)
            sl.drop_ticket(self.repo, b)
        rows = [x.split("\t") for x in out.splitlines() if x.startswith("WAITING")]
        self.assertEqual([(r[1], r[2], r[4]) for r in rows], [("1", "P0", "run-task hclf.34"), ("2", "P2", "run-task late-p2")])


class HoldLogic(Slots):
    def test_hold_default_is_an_hour_and_renewing_extends_it(self):
        bd = self.beads({})

        self.cli("slot", "hold", "s1", "--why", "a person")
        until = float(bd.slots["sl-1"]["metadata"]["hold_until"])  # pyrefly: ignore[bad-index]
        self.assertAlmostEqual(until - self.clock.t, 3600, delta=1)
        self.clock.t += 1800
        self.assertEqual(self.cli("slot", "hold", "s1", "--why", "a person")[0], 0)
        self.assertAlmostEqual(float(bd.slots["sl-1"]["metadata"]["hold_until"]) - self.clock.t, 3600, delta=1)  # pyrefly: ignore[bad-index]


class HoldRacesLogic(Slots):
    def test_a_hold_that_loses_the_claim_is_refused(self):
        bd = self.beads({})
        bd.taken_by_other.add("sl-1")
        rc, out = self.cli("slot", "hold", "s1", "--why", "x")
        self.assertEqual(rc, 1)
        self.assertIn("BUSY", out)
        self.assertNotIn("hold_until", bd.slots["sl-1"].get("metadata", {}))

    @NO_FCNTL
    def test_a_hold_taken_while_the_loop_releases_the_slot_is_kept(self):
        # race test (tl-bxk.11.1): the release unclaimed the slot bead, a person's hold claimed it at once, and the
        # release's own clean-up then wiped the hold's metadata: the hold was gone, the slot only leased
        bd = self.beads({})
        self.assertTrue(sl.take_slot(str(self.repo), SlotsConfig()))
        real, holds = bd.__call__, []
        racer: list[threading.Thread] = []

        def hold():
            with mock.patch.dict(os.environ, {"TASK_LOOP_ACTOR": "tl-denis000"}):
                holds.append(self.cli("slot", "hold", "s1", "--why", "screenshots")[0])

        def racing(*a, **kw):  # the release runs under slot_lock: the hold waits for it, never lands in between
            r = real(*a, **kw)
            if a[:1] == ("unclaim",) and a[1] == "sl-1":
                th = threading.Thread(target=hold)
                th.start()
                th.join(0.3)
                self.assertEqual(holds, [])
                racer.append(th)
            return r
        with tlbd.bd_boundary(racing):
            wslots.release_slot(str(self.repo), "s1", spawner=real_spawner(), git=port_git(), who=who())
        racer[0].join(10)
        self.assertEqual(holds, [0])
        self.assertEqual(bd.slots["sl-1"]["assignee"], "tl-denis000")
        self.assertIn("hold_until", bd.slots["sl-1"].get("metadata", {}))
        self.assertTrue(marks.hold_of(as_bead(bd.slots["sl-1"]), time.time()))
