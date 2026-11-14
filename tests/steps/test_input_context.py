"""Committed attempt context, bounded source definitions and dispatched evidence."""

import json
import sqlite3
from pathlib import Path
from shlex import split

import pytest
from git_porcelain import Recorded, Sha
from git_porcelain.testing import FakeRepo, FakeWorktree
from test_admit import Tracker, admission, request, slots
from test_attempt import ENTRY, KEY, AttemptSurroundings, app, database, fake
from test_attempt import surroundings as attempt_surroundings
from test_repeat import SECOND, captured, repeater
from test_steps import TASK

from taskloop.admit import AdmitRefused, Admitted
from taskloop.agents.launch import AgentLaunch
from taskloop.attempt import Attempts
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import TRAILER, Checkouts, SlotFiles
from taskloop.evidence_files import EvidenceFiles
from taskloop.glossary_extract import BUDGET, HEADING, MAX_BYTES, PRIORITY, extract
from taskloop.input_context import BEGIN, END, InputContext, InputError, read
from taskloop.operations import Started
from taskloop.profile import NoCommit, NotAFile, Unavailable
from taskloop.step_text import SAVED_WORK
from taskloop.steps import IMPLEMENT, PLAN, StepKind

surroundings = attempt_surroundings
GLOSSARY = b"| Term | Meaning | Example / distinction |\n|---|---|---|\n| task | Work to accomplish. | Example. |\n"
PROFILE = {"checks": [{"name": "check", "argv": ["just", "check"], "timeout": 60},
                      {"name": "test", "argv": ["just", "test"], "timeout": 60}]}


class Files:
    def __init__(self, glossary: bytes | NotAFile | Unavailable | NoCommit | None = GLOSSARY, profile: bytes = b"{}") -> None:
        self.glossary, self.profile = glossary, profile
        self.reads: list[tuple[str, str]] = []

    def blob(self, commit: str, path: str) -> bytes | NotAFile | Unavailable | NoCommit | None:
        self.reads.append((commit, path))
        return self.profile if path == ".task-loop.json" else self.glossary


@pytest.mark.parametrize("step", [PLAN, IMPLEMENT], ids=lambda step: step.step)
def test_both_steps_supply_the_spec_commands_and_orientation_once(step: StepKind) -> None:
    context = read(Files(profile=json.dumps(PROFILE).encode()), "commit")
    text = step.input_text(TASK, step.rules("tl-1"), context)
    assert TASK.title in text and TASK.requirements in text and TASK.acceptance in text
    for phrase in ("AGENTS.md is already in context", "without reading it again", "complete task specification",
                   "bd and the beads skill are unavailable", "bd prime", "bd show", "beads SKILL.md", "grep pattern",
                   "Do not read the justfile or .task-loop.json", "at most one targeted read", "only if the task's own plan cites it"):
        assert phrase in text
    assert "- just check\n- just test" in text
    assert text.count(BEGIN) == text.count(END) == text.count(HEADING) == 1
    assert SAVED_WORK in text and "tl-8bh9.8.7" not in text
    assert "run every command listed under" not in text


def test_all_validated_commands_keep_complete_shell_safe_argv() -> None:
    argv = ["a program", "with spaces", "$(unsafe)", "a'b", "a|b", "é"]
    profile = {"checks": [{"name": "optional", "argv": argv, "timeout": 1}], "required": []}
    files = Files(profile=json.dumps(profile).encode())
    context = read(files, "chosen")
    assert len(context.commands) == 1 and split(context.commands[0]) == argv
    assert files.reads == [("chosen", ".task-loop.json"), ("chosen", "docs/glossary.md")]
    with pytest.raises(InputError, match=r"Profile.*must name a program"):
        read(Files(profile=b'{"checks":[{"name":"bad","argv":[],"timeout":1}]}'), "chosen")


