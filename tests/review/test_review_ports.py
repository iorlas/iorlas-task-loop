"""Review behaviour on fake ports, without constructing the Engine."""
from support.review_host import FakeReview


def test_leftovers_are_visible_in_the_ledger_and_added_once(workdir):
    review = FakeReview(workdir)
    lo = {"title": "follow up", "why": "later"}
    assert review.routing.add_leftover(lo)
    assert not review.routing.add_leftover(dict(lo, why="again"))
    assert review.hand.leftovers == [lo]
    assert review.routing.ledger().deferred() == [("follow up", "later")]


def test_unused_tool_is_settled_before_a_verifier_call(workdir):
    review = FakeReview(workdir)
    assert review.verifier.run([{"what": "nobody ran ruff on tools/*.py", "kind": "tooling"}]) == []
    assert review.live.verified[0]["why"] == "not a check here"
    assert review.ports.asked == []


def test_a_failed_link_is_a_finding(workdir):
    review = FakeReview(workdir)
    review.live.link_bad["https://example.org"] = "HTTP 404"
    answer = {"findings": []}
    review.link_check.report([("README.md", "source https://example.org", "https://example.org")], answer)
    assert len(answer["findings"]) == 1
    assert "https://example.org" in str(answer["findings"])


def test_no_gaps_needs_no_verifier(workdir):
    review = FakeReview(workdir)
    assert review.verifier.run([]) == []
    assert review.ports.asked == []
    assert review.live.verified == []
