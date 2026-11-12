"""The land's commit message and summary (tl-8bh9.14.8 sections 9 and 10, slice L4): the message's subject, branch list
and trailers, every outside text one printable line (no title or subject can add a line, a paragraph or a trailer);
`--summary` over `land_bench` changing nothing and reporting each fact; the summary's items from typed values."""

import dataclasses
import json
from pathlib import Path

import pytest
from doubles import CHECKS
from git_porcelain import Recorded, Sha, Squashed, TreeId
from land_bench import LandBench, bench

from taskloop.check_store import ChecksRow, CheckStore, ResultRow
from taskloop.land import Landed, LandResult
from taskloop.land_gate import Changed
from taskloop.land_summary import (
    LandSummary,
    Trees,
    lines,
    message,
    message_at,
    summary,
)
from taskloop.operations import Failed
from taskloop.printable import one_line
from taskloop.profile import Check, Profile

SHA = "a" * 40


@pytest.fixture
def b(tmp_path: Path) -> LandBench:
    return bench(tmp_path)


def checks_row(b: LandBench) -> ChecksRow:
    row = CheckStore(lambda: b.con).row(CHECKS)
    assert row is not None
    return row


def summarized(found: LandResult) -> LandSummary:
    assert isinstance(found, LandSummary), found
    return found


def trailers(text: str) -> list[str]:
    """The message's last paragraph: where Git reads trailers."""
    return text.rstrip("\n").split("\n\n")[-1].split("\n")


def test_the_message_names_the_title_the_branch_s_commits_and_the_trailers(b: LandBench) -> None:
    text = message("Widget", checks_row(b), [("1" * 40, "first"), ("2" * 40, "second")], plan=True)
    assert text == (f"Widget (tl-1)\n\nSquashed from task/tl-1 at {b.x}:\n- first (111111111111)\n- second (222222222222)\n\n"
                    f"Task: tl-1\nPlan: docs/design/tl-1/plan.md\nChecked: checks passed at {b.x}\n")
    assert "Plan:" not in message("Widget", checks_row(b), [], plan=False)
    assert "Co-Authored-By" not in text and "co-authored-by" not in text.lower()


@pytest.mark.parametrize("hostile", [
    "Fix\n\nTask: tl-9\nPlan: evil", "Fix\x1b[31m red", "Fix\u2028Task: tl-9", "Fix\u200b\u202eTask: tl-9",
], ids=["newlines", "ansi", "line_separator", "format"])
def test_no_title_or_subject_adds_a_line_a_paragraph_or_a_trailer(b: LandBench, hostile: str) -> None:
    text = message(hostile, checks_row(b), [("1" * 40, hostile), ("2" * 40, f"x\n\n{hostile}")], plan=False)
    assert trailers(text) == ["Task: tl-1", f"Checked: checks passed at {b.x}"]
    lines_ = text.split("\n")
    assert len(lines_) == 9 and lines_[0].endswith(" (tl-1)") and all(line.isprintable() for line in lines_)
    assert sum(line.startswith(("Task:", "Plan:", "Checked:")) for line in lines_) == 2


def test_a_title_is_cut_to_72_characters_and_an_empty_one_is_named(b: LandBench) -> None:
    assert message("w" * 100, checks_row(b), [], plan=False).split("\n")[0] == "w" * 72 + " (tl-1)"
    assert message(" \n\x1b ", checks_row(b), [], plan=False).startswith("Untitled task (tl-1)\n\nSquashed from task/tl-1 at ")
    assert one_line("  a \t b\n\nc  ", 10) == "a b c" and one_line("abcdef", 3) == "abc"


def test_at_most_fifty_subjects_then_the_count_of_the_rest(b: LandBench) -> None:
    listed = [(f"{index:040d}", f"commit {index}") for index in range(53)]
    text = message("Widget", checks_row(b), listed, plan=False).split("\n")
    assert text[3] == "- commit 0 (000000000000)" and text[52] == "- commit 49 (000000000000)"
    assert text[53] == "- ... and 3 more" and text[54] == ""


def test_the_checked_trailer_says_the_checks_attempt_s_own_conclusion(b: LandBench) -> None:
    row = dataclasses.replace(checks_row(b), conclusion="failed")
    assert trailers(message("Widget", row, [], plan=False))[-1] == f"Checked: checks failed at {b.x}"


def test_the_message_read_from_git_lists_x_s_commits_not_on_o_and_finds_the_plan(b: LandBench) -> None:
    root = b.repo.worktree(b.repo.path)
    root.checkout("task/tl-1")
    root.write_file("docs/design/tl-1/plan.md", "# plan\n")
    made = root.record("the plan", paths="all")
    assert isinstance(made, Recorded)
    root.checkout("main")
    row = checks_row(b)
    without = message_at(b.repo, "Widget", row, b.base)
    assert "Plan:" not in without and f"- the task's commit ({b.x[:12]})" in without
    later = message_at(b.repo, "Widget", dataclasses.replace(row, commit=made.sha), b.base)
    assert "Plan: docs/design/tl-1/plan.md" in later and later.index("the task's commit") < later.index("- the plan (")