def test_source_definitions_change_but_examples_do_not() -> None:
    first = extract(GLOSSARY)
    assert extract(GLOSSARY.replace(b"Example.", b"Another example.")) == first
    assert extract(GLOSSARY.replace(b"Work to accomplish.", b"Changed definition.")) != first
    assert "Example." not in first and "task: Work to accomplish." in first


def test_real_glossary_keeps_every_priority_term_within_the_byte_budget() -> None:
    glossary = Path(__file__).resolve().parents[2] / "docs/glossary.md"
    text = extract(glossary.read_bytes())
    assert len(text.encode()) <= BUDGET
    for term in PRIORITY:
        assert f"\n{term}: " in text
    assert "partial" in text.lower() and "docs/glossary.md" in text


def test_tables_keep_whole_rows_skip_oversized_definitions_and_handle_code_pipes() -> None:
    data = GLOSSARY + ("| huge | " + "é" * BUDGET + " | Example |\n").encode()
    data += b"| pipe | Use `x|y` and a\\|b, or ``a`|b``. | ignore |\n"
    data += b"\n| Command | Result |\n|---|---|\n| ignored | ignored |\n"
    text = extract(data)
    assert "huge:" not in text and "pipe: Use `x|y` and a\\|b, or ``a`|b``." in text
    assert "ignored" not in text and len(text.encode()) <= BUDGET


@pytest.mark.parametrize(("blob", "reason"), [
    (NotAFile("120000"), "not a regular file"), (Unavailable("read failed"), "read failed"),
    (NoCommit(), "names no commit"), (b"\xff", "utf-8"), (b"not a table", "No glossary term tables"),
    (GLOSSARY.replace(b"|---|---|---|", b"|---|bad|---|"), "separator"),
    (GLOSSARY + b"| missing | column |\n", "row"), (b"x" * (MAX_BYTES + 1), "exceeds"),
])
def test_present_glossary_failures_are_explained(blob, reason: str) -> None:
    with pytest.raises(InputError, match=reason):
        read(Files(glossary=blob), "chosen")


def test_absent_glossary_is_truthful() -> None:
    context = read(Files(glossary=None), "chosen")
    assert "No docs/glossary.md exists" in context.glossary
    assert "task:" not in context.glossary and "consult" not in context.glossary


def committed(worktree: FakeWorktree, word: str) -> str:
    worktree.write_file("docs/glossary.md", GLOSSARY.decode().replace("Work to accomplish.", word))
    worktree.write_file(".task-loop.json", json.dumps(PROFILE))
    made = worktree.record(f"Context\n\n{TRAILER}: earlier", paths="all")
    assert isinstance(made, Recorded)
    return made.sha


@pytest.mark.parametrize("source", ["main", "local", "remote"])
def test_admission_uses_the_selected_committed_source_not_dirty_checkout(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path, source: str
) -> None:
    slots(factory, repo, root, 1)
    tree = repo.worktree(repo.identity().root)
    if source != "main":
        tree = repo.add_worktree(tmp_path / "author", "HEAD")
        tree.checkout_new("task/tl-1")
    commit = committed(tree, source)
    if source != "main":
        if source == "remote":
            tree.push("task/tl-1")
        tree.park("HEAD")
        if source == "remote":
            repo.delete_branch("task/tl-1", expected=Sha(commit))
    repo.worktree(repo.identity().root).write_file("docs/glossary.md", "dirty junk")
    tracker = Tracker(factory, tmp_path / "artifacts")
    result = admission(factory, tmp_path, tracker, repo).admit(request(tmp_path, repo))
    assert isinstance(result, Admitted)
    text = tracker.files.read(tracker.files.inputs[0])
    assert f"Source commit: {commit}" in text and f"task: {source}" in text
    assert "dirty junk" not in text and "- just check\n- just test" in text


def test_input_failure_precedes_claim_and_reservation(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path
) -> None:
    slots(factory, repo, root, 1)
    tree = repo.worktree(repo.identity().root)
    tree.write_file("docs/glossary.md", "malformed")
    assert isinstance(tree.record("bad glossary", paths="all"), Recorded)
    tracker = Tracker(factory, tmp_path / "artifacts")
    result = admission(factory, tmp_path, tracker, repo).admit(request(tmp_path, repo))
    assert isinstance(result, AdmitRefused) and result.reason == "input" and "term tables" in result.detail
    assert tracker.calls == [] and factory.execute("SELECT count(*) FROM reservation").fetchone() == (0,)


