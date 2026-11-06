"""delegate-gsy: `run ROLE --only-family F` keeps only the role's steps of those families, same order, with no fallback outside them."""

import copy

from support.procsim import real_proc

import hermetic  # noqa: F401  (a home of its own for every test)
import routing_support as support
from test_review_order import CFG, T, lanes


class OnlyFamilyTest:
    def decide(self, *up, role="worker", **kw):
        return support.decide(role, copy.deepcopy(CFG), lanes(*up), {}, T, dict({"authored_by": None, "unattended": True}, **kw))

    @real_proc("delegate: a worker, git or CLI process")
    def test_the_answer_never_leaves_the_family_and_names_it(self):
        everything_up = ("openai", "xai", "claude")
        d = self.decide(*everything_up, only_family=["openai"])
        assert (d["action"], d["lane"]) == ("run", "OPENAI_SUBSCRIPTION")




    @real_proc("delegate: a worker, git or CLI process")
    def test_without_the_flag_the_answer_is_unchanged(self):
        for up in (("openai", "xai", "claude"), ("xai", "claude"), ("claude",), ()):
            assert self.decide(*up) == self.decide(*up, only_family=[]), up
            assert self.decide(*up).get("reason") != "only_family_unready", up