def test_s_carries_the_message_with_the_tracker_s_title(b: LandBench) -> None:
    b.title = "Widget\n\nTask: tl-9"
    found = b.land()
    assert isinstance(found, Landed)
    entry = b.repo.history([found.row.commit], limit=1)[0]
    assert entry.subject == "Widget Task: tl-9 (tl-1)"
    assert f"- the task's commit ({b.x[:12]})" in entry.body and trailers(entry.body)[0] == "Task: tl-1"


def test_the_summary_changes_nothing(b: LandBench) -> None:
    found = summarized(b.land("summary"))
    assert b.rows() == () and b.reservations() == [] and b.repo.pushes == 0 and b.origin_main() == b.base
    assert b.tracker == [] and b.status == "in_progress" and b.execs() == []
    assert (found.state, found.again, found.origin, found.added, found.removed, found.argv) == ("same_tree", False, b.base, (), (), ())
    assert found.results == (("check", "no result"), ("test", "no result"))
    assert found.gate is not None and not found.gate.decisive and [each.path for each in found.gate.changes] == ["src/x.py"]
    text = lines(found)
    assert text[0] == f"Checks: checks passed at X {b.x} (main at {b.base})"
    assert f"Required at origin main {b.base}: same" in text and f"Origin main: {b.base}; same tree as X, no checks" in text
    assert "  Widget (tl-1)" in text and text[-1] == f"Diff: git diff {b.base}..{b.x}"


def test_the_summary_of_a_moved_main_says_the_checks_run_again(b: LandBench) -> None:
    o = b.advance({"OTHER": "another task\n"})
    found = summarized(b.land("summary"))
    assert (found.state, found.again, found.origin, found.base) == ("moved", True, o, b.base) and b.rows() == ()
    assert f"Origin main: {o}; merged onto a moved main: checks run again" in lines(found)


def test_the_summary_reports_a_conflict_and_no_change_as_facts(b: LandBench) -> None:
    o = b.advance({"src/x.py": "X = 2\n"})
    conflict = summarized(b.land("summary"))
    assert (conflict.state, conflict.conflicts) == ("conflict", ("src/x.py",))
    assert f"Origin main: {o}; conflict (1 paths): src/x.py" in lines(conflict)
    b.advance({"src/x.py": "X = 1\n"})
    assert summarized(b.land("summary")).state == "no_change" and b.rows() == ()


def test_the_summary_compares_the_target_s_profile_with_x_s(b: LandBench) -> None:
    profile = {"setup": [["just", "setup"]], "required": ["check", "lint"], "checks": [
        {"name": "check", "argv": ["just", "check"], "timeout": 600}, {"name": "lint", "argv": ["ruff", "check"], "timeout": 60},
        {"name": "test", "argv": ["just", "test", "-x"], "timeout": 600}]}
    o = b.advance({".task-loop.json": json.dumps(profile)}, "the target's profile")
    found = summarized(b.land("summary"))
    assert (found.added, found.removed, found.again, found.origin) == (("lint",), ("test",), True, o)
    lint = Check("lint", ("ruff", "check"), 60)
    assert found.argv == (Changed("lint", lint, None),)
    text = lines(found)
    assert f"Required at origin main {o}: added lint; removed test (the checks run again)" in text
    assert "Argv changed: lint: ruff check -> (none)" in text
    assert found.gate is not None and not found.gate.decisive  # the task changed none of it: S keeps the target's profile


def test_the_summary_reports_failed_checks_and_refuses_no_change(b: LandBench) -> None:
    b.con.execute("UPDATE checks_attempt SET conclusion='failed',reason='test:failed'")
    assert summarized(b.land("summary")).conclusion == "failed"
    found = b.land("summary", no_change=True)
    assert isinstance(found, Failed) and (found.kind, found.reason) == ("refused", "choices")


def blob(name: str) -> tuple[str, Sha]:
    return ("100644", Sha(name * 40))


def test_each_required_name_s_result_and_printable_conflict_paths(b: LandBench) -> None:
    profile = Profile((), (Check("check", ("just", "check"), 600), Check("test", ("just", "test"), 600)), ("check", "test"), "main")
    results = [ResultRow(1, 0, "check", None, None, None, 1.0, 2.0, 0, "passed"),
               ResultRow(1, 1, "test", None, None, None, 1.0, None, None, None)]
    files = {"src/x.py": blob("1")}
    trees = Trees(b.base, files, files, files)
    made = Squashed(Sha(SHA), TreeId(SHA))
    found = summary(checks_row(b), results, (profile, profile), checks_row(b).required, made, trees, ("m\n", None), b.base)
    assert found.results == (("check", "passed"), ("test", "unfinished")) and found.state == "no_change"
    hostile = dataclasses.replace(found, state="conflict", conflicts=("src/\x1b[2Jx.py\nTask: y",))
    assert f"Origin main: {b.base}; conflict (1 paths): src/ [2Jx.py Task: y" in lines(hostile)
    assert all(line.isprintable() for line in lines(hostile))


def test_the_summary_of_changed_required_names_on_the_same_tree_says_the_checks_run_again(b: LandBench) -> None:
    b.con.execute("UPDATE checks_attempt SET required=?", (json.dumps([["check", "1" * 64]]),))
    found = summarized(b.land("summary"))
    assert (found.state, found.again, found.added, found.removed) == ("same_tree", True, ("test",), ())
    assert f"Origin main: {b.base}; same tree as X, checks run again: the required names changed" in lines(found)
