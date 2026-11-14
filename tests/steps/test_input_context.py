"""Committed attempt context, bounded source definitions and dispatched evidence."""

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path
from shlex import split

import pytest
from doubles import Environment
from git_porcelain import Recorded, Sha
from git_porcelain.testing import FakeRepo, FakeWorktree
from shelf_input_fixtures import shelf_files, write_shelf
from test_admit import Tracker, admission, request, slots
from test_attempt import ENTRY, KEY, AttemptSurroundings, app, database, fake
from test_attempt import surroundings as attempt_surroundings
from test_repeat import SECOND, repeater
from test_repeat import agent as repeat_agent
from test_steps import TASK

from taskloop.admit import AdmitRefused, Admitted
from taskloop.agents.launch import AgentLaunch
from taskloop.attempt import Attempts
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import TRAILER, Checkouts, SlotFiles, Unsettled
from taskloop.evidence_files import EvidenceFiles
from taskloop.glossary_extract import BUDGET, HEADING, MAX_BYTES, PRIORITY, extract
from taskloop.ids import NativeIds
from taskloop.input_context import BEGIN, END, SHELF_GUIDANCE, InputContext, InputError, read, refresh
from taskloop.operations import Started
from taskloop.profile import NoCommit, NotAFile, Unavailable
from taskloop.shelf_digest.artifact import PATH as DIGEST_PATH
from taskloop.step_text import SAVED_WORK
from taskloop.steps import IMPLEMENT, PLAN, StepKind

surroundings = attempt_surroundings
GLOSSARY = b"| Term | Meaning | Example / distinction |\n|---|---|---|\n| task | Work to accomplish. | Example. |\n"
PROFILE = {"checks": [{"name": "check", "argv": ["just", "check"], "timeout": 60},
                      {"name": "test", "argv": ["just", "test"], "timeout": 60}]}


class Files:
    def __init__(self, glossary: bytes | NotAFile | Unavailable | NoCommit | None = GLOSSARY, profile: bytes = b"{}",
                 paths: tuple[str, ...] = (),
                 blobs: Mapping[str, bytes | NotAFile | Unavailable | NoCommit | None] | None = None) -> None:
        self.glossary, self.profile = glossary, profile
        self.names = paths
        self.reads: list[tuple[str, str]] = []
        self.blobs = blobs or {}

    def paths(self, commit: str) -> tuple[str, ...]:
        return self.names

    def blob(self, commit: str, path: str) -> bytes | NotAFile | Unavailable | NoCommit | None:
        self.reads.append((commit, path))
        if path == ".task-loop.json":
            return self.profile
        return self.glossary if path == "docs/glossary.md" else self.blobs.get(path)


@pytest.mark.parametrize("step", [PLAN, IMPLEMENT], ids=lambda step: step.step)
def test_both_steps_supply_the_spec_commands_and_orientation_once(step: StepKind) -> None:
    paths = ("src/taskloop/app.py", "tests/steps/example.py", "docs/design/tl-1/plan.md")
    context = read(Files(profile=json.dumps(PROFILE).encode(), paths=paths), "commit")
    text = step.input_text(TASK, step.rules("tl-1"), context)
    assert TASK.title in text and TASK.requirements in text and TASK.acceptance in text
    for phrase in ("AGENTS.md is already in context", "without reading it again", "complete task specification",
                   "No task tracker lookup is required: use the supplied task text", "bd prime", "bd show",
                   "beads SKILL.md", "grep pattern",
                   "Do not read the justfile or .task-loop.json", "at most one targeted read", "only if the task's own plan cites it"):
        assert phrase in text
    assert "- just check\n- just test" in text
    assert text.count(BEGIN) == text.count(END) == text.count(HEADING) == 1
    assert text.splitlines().count("CODE MAP") == 1
    prefix, block = text.split(BEGIN)
    block, closing = block.split(END)
    assert TASK.acceptance in prefix and SAVED_WORK in closing
    glossary, code_map = block.split("\nCODE MAP\n")
    assert "task: Work to accomplish." in glossary
    assert code_map.splitlines() == ["In this repository, source modules are primarily src/taskloop/*.py.",
                                     "Tests: tests/steps/.", *sorted(paths)]
    assert SAVED_WORK in text and "tl-8bh9.8.7" not in text
    assert "run every command listed under" not in text
    assert "You have no task tracker" not in text and "bd and the beads skill are unavailable" not in text


