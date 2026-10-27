"""The Beads contract, one suite for every implementation: the in-memory fake and `bd` itself in a throwaway database.
A subclass sets `make() -> Beads` (a fresh, empty store) and gets every test below."""
from support.tags import contract  # noqa: F401  (re-exported for the subclasses)
from taskloop.contracts.ports import BdFailure, BeadPatch, BeadQuery, Beads, NewBead


class BeadsContract:
    ACTOR = "tester"

    def make(self) -> Beads:
        raise NotImplementedError

    def setUp(self) -> None:
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
        got = self.beads.show(bead)
        assert got is not None
        self.assertEqual((got.title, got.status, got.priority, got.description, got.acceptance_criteria),
                         ("second", "open", 1, "dd", "ac"))
        self.assertEqual(got.labels, ["a", "slot"])

    def test_show_of_an_unknown_bead_is_none(self) -> None:
        self.assertIsNone(self.beads.show("zz-nope"))
        self.assertEqual(self.beads.comments("zz-nope"), [])

    def test_a_comment_is_kept_with_its_author(self) -> None:
        bead = self.new()
        self.beads.add_comment(bead, "hi there")
        got = self.beads.comments(bead)
        self.assertEqual([(c.author, c.text) for c in got], [(self.ACTOR, "hi there")])

    def test_claim_takes_an_open_bead_once_and_not_a_closed_one(self) -> None:
        bead, done = self.new(), self.new("done")
        self.assertTrue(self.beads.claim(bead))
        got = self.beads.show(bead)
        assert got is not None
        self.assertEqual((got.status, got.assignee), ("in_progress", self.ACTOR))
        self.beads.close(done, "done")
        self.assertFalse(self.beads.claim(done))

    def test_unclaim_gives_the_bead_back(self) -> None:
        bead = self.new()
        self.beads.claim(bead)
        self.assertTrue(self.beads.unclaim(bead))
        got = self.beads.show(bead)
        assert got is not None
        self.assertEqual((got.status, got.assignee), ("open", ""))

    def test_metadata_round_trip(self) -> None:
        bead = self.new()
        self.beads.update(bead, BeadPatch(set_metadata={"slot": "s1", "held_bead": "x-1"}))
        got = self.beads.show(bead)
        assert got is not None
        self.assertEqual((got.metadata.held_bead, got.metadata.extra), ("x-1", {"slot": "s1"}))
        self.beads.update(bead, BeadPatch(unset_metadata=["slot", "held_bead"]))
        got = self.beads.show(bead)
        assert got is not None
        self.assertEqual((got.metadata.held_bead, got.metadata.extra), ("", {}))

    def test_update_changes_status_and_assignee(self) -> None:
        bead = self.new()
        self.beads.claim(bead)
        self.beads.update(bead, BeadPatch(status="open", assignee=""))
        got = self.beads.show(bead)
        assert got is not None
        self.assertEqual((got.status, got.assignee), ("open", ""))

    def test_close_removes_a_bead_from_the_default_list(self) -> None:
        keep, gone = self.new("keep"), self.new("gone")
        self.beads.close(gone, "done")
        shown = self.ours(self.beads.find(BeadQuery()))
        everything = self.ours(self.beads.find(BeadQuery(include_closed=True)))
        closed = self.ours(self.beads.find(BeadQuery(status="closed")))
        self.assertEqual((shown, everything, closed), ({keep}, {keep, gone}, {gone}))

    def test_find_by_label_and_status(self) -> None:
        a, b = self.new("a", labels=["slot"]), self.new("b")
        self.beads.claim(b)
        self.assertEqual(self.ours(self.beads.find(BeadQuery(label="slot"))), {a})
        self.assertEqual(self.ours(self.beads.find(BeadQuery(status="in_progress"))), {b})

    def test_ready_lists_open_beads_only(self) -> None:
        a, b = self.new("a"), self.new("b")
        self.beads.claim(b)
        self.assertEqual(self.ours(self.beads.ready()), {a})

    def test_labels_add_and_remove(self) -> None:
        bead = self.new()
        self.beads.add_label(bead, "zed")
        self.beads.add_label(bead, "alpha")
        self.assertEqual((self.beads.show(bead) or self.fail("gone")).labels, ["alpha", "zed"])  # type: ignore[attr-defined]
        self.beads.remove_label(bead, "zed")
        self.assertEqual((self.beads.show(bead) or self.fail("gone")).labels, ["alpha"])  # type: ignore[attr-defined]

    def test_a_write_to_an_unknown_bead_raises_not_found(self) -> None:
        with self.assertRaises(BdFailure) as cm:  # type: ignore[attr-defined]
            self.beads.close("zz-nope", "done")
        self.assertEqual(cm.exception.error.kind, "not_found")
