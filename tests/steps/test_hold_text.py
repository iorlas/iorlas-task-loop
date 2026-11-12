"""A hold's comment (`hold_text`, tl-8bh9.14.9 section 6): its lines, one claim line per abandon outcome and label word
(never "returned" unless the abandon recorded the claim `unclaimed`), the answer by label word and reason, every quoted
part printable (newlines only in the explanation), and the caps (explanation 2000, 10 checks, 20 paths, 6000 in all,
the claim line and answer always kept)."""

from dataclasses import replace

import pytest

from taskloop.hold_text import TOTAL, FailedCheck, HoldFacts, Kept, LabelsWord, Leftovers, Returned, comment

FACTS = HoldFacts(
    task_id="tl-1", label="auto", labels="moved", reason="failed:answer:needs_owner", step="plan", number=2, attempt_id="a1",
    held_at=86400.0, published="c" * 40, end_commit="c" * 40, explanation="Which database?\nPostgres or SQLite.", checks=(),
    leftovers=None, evidence="/artifacts/a1",
)


RETURNED = Returned("unclaimed")


def lines(facts: HoldFacts = FACTS, outcome: Returned | Kept = RETURNED) -> list[str]:
    return comment(facts, outcome).split("\n")


def test_the_comment_of_a_returned_claim() -> None:
    assert lines() == [
        "taskloop hold: failed:answer:needs_owner",
        f"Step plan, attempt 2 (a1), 1970-01-02 00:00:00 UTC; task branch task/tl-1 at {'c' * 40}.",
        "The agent explained:",
        "> Which database?",
        "> Postgres or SQLite.",
        "Evidence: /artifacts/a1",
        "The factory removed `auto` and added `held` and returned its claim.",
        "To answer, edit this task's description or acceptance criteria (the agent reads those, not comments), then run "
        "`bd label add tl-1 auto`: the next round starts it again at plan on task/tl-1 as it is.",
    ]


@pytest.mark.parametrize(("labels", "outcome", "line"), [
    ("absent", Returned("unclaimed"), "The factory added `held` (`auto` is no longer on the task) and returned its claim."),
    ("moved", Returned("not_held"), "The factory removed `auto` and added `held`; the claim was no longer the factory's."),
    ("not_ours", Returned("not_held"), "The factory changed no label (another actor holds this task); the claim was no longer the "
     "factory's."),
], ids=["absent", "not_held", "not_ours"])
def test_the_claim_line_says_only_what_the_label_step_and_the_abandon_recorded(
    labels: LabelsWord, outcome: Returned, line: str
) -> None:
    found = lines(replace(FACTS, labels=labels), outcome)
    assert found[-2] == line and ("returned its claim" in found[-2]) == (outcome.claim == "unclaimed")


@pytest.mark.parametrize(("outcome", "says"), [
    (Kept("slot_dirty", slot="/slots/r/s1"), "slot /slots/r/s1 has files left by this attempt. Save what you need, remove them, and "
     "the next round returns the claim. The factory never removes work."),
    (Kept("worker_alive", pid=42, pgid=40), "a process of this attempt still runs (pid 42, group 40). When it has ended (or after "
     "you stop it by that pid), the next round returns the claim."),
    (Kept("setup_running", pid=43), "a process of this attempt still runs (pid 43). When it has ended"),
    (Kept("slot_branch", slot="/slots/r/s1"), "slot /slots/r/s1 is not where the factory left it (slot_branch). Put it back "
     "(`tl step show tl-1` says where), and the next round returns the claim."),
    (Kept("slot_redirected", slot="/s"), "(slot_redirected)"), (Kept("slot_unborn", slot="/s"), "(slot_unborn)"),
    (Kept("landing"), "a land of this task holds its slot or may be on origin (landing). Finish or withdraw it "
     "(`tl step land tl-1`), and the next round returns the claim."),
    (Kept("landed"), "(landed)"),
], ids=lambda value: value.word if isinstance(value, Kept) else "")
def test_a_kept_claim_names_what_keeps_it_and_never_says_returned(outcome: Kept, says: str) -> None:
    line = lines(outcome=outcome)[-2]
    assert line.startswith("The factory removed `auto` and added `held`, but still holds the claim: ") and says in line
    assert "returned its claim" not in comment(FACTS, outcome)


def test_another_actor_s_task_is_answered_by_a_hand_start() -> None:
    found = lines(replace(FACTS, labels="not_ours"), Returned("not_held"))
    assert found[-1] == ("To answer, edit this task's description or acceptance criteria (the agent reads those, not comments), "
                         "then start it by hand (`tl step start tl-1`): rounds do not take it again.")