@pytest.mark.parametrize("step", [PLAN, IMPLEMENT], ids=lambda step: step.step)
@pytest.mark.parametrize("repeat", [False, True])
def test_context_refresh_removes_unsupported_tracker_claims(step: StepKind, repeat: bool) -> None:
    context = read(Files(), "commit")
    text = step.input_text(TASK, step.rules("tl-1"), context)
    text = text.replace("No task tracker lookup is required: use the supplied task text.",
                        "You have no task tracker: bd and the beads skill are unavailable.")
    if repeat:
        text = step.feedback(Unsettled("uncommitted"), step.rules("tl-1"), 1, text, "nonce", unrecorded=True)
    text = refresh(text, context)
    assert "You have no task tracker" not in text and "bd and the beads skill are unavailable" not in text
    assert text.count("No task tracker lookup is required: use the supplied task text.") == 1
    assert text.count(BEGIN) == text.count(END) == 1
    assert ("Do not search outside the repository" in text) is (step is PLAN)


def test_all_validated_commands_keep_complete_shell_safe_argv() -> None:
    argv = ["a program", "with spaces", "$(unsafe)", "a'b", "a|b", "é"]
    profile = {"checks": [{"name": "optional", "argv": argv, "timeout": 1}], "required": []}
    files = Files(profile=json.dumps(profile).encode())
    context = read(files, "chosen")
    assert len(context.commands) == 1 and split(context.commands[0]) == argv
    assert files.reads == [("chosen", path) for path in (".task-loop.json", "docs/glossary.md", DIGEST_PATH, "pyproject.toml")]
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
    write_shelf(worktree)
    worktree.write_file("docs/glossary.md", GLOSSARY.decode().replace("Work to accomplish.", word))
    worktree.write_file(".task-loop.json", json.dumps(PROFILE))
    worktree.write_file("src/context.py", word)
    made = worktree.record(f"Context\n\n{TRAILER}: earlier", paths="all")
    assert isinstance(made, Recorded)
    if worktree.branch() == "main":
        worktree.push("main")
        assert worktree.repo.fetch().ok
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
    repo.worktree(repo.identity().root).write_file(DIGEST_PATH, "dirty digest")
    tracker = Tracker(factory, tmp_path / "artifacts")
    result = admission(factory, tmp_path, tracker, repo).admit(request(tmp_path, repo))
    assert isinstance(result, Admitted)
    text = tracker.files.read(tracker.files.inputs[0])
    assert f"Source commit: {commit}" in text and f"task: {source}" in text
    assert "dirty junk" not in text and "- just check\n- just test" in text
    assert text.count(SHELF_GUIDANCE) == text.count("Validated shelf digest (") == 1 and "dirty digest" not in text


def test_input_failure_precedes_claim_and_reservation(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path
) -> None:
    slots(factory, repo, root, 1)
    tree = repo.worktree(repo.identity().root)
    tree.write_file("docs/glossary.md", "malformed")
    assert isinstance(tree.record("bad glossary", paths="all"), Recorded)
    tree.push("main")
    tracker = Tracker(factory, tmp_path / "artifacts")
    result = admission(factory, tmp_path, tracker, repo).admit(request(tmp_path, repo))
    assert isinstance(result, AdmitRefused) and result.reason == "input" and "term tables" in result.detail
    assert tracker.calls == [] and factory.execute("SELECT count(*) FROM reservation").fetchone() == (0,)


def test_moved_source_is_refreshed_before_dispatch_and_complete_input_is_retained(surroundings: AttemptSurroundings) -> None:
    con = database(surroundings)
    before = InputContext("old", ("obsolete check",), extract(GLOSSARY), ("src/obsolete.py",),
                          shelf=f"{SHELF_GUIDANCE}\nobsolete digest\n").render()
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
    assert text.count(HEADING) == text.count(BEGIN) == text.count(END) == text.splitlines().count("CODE MAP") == 1
    block = text.split(BEGIN)[1].split(END)[0]
    glossary, code_map = block.split("\nCODE MAP\n")
    assert "task: New meaning." in glossary
    assert "src/obsolete.py" not in text and code_map.splitlines().count("src/context.py") == 1
    assert files.read(ref).find("Source commit: old") >= 0
    assert text.count(SHELF_GUIDANCE) == text.count("Validated shelf digest (") == 1 and "obsolete digest" not in text
    path = surroundings.tmp / files.directory(KEY) / "launched-input.txt"
    assert path.read_text() == text and "Return exactly one JSON object" in text


