"""A hold's tracker writes (`tracker_client.TrackerHolds`, tl-8bh9.14.9 sections 5.2 and 5.4) and the unclaim of a closed
or deleted task (5.3), over beads_client's scripted runner: the argv and their order (the fence before the labels, `held`
added before the approval label goes), every row of 5.2, bd's failures, and each call capped at BD_TIMEOUT_S."""

import json
from pathlib import Path

import pytest
from beads_client import Bd, BdError
from beads_client.testing import Script

from taskloop.claim_lease import BD_TIMEOUT_S
from taskloop.tracker_client import HoldAnswer, tracker_claims, tracker_holds

ACTOR = ["--actor", "taskloop"]
DELETED = '{"error": "resolving tl-1: no issue found matching \\"tl-1\\"", "schema_version": 1}'
# bd 1.3.1's unclaim of a closed task (measured 2026-11-12): exit 1, nothing written, the task stays closed.
UNCLAIM_CLOSED = '{"error": "cannot unclaim closed issue tl-1", "schema_version": 1}'
DOWN = '{"error": "database is down", "schema_version": 1}'


def show(status: str = "in_progress", assignee: str = "taskloop", labels: tuple[str, ...] = ("auto",)) -> str:
    return json.dumps([{"id": "tl-1", "title": "Widget", "status": status, "assignee": assignee, "labels": list(labels)}])


def calls(script: Script) -> list[list[str]]:
    return [argv[1:] for argv in script.calls]


def fence(assignee: str) -> list[str]:
    return [*ACTOR, "update", "tl-1", "--if-assignee", assignee, "--assignee", assignee, "--json"]


SHOW = [*ACTOR, "show", "tl-1", "--json"]
ADD = [*ACTOR, "label", "add", "tl-1", "held", "--json"]
REMOVE = [*ACTOR, "label", "remove", "tl-1", "auto", "--json"]


@pytest.mark.parametrize(("shown", "word", "assignee"), [
    (show(), "moved", "taskloop"),
    (show(labels=("auto", "other")), "moved", "taskloop"),
    (show(labels=("other",)), "absent", "taskloop"),
    (show("open", ""), "moved", ""),  # the claim lapsed or was reverted: fenced on no assignee (measured)
    (show("open", "", ()), "absent", ""),
], ids=["ours", "ours_two_labels", "ours_absent", "unassigned", "unassigned_absent"])
def test_the_label_step_fences_on_the_assignee_read_then_adds_held_then_removes_the_stored_label(
    tmp_path: Path, shown: str, word: str, assignee: str
) -> None:
    script = Script().say(shown)
    assert tracker_holds(script).labels(str(tmp_path), "tl-1", "auto") == HoldAnswer(word, assignee)  # the assignee read
    assert calls(script) == [SHOW, fence(assignee), ADD, REMOVE]


@pytest.mark.parametrize(("reply", "word"), [
    ((show(assignee="someone"), "", 0), "not_ours"),
    ((show("open", "someone"), "", 0), "not_ours"),
    ((show("closed"), "", 0), "closed"),  # closed while still assigned to the factory: bd would accept a label (5.4)
    ((show("closed", ""), "", 0), "closed"),
    (("", "Error: Issue tl-1 not found", 1), "missing"),
], ids=["another_actor", "open_another_actor", "closed_ours", "closed", "missing"])
def test_another_actor_s_closed_or_missing_task_is_read_and_written_nothing(
    tmp_path: Path, reply: tuple[str, str, int], word: str
) -> None:
    script = Script().say(*reply)
    assert tracker_holds(script).labels(str(tmp_path), "tl-1", "auto") == HoldAnswer(word)
    assert calls(script) == [SHOW]


@pytest.mark.parametrize(("replies", "expected", "written"), [
    ([("", "", 13)], HoldAnswer("precondition"), [fence("taskloop")]),  # stale fence: nothing written, labels unset
    ([("", "", 0), (DOWN, "", 1)], HoldAnswer("unavailable", "other"), [fence("taskloop"), ADD]),
    ([("", "", 0), ("", "", 0), ("", "bd: no answer in 30.0s", 124)], HoldAnswer("unavailable", "timeout"),
     [fence("taskloop"), ADD, REMOVE]),
    ([("", "", 0), (DELETED, "", 1)], HoldAnswer("missing"), [fence("taskloop"), ADD]),
], ids=["fence_stale", "add_failed", "remove_timed_out", "deleted_meanwhile"])
def test_a_failed_label_write_is_retried_by_the_next_round(
    tmp_path: Path, replies: list[tuple[str, str, int]], expected: HoldAnswer[str], written: list[list[str]]
) -> None:
    script = Script().say(show())
    for out, err, code in replies:
        script.say(out, err, code)
    assert tracker_holds(script).labels(str(tmp_path), "tl-1", "auto") == expected
    assert calls(script) == [SHOW, *written]