def test_moved_source_is_refreshed_before_dispatch_and_complete_input_is_retained(surroundings: AttemptSurroundings) -> None:
    con = database(surroundings)
    before = InputContext("old", ("obsolete check",), extract(GLOSSARY)).render()
    files = EvidenceFiles(surroundings.tmp)
    ref = files.put_input(KEY, f"Complete task spec\n{before}\n{SAVED_WORK}")
    con.execute("UPDATE attempt SET input_path=?, input_digest=?", (ref.path, ref.digest))
    # Main moves after admission, before preparation selects B.
    commit = committed(surroundings.slot.repo.worktree(surroundings.slot.repo.identity().root), "New meaning.")
    run = fake()
    result = app(con, surroundings, run).execute(KEY, ENTRY)
    assert result.reason == "verification" and len(run.calls) == 1
    text = run.calls[0][1].stdin
    assert "Complete task spec" in text and SAVED_WORK in text
    assert f"Source commit: {commit}" in text and "task: New meaning." in text and "obsolete check" not in text
    assert text.count(HEADING) == text.count(BEGIN) == 1
    assert files.read(ref).find("Source commit: old") >= 0
    path = surroundings.tmp / files.directory(KEY) / "launched-input.txt"
    assert path.read_text() == text and "Return exactly one JSON object" in text


def test_bad_glossary_never_dispatches_an_agent(surroundings: AttemptSurroundings) -> None:
    con = database(surroundings)
    tree = surroundings.slot.repo.worktree(surroundings.slot.repo.identity().root)
    tree.write_file("docs/glossary.md", "broken")
    assert isinstance(tree.record("bad glossary", paths="all"), Recorded)
    run = fake()
    result = app(con, surroundings, run).execute(KEY, ENTRY)
    assert result.reason == "input" and "No glossary term tables" in result.explanation
    assert not run.calls and con.execute("SELECT phase FROM attempt").fetchone() == ("admitted",)


def test_ordinary_repeat_uses_original_spec_and_current_committed_context_once(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: SlotFiles
) -> None:
    commit = committed(slot.repo.worktree(slot.repo.identity().root), "Original definition.")
    context = InputContext(commit, ("just check", "just test"), extract(GLOSSARY))
    files = EvidenceFiles(tmp_path)
    ref = files.put_input(KEY, PLAN.input_text(TASK, PLAN.rules("tl-1"), context))
    registered.execute("UPDATE attempt SET input_path=?,input_digest=?", (ref.path, ref.digest))
    captured(registered, tmp_path, slot, checkouts, slot_files, {"docs/design/tl-1/plan.md": "Plan", "stray": "leftovers"})
    result = repeater(registered, tmp_path, checkouts, slot_files).repeat("tasks", "tl-1", KEY, ENTRY, 30)
    assert isinstance(result, Started)
    store = AttemptStore(lambda: registered)
    current = store.attempt_of("tasks", "tl-1")
    assert current is not None
    run = fake()
    attempts = Attempts(store, files, AgentLaunch(lambda _kind: ("/bin/codex", {})), run, lambda: 10, checkouts, slot_files)
    assert attempts.execute(current[0], SECOND).reason == "verification"
    text = run.calls[0][1].stdin
    record = store.load(current[0])
    assert record is not None and f"Source commit: {record.base_commit}" in text
    assert record.base_commit != commit
    assert text.count(BEGIN) == text.count(HEADING) == 1 and text.count("BEGIN SLOT STATUS") == 1
    assert TASK.requirements in text and SAVED_WORK in text and "- just check\n- just test" in text
    assert (tmp_path / files.directory(current[0]) / "launched-input.txt").read_text() == text