def test_bad_glossary_never_dispatches_an_agent(surroundings: AttemptSurroundings) -> None:
    con = database(surroundings)
    tree = surroundings.slot.repo.worktree(surroundings.slot.repo.identity().root)
    tree.write_file("docs/glossary.md", "broken")
    assert isinstance(tree.record("bad glossary", paths="all"), Recorded)
    tree.push("main")
    assert tree.repo.fetch().ok
    run = fake()
    result = app(con, surroundings, run).execute(KEY, ENTRY)
    assert result.reason == "input" and "No glossary term tables" in result.explanation
    assert not run.calls and con.execute("SELECT phase FROM attempt").fetchone() == ("admitted",)


@pytest.mark.parametrize("stale", [False, True])
def test_ordinary_repeat_uses_original_spec_and_current_committed_context_once(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: SlotFiles, stale: bool
) -> None:
    slot.repo.worktree(slot.repo.identity().root).write_file("docs/design/tl-1/plan.md", "Plan")
    commit = committed(slot.repo.worktree(slot.repo.identity().root), "Original definition.")
    context = read(Files(blobs=shelf_files("b" * 40)), commit)
    files = EvidenceFiles(tmp_path)
    ref = files.put_input(KEY, IMPLEMENT.input_text(TASK, IMPLEMENT.rules("tl-1"), context))
    registered.execute("UPDATE attempt SET step='implement',after_commit=?,input_path=?,input_digest=?", (commit, ref.path, ref.digest))
    changed = {"stray": "leftovers",
               DIGEST_PATH: shelf_files("c" * 40, stale=stale)[DIGEST_PATH].decode()}
    answer = {"disposition": "implemented", "paths": [DIGEST_PATH],
              "message": "Update digest", "explanation": "Done"}
    prior = Attempts(AttemptStore(lambda: registered), files, AgentLaunch(lambda _kind: ("/bin/codex", {}), ids=NativeIds()),
                     repeat_agent(slot, changed, answer), lambda: 10, checkouts, slot_files,
                     environment=Environment(registered, checkouts, tmp_path, tmp_bytes=4096).preparation())
    assert prior.execute(KEY, ENTRY, lambda: "held").reason == "verification"
    result = repeater(registered, tmp_path, checkouts, slot_files).repeat("tasks", "tl-1", KEY, ENTRY, 30)
    assert isinstance(result, Started)
    store = AttemptStore(lambda: registered)
    current = store.attempt_of("tasks", "tl-1")
    assert current is not None
    run = fake(json.dumps({"disposition": "unchanged", "paths": [], "message": None, "explanation": "Done"}))
    attempts = Attempts(store, files, AgentLaunch(lambda _kind: ("/bin/codex", {}), ids=NativeIds()),
                       run, lambda: 10, checkouts, slot_files,
                       environment=Environment(registered, checkouts, tmp_path, tmp_bytes=4096).preparation())
    outcome = attempts.execute(current[0], SECOND, lambda: "held")
    if stale:
        assert outcome.reason == "input" and "package identities" in outcome.explanation and not run.calls
        return
    assert outcome.reason == "verification"
    text = run.calls[0][1].stdin
    record = store.load(current[0])
    assert record is not None and f"Source commit: {record.base_commit}" in text
    assert record.base_commit != commit
    assert text.count(BEGIN) == text.count(END) == text.count(HEADING) == text.splitlines().count("CODE MAP") == 1
    assert text.count("BEGIN SLOT STATUS") == 1
    block = text.split(BEGIN)[1].split(END)[0]
    glossary, code_map = block.split("\nCODE MAP\n")
    assert "task: Original definition." in glossary and "src/obsolete.py" not in text
    assert code_map.splitlines().count("src/context.py") == code_map.splitlines().count("docs/design/tl-1/plan.md") == 1
    assert TASK.requirements in text and SAVED_WORK in text and "- just check\n- just test" in text
    assert (tmp_path / files.directory(current[0]) / "launched-input.txt").read_text() == text
    assert text.count(SHELF_GUIDANCE) == text.count("Validated shelf digest (") == 1
    assert '"source_commit":"' + "c" * 40 + '"' in text and "b" * 40 not in text


