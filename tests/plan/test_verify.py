"""Commit, check clean, then judge: the factory commits the paths the agent listed, the tree must then be clean, and one
verdict over (B, X, the one-step chain, the plan blob) is stored once; slot state and unknowns store nothing. Real SQLite,
the owning agent fake, the semantic Git fake and the fake slot file port; the 'agent' only writes files in the slot."""

import dataclasses
import json
import sqlite3
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Literal, Protocol, get_args

import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome, Summary
from any_agent.procs import Worker
from any_agent.testing import FakeRun
from git_porcelain import Dirty, Recorded, Repo, Tree
from git_porcelain.api import RecordResult
from git_porcelain.testing import FakeRepo, FakeWorktree
from sqlite_store import Store

from taskloop.attempt_entry import shown
from taskloop.composition import open_plan_verifier
from taskloop.plan import Execution, PlanAttempts
from taskloop.plan_files import PlanFiles
from taskloop.plan_schema import SCHEMA
from taskloop.plan_store import PlanStore, StoreRefused
from taskloop.plan_types import (
    RULES,
    AttemptKey,
    Checkouts,
    FileEntry,
    FileRef,
    NotApplicable,
    Rejected,
    Rule,
    SlotFiles,
    StageRules,
    StepAttempt,
    StoredExecution,
    Unsettled,
    Verified,
    VerifyRefused,
    VerifyResult,
    VerifyUnavailable,
)
from taskloop.plan_verifier import PlanVerifier
from taskloop.plan_verify import judge

KEY = AttemptKey("attempt", "dispatch", 1)
ENTRY = (7, "entry-start", "boot")
WORKER = Worker(pid=42, pgid=42, start="native-start", boot="boot")
P = "docs/design/tl-1/plan.md"
D = "docs/design/tl-1/"
NOTE = D + "note.md"
PLAN = {"disposition": "planned", "plan_path": P, "paths": [P], "message": "Plan tl-1", "explanation": "Plan written"}
UNCHANGED = {"disposition": "unchanged", "plan_path": P, "paths": [], "message": None, "explanation": "Still valid"}
TRAILER = "Task-Loop-Attempt: attempt"
type Files = Mapping[str, str | bytes]


class FakeSlotFiles(SlotFiles, Protocol):
    """The conftest's fake slot file port, as these tests use it: `entries` and `contents` override any path."""

    entries: dict[Path, FileEntry | None]
    contents: dict[Path, bytes]
    resolved: dict[Path, Path | None]


type After = Callable[[FakeWorktree, FakeSlotFiles], object]


def head(slot: FakeWorktree) -> str:
    found = next(worktree.head for worktree in slot.repo.worktrees() if worktree.path == slot.path)
    assert found is not None
    return found


def write(slot: FakeWorktree, files: Files) -> None:
    for path, text in files.items():
        slot.write_file(path, text)


def commit(slot: FakeWorktree, files: Files, message: str = "step") -> str:
    """A commit made outside the stage: the person's before dispatch, or a crash leftover after it."""
    write(slot, files)
    assert isinstance(slot.record(message, paths="all"), Recorded)
    return head(slot)


