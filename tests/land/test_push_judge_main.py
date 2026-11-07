"""The pre-push judge's guard of main (merge-queue.md 8.1): with the guard on, a push to the base branch must come from tl's own land push
or release, which name themselves in the land lock; pushes to other branches never meet the rule; with the guard off nothing changes."""
from unittest import mock

import pytest
from support.memstores import fake_stores

from taskloop.app.land.push_judge import PushStatus, judge_push
from taskloop.contracts.env import Env
from taskloop.contracts.gitport import Git

SHA = "a" * 40


def judge(remote: str, holder: str, guard: bool = True):
    git = mock.create_autospec(Git, instance=True)
    git.symbolic_ref.return_value = ""
    git.rev_parse.return_value = ""
    request = f"refs/heads/x {SHA} {remote} {'0' * 40}\n"
    return judge_push("/repo", request, fake_stores(), git, env=Env({}), guard_main=guard, lock_holder=holder)


@pytest.mark.parametrize("holder", ["", "pid 12", "tl-abc", "reflect", "someone"])
def test_an_unmarked_push_to_main_is_refused(holder):
    decision = judge("refs/heads/main", holder)
    assert decision.status == PushStatus.REFUSED and "outside `tl land` and the release" in decision.reasons[0]


@pytest.mark.parametrize("holder", ["release: 1.2.3", "land-stack sess-1", "land tl-abc", "land-lock pid 4 (git push)"])
def test_a_push_under_the_land_lock_of_a_land_or_release_passes_the_guard(holder):
    decision = judge("refs/heads/main", holder)
    assert not any("outside `tl land`" in r for r in decision.reasons)


@pytest.mark.parametrize("remote", ["refs/heads/claude/slug", "refs/heads/task/a", "refs/tags/v1"])
def test_a_push_to_another_branch_never_meets_the_guard(remote):
    assert not any("outside" in r for r in judge(remote, "").reasons)


def test_with_the_guard_off_an_unmarked_push_is_judged_as_before():
    assert not any("outside" in r for r in judge("refs/heads/main", "", guard=False).reasons)