@pytest.mark.parametrize("label", ["", "-auto", "--force"])
def test_a_label_bd_would_read_as_a_flag_is_refused_before_any_call(tmp_path: Path, label: str) -> None:
    script = Script().say(show())
    assert tracker_holds(script).labels(str(tmp_path), "tl-1", label) == HoldAnswer("bad_label")
    assert script.calls == []


def test_a_locked_tracker_is_asked_once_and_retried_by_the_next_round(tmp_path: Path) -> None:
    script = Script().say("", "embeddeddolt: acquiring lock: busy", 1)
    assert tracker_holds(script).comment(str(tmp_path), "tl-1", "text") == HoldAnswer("unavailable", "other")
    assert len(script.calls) == 1


def test_an_unanswered_read_writes_nothing(tmp_path: Path) -> None:
    script = Script().say("", "bd: no answer in 30.0s", 124)
    assert tracker_holds(script).labels(str(tmp_path), "tl-1", "auto") == HoldAnswer("unavailable", "timeout")
    assert calls(script) == [SHOW]


def test_the_comment_and_the_clear_are_one_bd_call_each_with_no_read(tmp_path: Path) -> None:
    script = Script()
    holds = tracker_holds(script)
    text = "taskloop hold: failed:run:timeout\nline two"
    assert holds.comment(str(tmp_path), "tl-1", text) == HoldAnswer("done")
    assert holds.clear(str(tmp_path), "tl-1") == HoldAnswer("done")
    assert calls(script) == [[*ACTOR, "comments", "add", "tl-1", text, "--json"], [*ACTOR, "label", "remove", "tl-1", "held", "--json"]]


@pytest.mark.parametrize(("reply", "expected"), [
    ((DOWN, "", 1), HoldAnswer("unavailable", "other")), (("", "bd: no answer in 30.0s", 124), HoldAnswer("unavailable", "timeout")),
    ((DELETED, "", 1), HoldAnswer("missing")),
], ids=["failed", "timeout", "deleted"])
def test_a_failed_comment_or_clear_is_a_word(tmp_path: Path, reply: tuple[str, str, int], expected: HoldAnswer[str]) -> None:
    for write in ("comment", "clear"):
        script = Script().say(*reply)
        holds = tracker_holds(script)
        found = holds.comment(str(tmp_path), "tl-1", "text") if write == "comment" else holds.clear(str(tmp_path), "tl-1")
        assert found == expected and len(script.calls) == 1


def test_every_hold_call_is_capped_at_bd_timeout_at_the_resolved_root(tmp_path: Path) -> None:
    built: list[dict[str, object]] = []

    class Recorded(Bd):
        def __init__(self, actor: str, cwd: str | None = None, **options: object) -> None:
            built.append({"actor": actor, "cwd": cwd} | {key: value for key, value in options.items() if key != "run"})
            super().__init__(actor, cwd, run=Script().say("", "bd: no answer in 30.0s", 124))

    holds = tracker_holds(Script(), client=Recorded)
    root = str(tmp_path / "x" / "..")
    assert holds.labels(root, "tl-1", "auto") == holds.comment(root, "tl-1", "t") == holds.clear(root, "tl-1") == HoldAnswer(
        "unavailable", "timeout")
    # one try each (no lock retry): no call outlasts the comment lease
    assert built == [{"actor": "taskloop", "cwd": str(tmp_path.resolve()), "timeout": BD_TIMEOUT_S, "lock_retries": 0}] * 3


@pytest.mark.parametrize(("reply", "back"), [
    (("", "", 0), True),
    (("", "", 13), False),  # the fence: another actor holds it (unchanged)
    ((UNCLAIM_CLOSED, "", 1), False),
    (("", "Error: cannot unclaim closed issue tl-1", 1), False),
    ((DELETED, "", 1), False),
], ids=["returned", "not_ours", "closed", "closed_stderr", "deleted"])
def test_the_unclaim_of_a_closed_or_deleted_task_is_not_held(tmp_path: Path, reply: tuple[str, str, int], back: bool) -> None:
    script = Script().say(*reply)
    assert tracker_claims(script).unclaim(str(tmp_path), "tl-1") is back
    assert calls(script) == [[*ACTOR, "unclaim", "tl-1", "--if-assignee", "taskloop", "--json"]]


@pytest.mark.parametrize("reply", [(DOWN, "", 1), ("", "bd: no answer in 30.0s", 124), ('{"error": "cannot unclaim"}', "", 1)],
                         ids=["failed", "timeout", "other_refusal"])
def test_any_other_unclaim_failure_still_raises_and_stays_unclaiming(tmp_path: Path, reply: tuple[str, str, int]) -> None:
    with pytest.raises(BdError):
        tracker_claims(Script().say(*reply)).unclaim(str(tmp_path), "tl-1")



def test_a_hand_started_land_hold_adds_held_without_removing_any_label(tmp_path: Path) -> None:
    script = Script().say(show(labels=("other",)))
    assert tracker_holds(script).labels(str(tmp_path), "tl-1", None) == HoldAnswer("absent", "taskloop")
    assert calls(script) == [SHOW, fence("taskloop"), ADD]