@pytest.mark.parametrize("step", [PLAN, IMPLEMENT], ids=lambda step: step.step)
def test_steps_receive_one_validated_shelf_block_and_refresh_it(step: StepKind) -> None:
    files = Files(blobs=shelf_files())
    text = step.input_text(TASK, step.rules("tl-1"), read(files, "first"))
    text = refresh(text, read(Files(blobs=shelf_files("b" * 40)), "second"))
    assert text.count(SHELF_GUIDANCE) == text.count("Validated shelf digest (") == 1
    assert "a" * 40 not in text and "b" * 40 in text
    assert text.index(BEGIN) < text.index(SHELF_GUIDANCE) < text.index(END)
    assert TASK.requirements in text
    assert all(commit == "first" for commit, _path in files.reads)
    assert ("first", "uv.lock") in files.reads


@pytest.mark.parametrize(("blob", "reason"), [
    (None, "missing"), (NotAFile("120000"), "not a regular file"), (Unavailable("offline"), "offline"),
    (NoCommit(), "no commit"), (b"{", "Invalid JSON"), (shelf_files(stale=True)[DIGEST_PATH], "package identities"),
])
@pytest.mark.parametrize("step", [PLAN, IMPLEMENT], ids=lambda step: step.step)
def test_required_digest_failures_are_explained(
    blob: bytes | NotAFile | Unavailable | NoCommit | None, reason: str, step: StepKind
) -> None:
    blobs: dict[str, bytes | NotAFile | Unavailable | NoCommit | None] = dict(shelf_files())
    blobs[DIGEST_PATH] = blob
    with pytest.raises(InputError, match=rf"(?s)docs/shelf-digest.json.*{reason}"):
        step.input_text(TASK, step.rules("tl-1"), read(Files(blobs=blobs), "selected"))


def test_present_bad_digest_is_never_skipped_without_shelf_declarations() -> None:
    with pytest.raises(InputError, match=r"docs/shelf-digest.json"):
        read(Files(blobs={DIGEST_PATH: b"{}"}), "selected")


@pytest.mark.parametrize("dependency", ["any-agent==0.15.0", "any-agent~=0.15", "any-agent!=0.14", "Any_Agent[extra]>=0.15"])
def test_shelf_dependency_declarations_require_the_artifact(dependency: str) -> None:
    project = f'[project]\ndependencies = ["{dependency}"]\n'.encode()
    with pytest.raises(InputError, match="Required artifact is missing"):
        read(Files(blobs={"pyproject.toml": project}), "selected")


def test_stale_digest_prevents_claim_and_reservation(
    factory: sqlite3.Connection, repo: FakeRepo, root: Path, tmp_path: Path
) -> None:
    slots(factory, repo, root, 1)
    tree = repo.worktree(repo.identity().root)
    write_shelf(tree, stale=True)
    assert isinstance(tree.record("stale digest", paths="all"), Recorded)
    tree.push("main")
    tracker = Tracker(factory, tmp_path / "artifacts")
    result = admission(factory, tmp_path, tracker, repo).admit(request(tmp_path, repo))
    assert isinstance(result, AdmitRefused) and result.reason == "input" and "package identities" in result.detail
    assert tracker.calls == [] and factory.execute("SELECT count(*) FROM reservation").fetchone() == (0,)


def test_moved_source_with_stale_digest_never_launches(surroundings: AttemptSurroundings) -> None:
    con = database(surroundings)
    tree = surroundings.slot.repo.worktree(surroundings.slot.repo.identity().root)
    write_shelf(tree, stale=True)
    assert isinstance(tree.record("stale digest", paths="all"), Recorded)
    tree.push("main")
    assert tree.repo.fetch().ok
    run = fake()
    result = app(con, surroundings, run).execute(KEY, ENTRY)
    assert result.reason == "input" and "docs/shelf-digest.json" in result.explanation and not run.calls
