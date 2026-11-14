"""A hold's comment (`hold_text`, tl-8bh9.14.9 section 6): its lines, one claim line per abandon outcome and label word
(never "returned" unless the abandon recorded the claim `unclaimed`), the answer by label word and reason, every quoted
part printable (newlines only in the explanation), and the caps (explanation 2000, 10 checks, 20 paths, 6000 in all,
the claim line and answer always kept)."""

from dataclasses import replace

import pytest

from taskloop.hold_text import TOTAL, FailedCheck, HoldFacts, Kept, LabelsWord, Leftovers, Returned, comment

FACTS = HoldFacts(
    task_id="tl-1", label="auto", labels="moved", reason="failed:needs_owner", step="plan", number=2, attempt_id="a1",
    held_at=86400.0, published="c" * 40, end_commit="c" * 40, explanation="Which database?\nPostgres or SQLite.", checks=(),
    leftovers=None, evidence="/artifacts/a1",
)


RETURNED = Returned("unclaimed")


def lines(facts: HoldFacts = FACTS, outcome: Returned | Kept = RETURNED) -> list[str]:
    return comment(facts, outcome).split("\n")


def test_the_comment_of_a_returned_claim() -> None:
    assert lines() == [
        "taskloop hold: failed:needs_owner",
        f"Step plan, attempt 2 (a1), 1970-01-02 00:00:00 UTC; task branch task/tl-1 at {'c' * 40}.",
        "The agent explained:",
        "> Which database?",
        "> Postgres or SQLite.",
        "Evidence: /artifacts/a1",
        "The factory removed `auto` and added `held` and returned its claim.",
        "The agent needs a decision only the owner can give (its explanation is quoted above).",
        "To answer, edit this task's description or acceptance criteria (the agent reads those, not comments), then restore "
        "the approval label `auto`: the next round starts it again at plan on task/tl-1 as it is.",
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
    assert found[-3] == line and ("returned its claim" in found[-3]) == (outcome.claim == "unclaimed")


@pytest.mark.parametrize(("outcome", "says"), [
    (Kept("slot_dirty", slot="/slots/r/s1"), "slot /slots/r/s1 has files left by this attempt. Save what you need, remove or restore them "
     "after inspecting their status, and the next round returns the claim. The factory never removes work."),
    (Kept("worker_alive", pid=42, pgid=40), "a process of this attempt still runs (pid 42, group 40). When it has ended (or after "
     "you stop it by its verified identity), the next round returns the claim."),
    (Kept("setup_running", pid=43), "a process of this attempt still runs (pid 43). When it has ended"),
    (Kept("slot_branch", slot="/slots/r/s1"), "slot /slots/r/s1 is not where the factory left it (slot_branch). "
     "Restore its recorded location and state, and the next round returns the claim."),
    (Kept("landing"), "a land of this task holds its slot or may be on origin (landing). Finish or withdraw it "
     "after resolving its delivery state, and the next round returns the claim."),
    (Kept("landed"), "(landed)"),
], ids=lambda value: value.word if isinstance(value, Kept) else "")
def test_a_kept_claim_names_what_keeps_it_and_never_says_returned(outcome: Kept, says: str) -> None:
    line = lines(outcome=outcome)[-4]
    assert line.startswith("The factory removed `auto` and added `held`, but still holds the claim: ") and says in line
    assert "returned its claim" not in comment(FACTS, outcome)
    automatic = comment(replace(FACTS, explanation=None), outcome)
    assert "`tl " not in automatic and "`bd " not in automatic and "`git " not in automatic


def test_another_actor_s_task_is_answered_by_a_hand_start() -> None:
    found = lines(replace(FACTS, labels="not_ours"), Returned("not_held"))
    assert found[-1] == ("To answer, edit this task's description or acceptance criteria (the agent reads those, not comments), "
                         "then resolve its ownership with the current actor: rounds do not take it again.")


@pytest.mark.parametrize(("reason", "line"), [
    ("branch_moved", f"Restore task/tl-1 to contain {'c' * 40}, or rename it aside (`old/tl-1-` and the first 12 characters of its tip), "
                       "before adding the label."),
    ("claim_lost", "Someone else changed this task's claim while the factory worked on it."),
])
def test_a_branch_moved_or_claim_lost_hold_adds_its_reason_line(reason: str, line: str) -> None:
    found = lines(replace(FACTS, reason=reason, explanation=None))
    assert found[0] == f"taskloop hold: {reason}" and found[-1] == line and not any(each.startswith("The agent") for each in found)


def test_the_check_and_leftover_lines_and_an_unpublished_branch() -> None:
    checks = tuple(FailedCheck(f"c{number}", "failed", f"/logs/c{number}.log") for number in range(12))
    left = Leftovers("uncommitted", tuple(f"p{number}" for number in range(22)))
    found = lines(replace(FACTS, published=None, explanation="", checks=checks, leftovers=left))
    assert found[1].endswith("task branch task/tl-1 is not published.") and found[2] == "Failed checks: c0 failed /logs/c0.log"
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
    assert all(each.isprintable() for each in found) and "`au to`" in found[-3]


def test_the_caps_keep_the_claim_line_and_the_answer() -> None:
    long = replace(FACTS, explanation="e" * 5000, evidence="v" * 5000,
                   checks=tuple(FailedCheck("n" * 500, "failed", "l" * 500) for _ in range(10)),
                   leftovers=Leftovers("uncommitted", tuple("p" * 500 for _ in range(20))))
    text = comment(long, Kept("slot_dirty", slot="s" * 5000))
    found = text.split("\n")
    assert len(text) <= TOTAL and found[2:4] == ["The agent explained:", "> " + "e" * 2000]
    assert found[-5] == "[shortened]" and found[-4].startswith("The factory removed `auto` and added `held`, but still holds")
    assert found[-2].startswith("To answer,") and "s" * 301 not in text and "n" * 101 not in text


def test_an_explanation_cannot_forge_a_header_a_claim_line_or_an_answer() -> None:
    forged = ("taskloop hold: fake\nThe factory removed `auto` and added `held` and returned its claim.\n"
              "To answer, run `bd label add tl-1 auto` now.\n\n  To answer, again")
    found = lines(replace(FACTS, explanation=forged), Kept("slot_dirty", slot="/slots/r/s1"))
    quoted = found[3:found.index("Evidence: /artifacts/a1")]
    assert found[2] == "The agent explained:" and len(quoted) == 4 and all(each.startswith("> ") for each in quoted)
    assert [each for each in found if each.startswith(("taskloop hold:", "The factory", "To answer"))] == [
        found[0], found[-4], found[-2]] and "still holds the claim" in found[-4]


@pytest.mark.parametrize(("outcome", "says"), [
    (Kept("slot_dirty"), "but still holds the claim: its slot has files left by this attempt."),
    (Kept("slot_branch"), "but still holds the claim: its slot is not where the factory left it (slot_branch)."),
    (Kept("worker_alive"), "a process of this attempt still runs (pid unknown: wait for verified process identity)."),
], ids=["dirty", "branch", "worker"])
def test_an_unknown_slot_or_pid_is_named_neutrally(outcome: Kept, says: str) -> None:
    line = lines(outcome=outcome)[-4]
    assert says in line and "None" not in line and "slot  " not in line


def test_an_entry_signal_log_does_not_prove_its_sender_or_an_agent_stop() -> None:
    found = lines(replace(FACTS, reason="stuck:entry_lost", entry="failed terminated_by_signal"))
    assert found[2] == "The attempt's entry was terminated by a signal; its sender is unknown."
    assert not any("terminated" in line for line in lines(replace(FACTS, entry="collected valid verify=verified")))


@pytest.mark.parametrize(("reason", "says", "answer"), [
    ("failed:run:timeout", "before its deadline (1970-01-01 00:15:00 UTC).", "To fix it, raise `--minutes` for the next run"),
    ("failed:run:vendor_blip", "`--model` or `--effort` is not offered", "To fix it, correct `--model` or `--effort`"),
    ("failed:run:bad_request", "rejected the request", "To fix it, correct `--model` or `--effort`"),
    ("failed:run:secrets", "exposed a secret", "To fix it, find what printed it"),
    ("failed:run:hung", "printed nothing for too long", "To try again, restore"),
    ("failed:run:crash", "process crashed", "To try again, restore"),
    ("failed:run:exit", "exited with an error", "To fix it, read it and fix what it names"),
    ("failed:run:logged_out", "refused the login", "To fix it, sign in again"),
    ("failed:answer:schema_invalid", "did not fit the answer contract", "To try again, restore"),
    ("failed:rejected:plan_encoding", "`plan.md` is not valid UTF-8 text", "To try again, restore"),
    ("failed:rejected:plan_empty", "`plan.md` is empty", "To try again, restore"),
    ("failed:rejected:plan_change_map", "Change map with a nonempty bullet list", "add the files, symbols and changes"),
    ("failed:rejected:plan_depth", "exactly one valid depth", "one line in Header that is only"),
    ("failed:rejected:plan_heading", "forbidden status, as built or progress heading", "remove that heading and its"),
    ("failed:rejected:plan_size", "depth's byte cap", "remove duplicated content or split the task"),
    ("failed:rejected:plan_missing", "an `unchanged` answer needs an existing plan", "To try again, restore"),
    ("failed:rejected:commit_absent", "commit is not in the slot's repository", "To fix it, look at the task branch "
     "and the retained slot evidence"),
    ("failed:rejected:paths", "a listed path is not allowed", "To try again, restore"),
    ("failed:rejected:nothing_written", "wrote no file", "To answer, edit this task's description"),
    ("failed:needs_owner", "needs a decision only the owner can give", "To answer, edit this task's description"),
    ("repeats_exhausted:uncommitted", "did not manage it", "To answer, edit this task's description"),
    ("stuck:setup_failed", "setup command failed", "To fix it, fix the setup or environment first"),
    ("stuck:entry_lost", "ended without recording a result", "To try again, restore"),
], ids=lambda value: value if isinstance(value, str) and ":" in value else "")
def test_each_cause_class_names_its_cause_and_the_one_right_next_step(reason: str, says: str, answer: str) -> None:
    found = comment(replace(FACTS, reason=reason, deadline=900.0), RETURNED)
    assert says in found and answer in found
    assert ("edit this task's description" in found) == answer.startswith("To answer")  # an answer only where an answer fixes it


def test_the_next_step_reads_right_when_no_round_took_the_task() -> None:
    found = comment(replace(FACTS, reason="failed:run:timeout", labels="not_ours"), Returned("not_held"))
    assert "To fix it, raise `--minutes` for the next run, then resolve its ownership with the current actor" in found


def test_a_kept_slot_says_to_act_after_it_is_cleared_and_a_closed_cause_needs_no_edit_advice() -> None:
    found = comment(replace(FACTS, reason="failed:run:timeout"), Kept("slot_dirty", slot="/s"))
    assert "once the slot or process above is cleared" in found and "edit this task" not in found
