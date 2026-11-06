"""The Beads contract, one suite for every implementation: the in-memory fake and `bd` itself in a throwaway database.
A subclass sets `make() -> Beads` (a fresh, empty store) and gets every test below."""

import pytest
from support.case import Case
from support.tags import contract  # noqa: F401  (re-exported for the subclasses)

from taskloop.contracts.beadsport import BdFailure, BeadPatch, BeadQuery, Beads, NewBead
from taskloop.contracts.ids import BeadId

# A mixin: only a subclass that is also collected runs; the checker sees addCleanup and subTest through this base.
_Base = Case


class BeadsContract(_Base):
    ACTOR = "tester"

    def make(self) -> Beads:
        raise NotImplementedError

    def setup_method(self) -> None:
        self.beads = self.make()
        self.created: set[str] = set()

    def ours(self, found: list) -> set[str]:  # type: ignore[type-arg]
        """Ids of `found` this test made: a real database is shared by the whole class."""
        return {b.id for b in found} & self.created

    def new(self, title: str = "a bead", **kw: object) -> str:
        bead = self.beads.create(NewBead(title=title, **kw))  # type: ignore[arg-type]
        self.created.add(bead)
        return bead

    def test_create_then_show(self) -> None:
        bead = self.new("second", priority=1, labels=["slot", "a"], description="dd", acceptance_criteria="ac")
        got = self.beads.show(BeadId(bead))
        assert got is not None
        assert (got.title, got.status, got.priority, got.description, got.acceptance_criteria) == ("second", "open", 1, "dd", "ac")
        assert got.labels == ["a", "slot"]

    def test_show_of_an_unknown_bead_is_none(self) -> None:
        assert self.beads.show(BeadId("zz-nope")) is None
        assert self.beads.comments(BeadId("zz-nope")) == []

    def test_a_comment_is_kept_with_its_author(self) -> None:
        bead = self.new()
        self.beads.add_comment(BeadId(bead), "hi there")
        got = self.beads.comments(BeadId(bead))
        assert [(c.author, c.text) for c in got] == [(self.ACTOR, "hi there")]

    def test_claim_takes_an_open_bead_once_and_not_a_closed_one(self) -> None:
        bead, done = self.new(), self.new("done")
        assert self.beads.claim(BeadId(bead))
        got = self.beads.show(BeadId(bead))
        assert got is not None
        assert (got.status, got.assignee) == ("in_progress", self.ACTOR)
        self.beads.close(BeadId(done), "done")
        assert not self.beads.claim(BeadId(done))

    def test_unclaim_gives_the_bead_back(self) -> None:
        bead = self.new()
        self.beads.claim(BeadId(bead))
        assert self.beads.unclaim(BeadId(bead))
        got = self.beads.show(BeadId(bead))
        assert got is not None
        assert (got.status, got.assignee) == ("open", "")

    def test_metadata_round_trip(self) -> None:
        bead = self.new()
        self.beads.update(BeadId(bead), BeadPatch(set_metadata={"slot": "s1", "held_bead": "x-1"}))
        got = self.beads.show(BeadId(bead))
        assert got is not None
        assert got.metadata == {"slot": "s1", "held_bead": "x-1"}
        self.beads.update(BeadId(bead), BeadPatch(unset_metadata=["slot", "held_bead"]))
        got = self.beads.show(BeadId(bead))
        assert got is not None
        assert got.metadata == {}

    def test_update_changes_status_and_assignee(self) -> None:
        bead = self.new()
        self.beads.claim(BeadId(bead))
        self.beads.update(BeadId(bead), BeadPatch(status="open", assignee=""))
        got = self.beads.show(BeadId(bead))
        assert got is not None
        assert (got.status, got.assignee) == ("open", "")

    def test_close_removes_a_bead_from_the_default_list(self) -> None:
        keep, gone = self.new("keep"), self.new("gone")
        self.beads.close(BeadId(gone), "done")
        shown = self.ours(self.beads.find(BeadQuery()))
        everything = self.ours(self.beads.find(BeadQuery(include_closed=True)))
        closed = self.ours(self.beads.find(BeadQuery(status="closed")))
        assert (shown, everything, closed) == ({keep}, {keep, gone}, {gone})

    def test_a_fenced_close_keeps_its_reason_and_a_stale_fence_changes_nothing(self) -> None:
        mine, theirs = self.new("mine"), self.new("theirs")
        self.beads.claim(BeadId(mine))
        self.beads.claim(BeadId(theirs))
        self.beads.close(BeadId(mine), "landed", if_assignee=self.ACTOR)
        with pytest.raises(BdFailure):
            self.beads.close(BeadId(theirs), "landed", if_assignee="someone-else")
        a, b = self.beads.show(BeadId(mine)), self.beads.show(BeadId(theirs))
        assert a is not None and b is not None
        assert (a.status, a.close_reason, b.status, b.close_reason) == ("closed", "landed", "in_progress", "")

    def test_find_by_label_and_status(self) -> None:
        a, b = self.new("a", labels=["slot"]), self.new("b")
        self.beads.claim(BeadId(b))
        assert self.ours(self.beads.find(BeadQuery(label="slot"))) == {a}
        assert self.ours(self.beads.find(BeadQuery(status="in_progress"))) == {b}

    def test_ready_lists_open_beads_only(self) -> None:
        a, b = self.new("a"), self.new("b")
        self.beads.claim(BeadId(b))
        assert self.ours(self.beads.ready()) == {a}

    def test_labels_add_and_remove(self) -> None:
        bead = self.new()
        self.beads.add_label(BeadId(bead), "zed")
        self.beads.add_label(BeadId(bead), "alpha")
        assert (self.beads.show(bead) or pytest.fail("gone")).labels == ["alpha", "zed"]  # type: ignore[attr-defined]
        self.beads.remove_label(BeadId(bead), "zed")
        assert (self.beads.show(bead) or pytest.fail("gone")).labels == ["alpha"]  # type: ignore[attr-defined]

    def test_a_write_to_an_unknown_bead_raises_not_found(self) -> None:
        with pytest.raises(BdFailure) as cm:  # type: ignore[attr-defined]
            self.beads.close(BeadId("zz-nope"), "done")
        assert cm.value.error.kind == "not_found"