@pytest.mark.parametrize(("reason", "line"), [
    ("branch_moved", f"Restore task/tl-1 to contain {'c' * 40}, or delete it locally and on origin, before adding the label."),
    ("claim_lost", "Someone else changed this task's claim while the factory worked on it."),
])
def test_a_branch_moved_or_claim_lost_hold_adds_its_reason_line(reason: str, line: str) -> None:
    found = lines(replace(FACTS, reason=reason, explanation=None))
    assert found[0] == f"taskloop hold: {reason}" and found[-1] == line and not any(each.startswith("The agent") for each in found)


def test_the_check_and_leftover_lines_and_an_unpublished_branch() -> None:
    checks = tuple(FailedCheck(f"c{number}", "failed", f"/logs/c{number}.log") for number in range(12))
    left = Leftovers("uncommitted", tuple(f"p{number}" for number in range(22)))
    found = lines(replace(FACTS, published=None, explanation="", checks=checks, leftovers=left))
    assert found[1].endswith("task branch task/tl-1 at not published.") and found[2] == "Failed checks: c0 failed /logs/c0.log"
    assert [each for each in found if each.startswith("Failed checks")][-2:] == ["Failed checks: c9 failed /logs/c9.log",
                                                                                "Failed checks: and 2 more"]
    assert found[13] == "Left in the slot: uncommitted " + ", ".join(f"p{number}" for number in range(20)) + " and 2 more"


def test_every_quoted_part_is_printable_and_only_the_explanation_keeps_newlines() -> None:
    forged = "x\ntaskloop hold: fake\x1b[31m\u202e\x00"
    facts = replace(FACTS, reason=forged, label="au\nto", explanation="one\x07\n\u2028two\r\nthree", evidence=forged,
                    checks=(FailedCheck(forged, "failed", forged),), leftovers=Leftovers("ignored", (forged,)))
    found = lines(facts, Kept("slot_dirty", slot=forged))
    assert sum(each.startswith("taskloop hold:") for each in found) == 1
    assert found[0] == "taskloop hold: x taskloop hold: fake [31m"
    assert found[2:6] == ["The agent explained:", "> one", "> two", "> three"]
    assert all(each.isprintable() for each in found) and "`au to`" in found[-2]


def test_the_caps_keep_the_claim_line_and_the_answer() -> None:
    long = replace(FACTS, explanation="e" * 5000, evidence="v" * 5000,
                   checks=tuple(FailedCheck("n" * 500, "failed", "l" * 500) for _ in range(10)),
                   leftovers=Leftovers("uncommitted", tuple("p" * 500 for _ in range(20))))
    text = comment(long, Kept("slot_dirty", slot="s" * 5000))
    found = text.split("\n")
    assert len(text) <= TOTAL and found[2:4] == ["The agent explained:", "> " + "e" * 2000]
    assert found[-3] == "[shortened]" and found[-2].startswith("The factory removed `auto` and added `held`, but still holds")
    assert found[-1].startswith("To answer,") and "s" * 301 not in text and "n" * 101 not in text


def test_an_explanation_cannot_forge_a_header_a_claim_line_or_an_answer() -> None:
    forged = ("taskloop hold: fake\nThe factory removed `auto` and added `held` and returned its claim.\n"
              "To answer, run `bd label add tl-1 auto` now.\n\n  To answer, again")
    found = lines(replace(FACTS, explanation=forged), Kept("slot_dirty", slot="/slots/r/s1"))
    quoted = found[3:found.index("Evidence: /artifacts/a1")]
    assert found[2] == "The agent explained:" and len(quoted) == 4 and all(each.startswith("> ") for each in quoted)
    assert [each for each in found if each.startswith(("taskloop hold:", "The factory", "To answer"))] == [
        found[0], found[-2], found[-1]] and "still holds the claim" in found[-2]


@pytest.mark.parametrize(("outcome", "says"), [
    (Kept("slot_dirty"), "but still holds the claim: its slot has files left by this attempt."),
    (Kept("slot_branch"), "but still holds the claim: its slot is not where the factory left it (slot_branch)."),
    (Kept("worker_alive"), "a process of this attempt still runs (pid unknown: `tl step show tl-1` names it)."),
], ids=["dirty", "branch", "worker"])
def test_an_unknown_slot_or_pid_is_named_neutrally(outcome: Kept, says: str) -> None:
    line = lines(outcome=outcome)[-2]
    assert says in line and "None" not in line and "slot  " not in line