def agent(slot: FakeWorktree, files: Files, answer: Mapping[str, object] = PLAN, rc: int = 0) -> Execution:
    """The run: the 'agent' writes files in the slot (never Git), then answers."""

    def call(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        write(slot, files)
        text = json.dumps(answer)
        return FakeRun(RunOutcome(rc=rc, worker=WORKER, summary=Summary(text=text, rc=rc, stands=True)))(harness, spec, timeout, hooks)

    return call


def gone(_worker: Worker) -> bool:
    return True


class Counted:
    def __init__(self, checkouts: Checkouts) -> None:
        self.checkouts, self.opens = checkouts, 0

    def __call__(self, path: Path) -> Repo:
        self.opens += 1
        return self.checkouts(path)


def body(con: sqlite3.Connection, tmp_path: Path, checkouts: Checkouts, files: FakeSlotFiles, run: Execution) -> PlanAttempts:
    return PlanAttempts(PlanStore(lambda: con), PlanFiles(tmp_path), lambda: ("/bin/codex", {}), run, lambda: 10, checkouts, files)


def captured(
    con: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, files: FakeSlotFiles,
    written: Files, answer: Mapping[str, object] = PLAN,
) -> None:
    assert body(con, tmp_path, checkouts, files, agent(slot, written, answer)).execute(KEY, ENTRY).reason == "verification"


def verifier(con: sqlite3.Connection, checkouts: Checkouts, files: FakeSlotFiles) -> PlanVerifier:
    return PlanVerifier(PlanStore(lambda: con), checkouts, files, gone, lambda: 20)


def stored(con: sqlite3.Connection) -> list[tuple[object, ...]]:
    return con.execute("SELECT verdict,reason,reused,observed_at FROM plan_verification").fetchall()


def plan_commit(con: sqlite3.Connection) -> object:
    return con.execute("SELECT plan_commit FROM plan_attempt").fetchone()[0]


def made(slot: FakeWorktree, base: str) -> list[tuple[str, str]]:
    """The commits on the slot beyond B: subject and body."""
    return [(entry.subject, entry.body) for entry in slot.repo.history([head(slot)], not_on=[base])]


def adopt(slot: FakeWorktree, _files: FakeSlotFiles) -> None:
    """A crash after the factory's commit, before its recording: the slot HEAD is this attempt's trailer commit."""
    slot.stage([P], literal=True)
    assert isinstance(slot.record(f"Plan tl-1\n\n{TRAILER}", paths="staged"), Recorded)


def foreign(slot: FakeWorktree, _files: FakeSlotFiles) -> None:
    commit(slot, {}, "someone else")


def trailer_commit(slot: FakeWorktree, files: FakeSlotFiles) -> None:
    """This attempt's trailer commit of a changed plan: adoptable for `planned`, never for `unchanged` (X is B)."""
    slot.write_file(P, "# Plan v2\n")
    adopt(slot, files)


def entry(path: str, found: FileEntry | None) -> After:
    def override(slot: FakeWorktree, files: FakeSlotFiles) -> None:
        files.entries[slot.path / path] = found

    return override


def contents(path: str, data: bytes) -> After:
    def override(slot: FakeWorktree, files: FakeSlotFiles) -> None:
        files.contents[slot.path / path] = data

    return override


def unregistered(slot: FakeWorktree, files: FakeSlotFiles) -> None:
    """Git forgets the slot; its pointer files stay readable (the fake port saw the slot listed at dispatch)."""
    assert files.lstat(slot.path / ".git") is not None
    slot.repo.drop_worktree(slot.path, force=True)


LOST = "unavailable:git:MissingRevision"  # B no longer resolves: permanently unknown, never a verdict
OTHER_REPO = "UPDATE reservation SET repo_id='other'; UPDATE plan_attempt SET repo_id='other'"
PLANNED = {P: "# Plan\n"}
# id, files committed before dispatch (B), files the agent writes, its answer, a change after the run, SQL, expected, commits
CASES: list[tuple[str, Files | None, Files, Mapping[str, object], After | None, str | None, str, int]] = [
    ("plan_only", None, PLANNED, PLAN, None, None, "verified", 1),
    ("plan_and_note", None, PLANNED | {NOTE: "n"}, PLAN | {"paths": [P, NOTE]}, None, None, "verified", 1),
    ("replan", PLANNED, {P: "# Plan v2\n"}, PLAN, None, None, "verified", 1),
    ("unlisted_file", None, PLANNED | {NOTE: "n"}, PLAN, None, None, "unsettled:uncommitted", 1),
    ("nothing_written", PLANNED, PLANNED, PLAN, None, None, "rejected:nothing_written", 0),
    ("unchanged", PLANNED, {}, UNCHANGED, None, None, "reused", 0),
    ("unchanged_without_plan", None, {}, UNCHANGED, None, None, "rejected:plan_missing", 0),
    ("unchanged_empty_plan", {P: "  \n"}, {}, UNCHANGED, None, None, "rejected:plan_empty", 0),
    ("unchanged_with_a_stray_file", PLANNED, {NOTE: "n"}, UNCHANGED, None, None, "unsettled:uncommitted", 0),
    ("plan_empty", None, {P: " \n\t"}, PLAN, None, None, "rejected:plan_empty", 1),
    ("plan_encoding", None, {P: b"\xff\xfe plan"}, PLAN, None, None, "rejected:plan_encoding", 1),
    ("plan_at_cap", None, {P: "a" * (1 << 20)}, PLAN, None, None, "verified", 1),
    ("plan_over_cap", None, {P: "a" * ((1 << 20) + 1)}, PLAN, None, None, "unsettled:unsafe", 0),
    ("plan_missing", None, {NOTE: "n"}, PLAN | {"paths": [P, NOTE]}, None, None, "unsettled:unsafe", 0),
    ("executable", None, PLANNED, PLAN, entry(P, FileEntry("file", 7, True)), None, "unsettled:unsafe", 0),
    ("symlinked_root", None, PLANNED, PLAN, entry(D.rstrip("/"), FileEntry("link", 9, False)), None, "unsettled:unsafe", 0),
    ("ignored", {".gitignore": "*.log\n"}, PLANNED | {D + "x.log": "x"}, PLAN, None, None, "unsettled:ignored", 0),
    ("listed_path_ignored", {".gitignore": "*.md\n"}, PLANNED, PLAN, None, None, "unsettled:ignored", 0),
    ("gitattributes_at_the_top", None, PLANNED | {".gitattributes": "* filter=x\n"}, PLAN, None, None, "unsettled:unsafe", 0),
    ("gitmodules_on_the_way", None, PLANNED | {"docs/.gitmodules": "x"}, PLAN, None, None, "unsettled:unsafe", 0),
    ("github_folder_on_the_way", None, PLANNED | {"docs/.github/x.yml": "x"}, PLAN, None, None, "unsettled:unsafe", 0),
    ("gitignore_under_the_root", None, PLANNED | {D + "sub/.gitignore": "x"}, PLAN, None, None, "unsettled:unsafe", 0),
    ("hfs_ignorable_gitattributes", None, PLANNED | {"docs/.g\u200cit\ufeffattributes": "x"}, PLAN, None, None, "unsettled:unsafe", 0),
    ("git_file_elsewhere", None, PLANNED | {"src/.gitignore": "x"}, PLAN, None, None, "unsettled:uncommitted", 1),
    ("adopted_after_a_crash", None, PLANNED, PLAN, adopt, None, "verified", 1),
    ("foreign_commit", None, PLANNED, PLAN, foreign, None, "unsettled:head_moved", 1),
    ("unchanged_head_moved", PLANNED, {}, UNCHANGED, lambda slot, _files: commit(slot, {"README": "two"}), None, "unsettled:head_moved", 1),
    ("unchanged_never_adopts", PLANNED, {}, UNCHANGED, trailer_commit, None, "unsettled:head_moved", 1),
    ("branch", None, PLANNED, PLAN, lambda slot, _files: slot.checkout_new("task/tl-1"), None, "unsettled:branch", 0),
    ("index_locked", None, PLANNED, PLAN, lambda slot, _files: slot.lock_index(), None, "unavailable:git:IndexLocked", 0),
    ("lost_base", None, PLANNED, PLAN, None, "UPDATE plan_attempt SET base_commit='f' || substr(base_commit, 2)", LOST, 0),
    ("dropped", None, PLANNED, PLAN, lambda slot, _files: slot.repo.drop_checkout(slot.path), None, "unavailable:git:NotARepo", 0),
    ("not_listed", None, PLANNED, PLAN, unregistered, None, "unavailable:not_listed", 0),
    ("other_repo", None, PLANNED, PLAN, None, OTHER_REPO, "unavailable:repo", 0),
]


@pytest.mark.parametrize(
    ("before", "written", "answer", "after", "sql", "expected", "commits"), [case[1:] for case in CASES], ids=[case[0] for case in CASES]
)
def test_the_stage_commit_and_verdict_table(
    registered: sqlite3.Connection,
    slot: FakeWorktree,
    tmp_path: Path,
    checkouts: Checkouts,
    slot_files: FakeSlotFiles,
    before: Files | None,
    written: Files,
    answer: Mapping[str, object],
    after: After | None,
    sql: str | None,
    expected: str,
    commits: int,
) -> None:
    if before is not None:
        commit(slot, before)  # before dispatch: B is this commit
    base = head(slot)
    captured(registered, tmp_path, slot, checkouts, slot_files, written, answer)
    if after is not None:
        after(slot, slot_files)
    for statement in (sql or "").split(";"):
        if statement.strip():
            registered.execute(statement)
    result = verifier(registered, checkouts, slot_files).verify(KEY)
    assert shown(result) == expected
    final = expected.startswith(("verified", "reused", "rejected"))
    assert len(stored(registered)) == (1 if final else 0)  # slot state and unknowns are never stored
    if expected != "unavailable:not_listed":
        assert len(made(slot, base)) == commits
        assert all(body == TRAILER for subject, body in made(slot, base) if subject == "Plan tl-1")
    collected = body(registered, tmp_path, checkouts, slot_files, agent(slot, {})).collect(KEY)
    assert (collected.status, collected.reason) == (("collected", expected) if final else ("pending", "verification"))


def test_one_factory_commit_with_the_agents_message_and_the_trailer_is_recorded_once(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: FakeSlotFiles
) -> None:
    base = head(slot)
    captured(registered, tmp_path, slot, checkouts, slot_files, PLANNED | {NOTE: "n"}, PLAN | {"paths": [P, NOTE]})
    assert isinstance(verifier(registered, checkouts, slot_files).verify(KEY), Verified)
    assert made(slot, base) == [("Plan tl-1", TRAILER)] and plan_commit(registered) == head(slot)
    assert slot.dirty().raw is False


def test_leftovers_are_listed_fresh_and_a_tidied_slot_then_verifies(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: FakeSlotFiles
) -> None:
    captured(registered, tmp_path, slot, checkouts, slot_files, PLANNED | {NOTE: "n", "scratch.txt": "s"})
    check = verifier(registered, checkouts, slot_files)
    assert check.verify(KEY) == Unsettled("uncommitted", ("?? docs/design/tl-1/note.md", "?? scratch.txt"))
    x = plan_commit(registered)
    assert x == head(slot) and check.leftovers(KEY) == check.verify(KEY)  # X stays recorded; the listing is read again
    slot.remove_file(NOTE)
    slot.remove_file("scratch.txt")
    assert check.leftovers(KEY) is None and isinstance(check.verify(KEY), Verified) and plan_commit(registered) == x


def test_the_listing_is_bounded(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: FakeSlotFiles
) -> None:
    captured(registered, tmp_path, slot, checkouts, slot_files, PLANNED | {f"stray-{n:02}": "s" for n in range(53)})
    result = verifier(registered, checkouts, slot_files).verify(KEY)
    assert isinstance(result, Unsettled) and len(result.listing) == 51 and result.listing[-1] == "+3 more"


def test_unchanged_records_b_only_after_the_tree_is_clean(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: FakeSlotFiles
) -> None:
    base = commit(slot, PLANNED)
    captured(registered, tmp_path, slot, checkouts, slot_files, {NOTE: "n"}, UNCHANGED)
    check = verifier(registered, checkouts, slot_files)
    assert shown(check.verify(KEY)) == "unsettled:uncommitted" and plan_commit(registered) is None
    slot.remove_file(NOTE)
    tree = slot.repo.tree(base)
    assert tree is not None and check.verify(KEY) == Verified(tree.files[P][1], reused=True)
    assert plan_commit(registered) == base


@pytest.mark.parametrize(
    "rewrite",
    [
        entry(".git", FileEntry("dir", 0, False)),
        entry(".git", FileEntry("link", 30, False)),
        entry(".git", FileEntry("other", 0, False)),
        contents(".git", b"gitdir: /elsewhere/.git/worktrees/s1\n"),
        contents(".git", b"x" * 5000),
    ],
    ids=["directory", "symlink", "fifo", "other_gitdir", "oversize"],
)
def test_a_rewritten_slot_pointer_is_redirected_before_any_git_call(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: FakeSlotFiles, rewrite: After
) -> None:
    captured(registered, tmp_path, slot, checkouts, slot_files, PLANNED)
    rewrite(slot, slot_files)
    counted = Counted(checkouts)
    assert verifier(registered, counted, slot_files).verify(KEY) == Unsettled("redirected") and counted.opens == 0
    assert stored(registered) == [] and plan_commit(registered) is None


@pytest.mark.parametrize("target", ["slot_path", "gitdir_in_slot", "common_in_slot", "unresolvable"])
def test_a_pointer_is_judged_as_git_resolves_it(
    registered: sqlite3.Connection, slot: FakeWorktree, repo: FakeRepo, tmp_path: Path, checkouts: Checkouts,
    slot_files: FakeSlotFiles, target: str,
) -> None:
    """A symlinked slot path, or a pointer whose Git directory or common directory resolves inside the slot (the agent's
    own symlinks), is `redirected` before any Git call, though every name is right lexically."""
    captured(registered, tmp_path, slot, checkouts, slot_files, PLANNED)
    gitdir = repo.identity().common_dir / "worktrees" / "s1"
    inside = slot.path / "repo/.git/worktrees/s1"
    redirects = {
        "slot_path": {slot.path: tmp_path / "elsewhere"},
        "gitdir_in_slot": {gitdir: inside},
        "common_in_slot": {gitdir / "../..": slot.path / "repo/.git"},
        "unresolvable": {gitdir: None},
    }
    slot_files.resolved.update(redirects[target])
    counted = Counted(checkouts)
    assert verifier(registered, counted, slot_files).verify(KEY) == Unsettled("redirected") and counted.opens == 0
    assert made(slot, head(slot)) == [] and plan_commit(registered) is None


def test_a_wrong_back_pointer_is_redirected(
    registered: sqlite3.Connection, slot: FakeWorktree, repo: FakeRepo, tmp_path: Path, checkouts: Checkouts, slot_files: FakeSlotFiles
) -> None:
    captured(registered, tmp_path, slot, checkouts, slot_files, PLANNED)
    slot_files.contents[repo.identity().common_dir / "worktrees" / "s1" / "gitdir"] = b"/elsewhere/.git\n"
    counted = Counted(checkouts)
    assert verifier(registered, counted, slot_files).verify(KEY) == Unsettled("redirected") and counted.opens == 0


def test_a_rewritten_pointer_refuses_dispatch(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: FakeSlotFiles
) -> None:
    slot_files.entries[slot.path / ".git"] = FileEntry("dir", 0, False)
    result = body(registered, tmp_path, checkouts, slot_files, agent(slot, PLANNED)).execute(KEY, ENTRY)
    assert (result.status, result.reason) == ("refused", "slot_redirected")


def rules(cap: int = 1 << 20) -> StageRules:
    return StageRules(D, file_cap=cap)


def one(base: str, paths: tuple[str, ...]) -> tuple[StepAttempt, ...]:
    """Attempt 1 alone, `planned`: today's one-step chain."""
    return (StepAttempt(1, base, None, "planned", paths, FileRef("input.txt", "d")),)


@pytest.mark.parametrize(
    ("changes", "paths", "cap", "expected"),
    [
        ([PLANNED, {P: "# Plan v2\n"}], (P,), 1 << 20, Rejected("chain_length")),
        ([PLANNED | {NOTE: "n"}], (P,), 1 << 20, Rejected("paths")),
        ([PLANNED | {"src/x.py": "x"}], (P, "src/x.py"), 1 << 20, Rejected("paths")),
        ([PLANNED | {NOTE: "0123456789a"}], (P, NOTE), 10, Rejected("file_size")),
        ([PLANNED | {NOTE: "0123456789"}], (P, NOTE), 10, None),
    ],
    ids=["chain_length", "unlisted_change", "outside_root", "file_size", "at_cap"],
)
def test_judge_rules_the_verify_path_cannot_reach(
    repo: FakeRepo, slot: FakeWorktree, changes: list[Files], paths: tuple[str, ...], cap: int, expected: Rejected | None
) -> None:
    base = head(slot)
    for files in changes:
        commit(slot, files)
    found = judge(repo, repo.path, head(slot), rules(cap), one(base, paths))
    assert found == expected if expected is not None else isinstance(found, Verified)


def test_a_commit_that_does_not_descend_from_b_or_is_no_commit(repo: FakeRepo, slot: FakeWorktree) -> None:
    base = commit(slot, {"notes.txt": "x"})
    slot.checkout("HEAD^")
    assert judge(repo, repo.path, head(slot), rules(), one(base, (P,))) == Rejected("not_descendant")
    tree = slot.snapshot("HEAD").head_tree
    assert tree is not None
    for reported in ("c" * 40, tree, base[:12]):  # an abbreviation resolves to another name of a commit: never X itself
        assert judge(repo, repo.path, reported, rules(), one(base, (P,))) == Rejected("commit_absent")


@pytest.mark.parametrize("unread", ["parent", "blob"])
def test_an_empty_read_of_a_parent_or_a_listed_blob_is_unknown_never_a_verdict(
    registered: sqlite3.Connection,
    slot: FakeWorktree,
    repo: FakeRepo,
    tmp_path: Path,
    checkouts: Checkouts,
    slot_files: FakeSlotFiles,
    monkeypatch: pytest.MonkeyPatch,
    unread: str,
) -> None:
    """The library reads both with an unchecked exit code: a failed read and a root commit or a missing blob look alike."""
    captured(registered, tmp_path, slot, checkouts, slot_files, PLANNED)
    read = repo.tree

    def failing(rev: str) -> Tree | None:
        found = read(rev)
        if unread == "parent":
            return None if rev.endswith("^") else found
        return None if found is None else Tree(found.sha, lambda: found.files, lambda _path: None)

    monkeypatch.setattr(repo, "tree", failing)
    assert verifier(registered, checkouts, slot_files).verify(KEY) == VerifyUnavailable("git:Unreadable")
    assert stored(registered) == []


def test_a_stored_verdict_is_returned_again_without_any_git_read(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: FakeSlotFiles
) -> None:
    captured(registered, tmp_path, slot, checkouts, slot_files, PLANNED)
    first = verifier(registered, checkouts, slot_files).verify(KEY)
    assert isinstance(first, Verified) and not first.reused
    slot.repo.drop_checkout(slot.path)
    counted = Counted(checkouts)
    assert verifier(registered, counted, slot_files).verify(KEY) == first and counted.opens == 0
    assert stored(registered) == [("verified", None, 0, 20.0)]


@pytest.mark.parametrize(
    ("answer", "rc", "expected"),
    [
        ({"disposition": "incomplete", "plan_path": None}, 0, NotApplicable("incomplete")),
        ({"disposition": "needs_owner", "plan_path": None}, 0, NotApplicable("needs_owner")),
        ({"disposition": "other"}, 0, NotApplicable("answer:schema_invalid")),
        ({"commit": "a" * 40}, 0, NotApplicable("answer:schema_invalid")),
        ({}, 1, NotApplicable("run:worker_failed")),
    ],
    ids=["incomplete", "needs_owner", "invalid", "old_commit_key", "failed_run"],
)
def test_no_valid_staged_answer_of_a_clean_run_is_not_applicable_with_no_git_read(
    registered: sqlite3.Connection,
    slot: FakeWorktree,
    tmp_path: Path,
    checkouts: Checkouts,
    slot_files: FakeSlotFiles,
    answer: dict[str, object],
    rc: int,
    expected: object,
) -> None:
    quiet = {"paths": [], "message": None} if answer.get("disposition") in ("incomplete", "needs_owner") else {}
    run = agent(slot, PLANNED, PLAN | answer | quiet, rc)
    assert body(registered, tmp_path, checkouts, slot_files, run).execute(KEY, ENTRY).status == "collected"
    counted = Counted(checkouts)
    assert verifier(registered, counted, slot_files).verify(KEY) == expected and counted.opens == 0 and stored(registered) == []


def test_refusals_and_unknowns_before_any_git_read(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: FakeSlotFiles
) -> None:
    counted = Counted(checkouts)
    assert verifier(registered, counted, slot_files).verify(KEY) == VerifyRefused("not_captured")
    captured(registered, tmp_path, slot, checkouts, slot_files, PLANNED)
    registered.execute(
        "UPDATE plan_execution SET answer_kind='validation_pending',disposition=NULL,plan_path=NULL,commit_paths=NULL,commit_message=NULL"
    )
    assert verifier(registered, counted, slot_files).verify(KEY) == VerifyUnavailable("validation_pending")
    assert PlanVerifier(PlanStore(lambda: None), counted, slot_files, gone, lambda: 20).verify(KEY) == VerifyUnavailable("store")
    assert counted.opens == 0 and stored(registered) == []


@pytest.mark.parametrize(
    ("publication", "expected"), [("pending", VerifyUnavailable("session_pending")), ("conflict", VerifyRefused("session"))]
)
def test_an_unfinished_session_publication_is_never_verified(
    registered: sqlite3.Connection,
    slot: FakeWorktree,
    tmp_path: Path,
    checkouts: Checkouts,
    slot_files: FakeSlotFiles,
    publication: str,
    expected: object,
) -> None:
    captured(registered, tmp_path, slot, checkouts, slot_files, PLANNED)
    registered.execute("UPDATE plan_execution SET publication=?", (publication,))
    assert verifier(registered, checkouts, slot_files).verify(KEY) == expected and stored(registered) == []


def test_a_dispatched_attempt_always_has_a_base(registered: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="base_commit IS NOT NULL"):
        registered.execute("UPDATE plan_attempt SET phase='dispatching'")
    registered.execute("UPDATE plan_attempt SET phase='dispatching',base_commit=?", ("b" * 40,))
    with pytest.raises(sqlite3.IntegrityError, match="phase='captured'"):
        registered.execute("UPDATE plan_attempt SET plan_commit=?", ("c" * 40,))


def test_a_stale_reservation_refuses_and_stores_nothing(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: FakeSlotFiles
) -> None:
    captured(registered, tmp_path, slot, checkouts, slot_files, PLANNED)
    registered.execute("UPDATE reservation SET generation=2")
    assert verifier(registered, checkouts, slot_files).verify(KEY) == VerifyRefused("stale_reservation")
    assert stored(registered) == [] and made(slot, head(slot)) == []


def test_another_verifier_storing_first_is_inconsistent(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: FakeSlotFiles
) -> None:
    captured(registered, tmp_path, slot, checkouts, slot_files, PLANNED)
    store = PlanStore(lambda: registered)
    record = store.load(KEY)
    assert record is not None and record.base_commit is not None
    found = verifier(registered, checkouts, slot_files).verify(KEY)
    tree = slot.repo.tree(head(slot))
    assert tree is not None and found == Verified(tree.files[P][1])
    registered.execute("DELETE FROM plan_verification")
    assert store.verdict(record.admission, record.base_commit, head(slot), Rejected("paths"), 1) == Rejected("paths")

    class Racing(PlanStore):
        """Another verifier stored its row between this one's collect and insert."""

        def collect(self, key: AttemptKey) -> StoredExecution | None:
            found = super().collect(key)
            return None if found is None else dataclasses.replace(found, verification=None)

    assert PlanVerifier(Racing(lambda: registered), checkouts, slot_files, gone, lambda: 3).verify(KEY) == VerifyUnavailable("inconsistent")


def test_the_real_composition_opens_the_factory_database(tmp_path: Path) -> None:
    store = Store(SCHEMA)
    assert open_plan_verifier(tmp_path / "factory.db", store).verify(KEY) == VerifyRefused("not_captured")
    store.close_shared()


def test_every_rule_a_verdict_can_name_is_one_the_store_reads_back() -> None:
    assert set(RULES) == set(get_args(Rule.__value__)) and len(RULES) == len(set(RULES))
    assert "merge" not in RULES and {"nothing_written", "file_size"} <= set(RULES)


def test_the_writer_refuses_a_plan_commit_or_verdict_without_its_preconditions(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: FakeSlotFiles
) -> None:
    captured(registered, tmp_path, slot, checkouts, slot_files, PLANNED)
    store = PlanStore(lambda: registered)
    record = store.load(KEY)
    assert record is not None and record.base_commit is not None
    with pytest.raises(StoreRefused, match="changed_answer"):
        store.plan_commit(record.admission, record.base_commit)  # planned: X must differ from B
    with pytest.raises(StoreRefused, match="changed_answer"):
        store.verdict(record.admission, record.base_commit, "e" * 40, Verified("e" * 40), 1)  # no plan_commit stored yet
    assert store.plan_commit(record.admission, "e" * 40) == "e" * 40
    assert store.plan_commit(record.admission, "f" * 40) == "e" * 40  # written once: the caller sees the other value
    with pytest.raises(StoreRefused, match="changed_answer"):
        store.verdict(record.admission, record.base_commit, None, Rejected("nothing_written"), 1)  # a commit is recorded
    with pytest.raises(StoreRefused, match="changed_answer"):
        store.verdict(record.admission, record.base_commit, "e" * 40, Verified("e" * 40, reused=True), 1)  # reused needs unchanged
    assert stored(registered) == []


def flip(slot: FakeWorktree, files: FakeSlotFiles) -> None:
    files.entries[slot.path / ".git"] = FileEntry("dir", 0, False)


def test_a_pointer_rewritten_after_the_slot_read_stops_before_stage(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: FakeSlotFiles,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rewritten between the slot read and `stage` (here: during the pre-stage status read): nothing is staged."""
    base = head(slot)
    captured(registered, tmp_path, slot, checkouts, slot_files, PLANNED)
    index, read = dict(slot.state().index), FakeWorktree.dirty

    def dirty(self: FakeWorktree, base: str | None = None, *, ignored_under: Sequence[str] = ()) -> Dirty:
        if ignored_under:
            flip(slot, slot_files)
        return read(self, base, ignored_under=ignored_under)

    monkeypatch.setattr(FakeWorktree, "dirty", dirty)
    assert verifier(registered, checkouts, slot_files).verify(KEY) == Unsettled("redirected")
    assert slot.state().index == index and made(slot, base) == [] and plan_commit(registered) is None


def test_a_pointer_rewritten_during_stage_stops_before_record(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: FakeSlotFiles,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = head(slot)
    captured(registered, tmp_path, slot, checkouts, slot_files, PLANNED)
    staged = FakeWorktree.stage

    def stage(self: FakeWorktree, paths: Sequence[str], *, literal: bool = True) -> None:
        staged(self, paths, literal=literal)
        flip(slot, slot_files)

    monkeypatch.setattr(FakeWorktree, "stage", stage)
    assert verifier(registered, checkouts, slot_files).verify(KEY) == Unsettled("redirected")
    assert made(slot, base) == [] and plan_commit(registered) is None and stored(registered) == []


def test_a_verifier_racing_another_adopts_its_commit_never_nothing_written(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: FakeSlotFiles,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other verifier commits, records X and stores its verdict between this one's `stage` and `record`, so this
    `record` finds nothing to commit: HEAD is no longer B, and the trailer commit is adopted, not `nothing_written`."""
    base = head(slot)
    captured(registered, tmp_path, slot, checkouts, slot_files, PLANNED)
    recorded, raced = FakeWorktree.record, list[VerifyResult]()

    def record(self: FakeWorktree, message: str, **options: Literal["staged"] | bool) -> RecordResult:
        if not raced:
            raced.append(Unsettled("racing"))
            raced[0] = verifier(registered, checkouts, slot_files).verify(KEY)
        return recorded(self, message, paths="staged", hooks=False)

    monkeypatch.setattr(FakeWorktree, "record", record)
    found = verifier(registered, checkouts, slot_files).verify(KEY)
    assert isinstance(found, Verified) and raced == [found]
    assert made(slot, base) == [("Plan tl-1", TRAILER)] and plan_commit(registered) == head(slot)
    assert stored(registered) == [("verified", None, 0, 20.0)]


def test_no_plan_commit_is_written_once_a_verdict_is_stored(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: FakeSlotFiles
) -> None:
    captured(registered, tmp_path, slot, checkouts, slot_files, PLANNED)
    store = PlanStore(lambda: registered)
    record = store.load(KEY)
    assert record is not None and record.base_commit is not None
    nothing = Rejected("nothing_written")
    assert store.verdict(record.admission, record.base_commit, None, nothing, 1) == nothing
    with pytest.raises(StoreRefused, match="changed_answer"):
        store.plan_commit(record.admission, "e" * 40)
    assert plan_commit(registered) is None


def test_the_listing_is_safe_to_print(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: FakeSlotFiles
) -> None:
    captured(registered, tmp_path, slot, checkouts, slot_files, PLANNED | {"evil\x1b[31m\nname\x9b": "x", "x" * 400: "y"})
    result = verifier(registered, checkouts, slot_files).verify(KEY)
    assert isinstance(result, Unsettled) and result.listing[0] == "?? evil?[31m?name?"
    assert len(result.listing[1]) == 300 and result.listing[1].endswith("...")


def test_no_git_write_while_the_worker_may_still_run(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, slot_files: FakeSlotFiles
) -> None:
    base = head(slot)
    captured(registered, tmp_path, slot, checkouts, slot_files, PLANNED)
    index, seen = dict(slot.state().index), list[Worker]()

    def alive(worker: Worker) -> bool:
        seen.append(worker)
        return False

    found = PlanVerifier(PlanStore(lambda: registered), checkouts, slot_files, alive, lambda: 20).verify(KEY)
    assert found == Unsettled("worker_alive") and seen == [WORKER]
    assert slot.state().index == index and made(slot, base) == [] and plan_commit(registered) is None
    assert isinstance(verifier(registered, checkouts, slot_files).verify(KEY), Verified)  # once it is gone
