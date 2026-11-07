"""The review stage's writes go through its own state and ledger, not through lists on the engine (docs/design/b-review.md, slice 2)."""
from tlwork.review.state import ReviewLive
from tlwork.testing import FakeReview


def test_a_verifier_answer_is_recorded_with_its_five_fields():
    live = ReviewLive()
    live.add_verified({"what": "w", "kind": "k"}, "settled", "why", "ev")
    assert live.verified == [{"what": "w", "kind": "k", "verdict": "settled", "why": "why", "evidence": "ev"}]


def test_an_unverified_item_is_kept_once_by_its_text():
    live = ReviewLive()
    live.add_unverified({"what": "w", "kind": "k", "source": "s"}, "first")
    live.add_unverified({"what": "w", "kind": "other"}, "second")
    assert live.unverified == [{"what": "w", "kind": "k", "why": "first", "source": "s"}]


def test_a_leftover_is_added_once_by_title_and_says_whether_it_was_new(workdir):
    review = FakeReview(workdir)
    host, routing = review.hand, review.routing
    host.leftovers[:] = [{"title": "t"}]
    assert routing.add_leftover({"title": "t", "why": "again"}) is False
    assert routing.add_leftover({"title": "u"}) is True
    assert host.leftovers == [{"title": "t"}, {"title": "u"}]
