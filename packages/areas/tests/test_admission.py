"""Atomic admission uses one store and publishes only after winning inside the lock."""
from contextlib import contextmanager
from unittest import mock

import pytest
from tlkernel.bead import BdError, Bead
from tlkernel.beadsport import BdFailure
from tlkernel.ids import BeadId
from tltestkit.membeads import MemBeads

from tlareas import policy as admission
from tlareas.policy import Areas


class Host:
    __test__ = False

    def __init__(self, configured=True):
        self.events, self.said, self.reads = [], [], []
        self.locked = False
        self.store = MemBeads()
        for bid in ("x-1", "x-2"):
            self.store.put(Bead(id=BeadId(bid), title="", status="open", labels=["lane:live"]))
        self.occupancy = {}
        self.host = self
        self.areas, self.area_label_prefix = {}, "lane:" if configured else ""
        self.area_lock, self.say = self.lock, self.said.append

    @contextmanager
    def lock(self):
        assert not self.locked
        self.locked = True
        self.events.append("lock")
        try:
            yield
        finally:
            self.events.append("unlock")
            self.locked = False

    def running(self):
        assert self.locked
        self.events.append("refresh")
        return self.occupancy

    def step(self, name, result):
        self.events.append(name)
        return result


@pytest.mark.parametrize("configured", [False, True])
@pytest.mark.parametrize("why", ["", "engine held"])
def test_hand_marks_only_after_a_successful_engine_take(configured, why):
    h = Host(configured)
    assert admission.hand(h.host, BeadId("x-1"), False, lambda: h.step("take", why), lambda: h.step("mark", None)) == why
    middle = ["take"] + ([] if why else ["mark"])
    assert h.events == (["lock", "refresh", *middle, "unlock"] if configured else middle)


@pytest.mark.parametrize("exclusive", [False, True])
def test_hand_busy_warning_and_exclusive_refusal(exclusive):
    h = Host()
    h.occupancy = {BeadId("x-2"): "s2"}
    take, mark = mock.Mock(return_value=""), mock.Mock()
    busy = "area live busy: x-2 in s2"
    assert admission.hand(h.host, BeadId("x-1"), exclusive, take, mark) == (busy + " (--exclusive-area)" if exclusive else "")
    assert h.said == ([] if exclusive else [f"⚠ {busy}: running anyway beside it; --exclusive-area refuses instead"])
    assert (take.call_count, mark.call_count) == ((0, 0) if exclusive else (1, 1))


def test_hand_reads_candidate_and_occupants_from_the_supplied_store():
    h = Host()
    h.occupancy = {BeadId("x-2"): "s2"}
    original = h.store.show

    def read(bid):
        assert h.locked
        h.reads.append((h.store, bid))
        return original(bid)

    with mock.patch.object(h.store, "show", side_effect=read):
        why = admission.hand(h.host, BeadId("x-1"), True, mock.Mock(), mock.Mock())
    assert why == "area live busy: x-2 in s2 (--exclusive-area)"
    assert h.reads == [(h.store, "x-1"), (h.store, "x-2")]


@pytest.mark.parametrize("failure", [False, True])
def test_hand_unreadable_candidate_still_takes_the_engine(failure):
    h = Host()
    with mock.patch.object(h.store, "show", side_effect=BdFailure(BdError(kind="other"))) if failure else mock.patch.object(
        h.store, "show", return_value=None
    ):
        assert admission.hand(h.host, BeadId("x-1"), True, lambda: h.step("take", ""), lambda: h.step("mark", None)) == ""
    assert h.events == ["lock", "refresh", "take", "mark", "unlock"]


@pytest.mark.parametrize("busy,won", [(True, False), (False, False), (False, True)])
def test_loop_refresh_check_claim_publish_are_one_transaction(busy, won):
    h = Host()
    if busy:
        h.occupancy = {BeadId("x-2"): "s2"}
    rule = Areas(h.store, {}, "lane:", {})
    original = rule.area_busy

    def check(bead):
        assert h.locked and rule.running is h.occupancy
        h.events.append("check")
        return original(bead)

    def claim():
        assert h.locked
        return h.step("claim", (won, "lost"))

    def publish():
        assert h.locked
        h.step("publish", None)

    with mock.patch.object(rule, "area_busy", side_effect=check):
        got = admission.loop(h.host, h.store.beads[BeadId("x-1")], rule, claim, publish)
    expected = admission.Admission("busy", "area live busy: x-2 in s2") if busy else (
        admission.Admission("won", "") if won else admission.Admission("not_won", "lost"))
    assert got == expected
    assert h.events == ["lock", "refresh", "check", *([] if busy else ["claim"] + (["publish"] if won else [])), "unlock"]


@pytest.mark.parametrize("configured", [False, True])
def test_loop_without_an_area_does_not_publish(configured):
    h = Host(configured)
    bead = Bead(id=BeadId("x-3"), title="", status="open")
    publish = mock.Mock()
    rule = Areas(h.store, {}, "lane:", {})
    assert admission.loop(h.host, bead, rule, lambda: (True, ""), publish).kind == "won"
    publish.assert_not_called()
    assert h.events == (["lock", "refresh", "unlock"] if configured else [])
