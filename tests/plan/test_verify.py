"""Plan verification: one verdict over (B, X, the chain, the plan blob), stored once; slot state and unknowns store
nothing. Real SQLite, the owning agent fake and the semantic Git fake; the 'agent' acts on the slot through Git."""

import dataclasses
import json
import sqlite3
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import get_args

import pytest
from any_agent import Harness, LaunchSpec, RunHooks, RunOutcome, Summary
from any_agent.procs import Worker
from any_agent.testing import FakeRun
from git_porcelain import Recorded, Repo, Tree
from git_porcelain.testing import FakeRepo, FakeWorktree
from sqlite_store import Store

from taskloop.attempt_entry import shown
from taskloop.composition import open_plan_verifier
from taskloop.plan import Execution, PlanAttempts, PlanVerifier
from taskloop.plan_files import PlanFiles
from taskloop.plan_schema import SCHEMA
from taskloop.plan_store import PlanStore, StoreRefused
from taskloop.plan_types import (
    RULES,
    AttemptKey,
    Checkouts,
    NotApplicable,
    Rejected,
    Rule,
    StoredExecution,
    Verified,
    VerifyRefused,
    VerifyUnavailable,
)
from taskloop.plan_verify import judge

KEY = AttemptKey("attempt", "dispatch", 1)
ENTRY = (7, "entry-start", "boot")
WORKER = Worker(pid=42, pgid=42, start="native-start", boot="boot")
P = "docs/design/tl-1/plan.md"
D = "docs/design/tl-1/"
PLAN = {"disposition": "planned", "plan_path": P, "commit": None, "explanation": "Plan committed"}
type Act = Callable[[FakeWorktree], str]
type After = Callable[[FakeWorktree], object]


def head(slot: FakeWorktree) -> str:
    found = next(worktree.head for worktree in slot.repo.worktrees() if worktree.path == slot.path)
    assert found is not None
    return found


def commit(*changes: Mapping[str, str | bytes | None]) -> Act:
    """One commit per mapping (a None value deletes the file); the act reports the last."""

    def act(slot: FakeWorktree) -> str:
        for files in changes:
            for path, text in files.items():
                if text is None:
                    slot.remove_file(path)
                else:
                    slot.write_file(path, text)
            assert isinstance(slot.record("step", paths="all"), Recorded)
        return head(slot)

    return act


def back(slot: FakeWorktree) -> str:
    """Detach the slot at the parent of B and report it."""
    slot.checkout("HEAD^")
    return head(slot)


def agent(slot: FakeWorktree, act: Act, answer: Mapping[str, object] = PLAN, rc: int = 0) -> Execution:
    """The run: the 'agent' first acts on the slot, then answers with the commit the act reports."""

    def call(harness: Harness, spec: LaunchSpec, timeout: float, hooks: RunHooks | None) -> RunOutcome:
        text = json.dumps(dict(answer) | ({"commit": act(slot)} if answer.get("disposition") == "planned" else {}))
        return FakeRun(RunOutcome(rc=rc, worker=WORKER, summary=Summary(text=text, rc=rc, stands=True)))(harness, spec, timeout, hooks)

    return call


class Counted:
    def __init__(self, checkouts: Checkouts) -> None:
        self.checkouts, self.opens = checkouts, 0

    def __call__(self, path: Path) -> Repo:
        self.opens += 1
        return self.checkouts(path)


def body(con: sqlite3.Connection, tmp_path: Path, checkouts: Checkouts, run: Execution) -> PlanAttempts:
    return PlanAttempts(PlanStore(lambda: con), PlanFiles(tmp_path), lambda: ("/bin/codex", {}), run, lambda: 10, checkouts)


def captured(con: sqlite3.Connection, tmp_path: Path, slot: FakeWorktree, checkouts: Checkouts, act: Act) -> None:
    assert body(con, tmp_path, checkouts, agent(slot, act)).execute(KEY, ENTRY).reason == "verification"


def verifier(con: sqlite3.Connection, checkouts: Checkouts) -> PlanVerifier:
    return PlanVerifier(PlanStore(lambda: con), checkouts, lambda: 20)


def stored(con: sqlite3.Connection) -> list[tuple[object, ...]]:
    return con.execute("SELECT verdict,reason,reused,observed_at FROM plan_verification").fetchall()


LOST = "unavailable:git:MissingRevision"  # B no longer resolves: permanently unknown, never a verdict
OTHER_REPO = "UPDATE reservation SET repo_id='other'; UPDATE plan_attempt SET repo_id='other'"
NINE = tuple({P: f"step {n}\n"} for n in range(9))
CASES: list[tuple[str, Act | None, Act, After | None, str | None, str]] = [
    ("one_commit", None, commit({P: "# Plan\n"}), None, None, "verified"),
    ("chain_of_three", None, commit({P: "# Plan\n"}, {D + "a.md": "a"}, {P: "# Plan v2\n"}), None, None, "verified"),
    ("reused", commit({P: "# Plan\n"}), head, None, None, "reused"),
    ("reused_without_plan", None, head, None, None, "rejected:plan_missing"),
    ("reused_empty_plan", commit({P: "  \n"}), head, None, None, "rejected:plan_empty"),
    ("not_descendant", commit({"notes.txt": "x"}), back, None, None, "rejected:not_descendant"),
    ("chain_of_eight", None, commit(*NINE[:8]), None, None, "verified"),
    ("chain_length", None, commit(*NINE), None, None, "rejected:chain_length"),
    ("extra_file", None, commit({P: "# Plan\n", "src/extra.py": "x"}), None, None, "rejected:paths"),
    ("deletion", None, commit({P: "# Plan\n", D + "old.md": "x"}, {D + "old.md": None}), None, None, "rejected:paths"),
    ("modified_away", None, commit({P: "# Plan\n", "README": "changed"}, {"README": "one"}), None, None, "rejected:paths"),
    ("git_component", None, commit({P: "# Plan\n", D + ".GIT/hooks": "x"}), None, None, "rejected:paths"),
    ("dot_dot_component", None, commit({P: "# Plan\n", D + "../escape.md": "x"}), None, None, "rejected:paths"),
    ("dot_component", None, commit({P: "# Plan\n", D + "./here.md": "x"}), None, None, "rejected:paths"),
    ("empty_component", None, commit({P: "# Plan\n", D + "sub//here.md": "x"}), None, None, "rejected:paths"),
    ("other_task", None, commit({P: "# Plan\n", "docs/design/tl-2/plan.md": "x"}), None, None, "rejected:paths"),
    ("plan_missing", None, commit({D + "notes.md": "x"}), None, None, "rejected:plan_missing"),
    ("plan_empty", None, commit({P: " \n\t"}), None, None, "rejected:plan_empty"),
    ("plan_encoding", None, commit({P: b"\xff\xfe plan"}), None, None, "rejected:plan_encoding"),
    ("plan_size", None, commit({P: "a" * ((1 << 20) + 1)}), None, None, "rejected:plan_size"),
    ("plan_at_cap", None, commit({P: "a" * (1 << 20)}), None, None, "verified"),
    ("head_moved", None, commit({P: "# Plan\n"}), commit({P: "# Later\n"}), None, "unsettled:head_moved"),
    ("branch", None, commit({P: "# Plan\n"}), lambda slot: slot.checkout_new("task/tl-1"), None, "unsettled:branch"),
    ("untracked", None, commit({P: "# Plan\n"}), lambda slot: slot.write_file("scratch", "x"), None, "unsettled:dirty"),
    ("random_commit", None, lambda _slot: "c" * 40, None, None, "unsettled:head_moved"),
    ("lost_base", None, commit({P: "# Plan\n"}), None, "UPDATE plan_attempt SET base_commit='f' || substr(base_commit, 2)", LOST),
    ("dropped", None, commit({P: "# Plan\n"}), lambda slot: slot.repo.drop_checkout(slot.path), None, "unavailable:git:NotARepo"),
    ("not_listed", None, commit({P: "# Plan\n"}), lambda slot: slot.repo.drop_worktree(slot.path), None, "unavailable:not_listed"),
    ("other_repo", None, commit({P: "# Plan\n"}), None, OTHER_REPO, "unavailable:repo"),
]


@pytest.mark.parametrize(("before", "act", "after", "sql", "expected"), [case[1:] for case in CASES], ids=[case[0] for case in CASES])
def test_the_verdict_table(
    registered: sqlite3.Connection,
    slot: FakeWorktree,
    tmp_path: Path,
    checkouts: Checkouts,
    before: Act | None,
    act: Act,
    after: After | None,
    sql: str | None,
    expected: str,
) -> None:
    if before is not None:
        before(slot)  # before dispatch: B is this commit
    captured(registered, tmp_path, slot, checkouts, act)
    if after is not None:
        after(slot)
    for statement in (sql or "").split(";"):
        if statement.strip():
            registered.execute(statement)
    result = verifier(registered, checkouts).verify(KEY)
    assert shown(result) == expected
    final = expected.startswith(("verified", "reused", "rejected"))
    assert len(stored(registered)) == (1 if final else 0)  # slot state and unknowns are never stored
    collected = body(registered, tmp_path, checkouts, agent(slot, head)).collect(KEY)
    assert (collected.status, collected.reason) == (("collected", expected) if final else ("pending", "verification"))


def test_a_reported_commit_that_is_no_commit_is_absent(repo: FakeRepo, slot: FakeWorktree) -> None:
    """Through `verify` the slot precondition decides first (HEAD is never a missing commit); the rule itself, alone."""
    base = head(slot)
    tree = slot.snapshot("HEAD").head_tree
    assert tree is not None
    for reported in ("c" * 40, tree, base[:12]):  # an abbreviation resolves to another name of a commit: never X itself
        assert judge(repo, repo.path, base, reported, "tl-1", P) == Rejected("commit_absent")


@pytest.mark.parametrize("unread", ["parent", "blob"])
def test_an_empty_read_of_a_parent_or_a_listed_blob_is_unknown_never_a_verdict(
    registered: sqlite3.Connection,
    slot: FakeWorktree,
    repo: FakeRepo,
    tmp_path: Path,
    checkouts: Checkouts,
    monkeypatch: pytest.MonkeyPatch,
    unread: str,
) -> None:
    """The library reads both with an unchecked exit code: a failed read and a root commit or a missing blob look alike."""
    captured(registered, tmp_path, slot, checkouts, commit({P: "# Plan\n"}))
    read = repo.tree

    def failing(rev: str) -> Tree | None:
        found = read(rev)
        if unread == "parent":
            return None if rev.endswith("^") else found
        return None if found is None else Tree(found.sha, lambda: found.files, lambda _path: None)

    monkeypatch.setattr(repo, "tree", failing)
    assert verifier(registered, checkouts).verify(KEY) == VerifyUnavailable("git:Unreadable")
    assert stored(registered) == []


def test_a_stored_verdict_is_returned_again_without_any_git_read(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts
) -> None:
    captured(registered, tmp_path, slot, checkouts, commit({P: "# Plan\n"}))
    first = verifier(registered, checkouts).verify(KEY)
    assert isinstance(first, Verified) and not first.reused
    slot.repo.drop_checkout(slot.path)
    counted = Counted(checkouts)
    assert verifier(registered, counted).verify(KEY) == first and counted.opens == 0
    assert stored(registered) == [("verified", None, 0, 20.0)]


@pytest.mark.parametrize(
    ("answer", "rc", "expected"),
    [
        ({"disposition": "incomplete", "plan_path": None}, 0, NotApplicable("incomplete")),
        ({"disposition": "needs_owner", "plan_path": None}, 0, NotApplicable("needs_owner")),
        ({"disposition": "other"}, 0, NotApplicable("answer:schema_invalid")),
        ({}, 1, NotApplicable("run:worker_failed")),
    ],
    ids=["incomplete", "needs_owner", "invalid", "failed_run"],
)
def test_no_valid_planned_answer_of_a_clean_run_is_not_applicable_with_no_git_read(
    registered: sqlite3.Connection,
    slot: FakeWorktree,
    tmp_path: Path,
    checkouts: Checkouts,
    answer: dict[str, object],
    rc: int,
    expected: object,
) -> None:
    run = agent(slot, commit({P: "# Plan\n"}), PLAN | answer, rc)
    assert body(registered, tmp_path, checkouts, run).execute(KEY, ENTRY).status == "collected"
    counted = Counted(checkouts)
    assert verifier(registered, counted).verify(KEY) == expected and counted.opens == 0 and stored(registered) == []


def test_refusals_and_unknowns_before_any_git_read(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts
) -> None:
    counted = Counted(checkouts)
    assert verifier(registered, counted).verify(KEY) == VerifyRefused("not_captured")
    captured(registered, tmp_path, slot, checkouts, commit({P: "# Plan\n"}))
    registered.execute("UPDATE plan_execution SET answer_kind='validation_pending',disposition=NULL,plan_path=NULL,reported_commit=NULL")
    assert verifier(registered, counted).verify(KEY) == VerifyUnavailable("validation_pending")
    assert PlanVerifier(PlanStore(lambda: None), counted, lambda: 20).verify(KEY) == VerifyUnavailable("store")
    assert counted.opens == 0 and stored(registered) == []


@pytest.mark.parametrize(
    ("publication", "expected"), [("pending", VerifyUnavailable("session_pending")), ("conflict", VerifyRefused("session"))]
)
def test_an_unfinished_session_publication_is_never_verified(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, publication: str, expected: object
) -> None:
    captured(registered, tmp_path, slot, checkouts, commit({P: "# Plan\n"}))
    registered.execute("UPDATE plan_execution SET publication=?", (publication,))
    assert verifier(registered, checkouts).verify(KEY) == expected and stored(registered) == []


@pytest.mark.parametrize(
    "change",
    [
        "UPDATE reservation SET generation=2",
        "UPDATE plan_execution SET disposition='incomplete'",
        "UPDATE plan_execution SET answer_kind='schema_invalid',disposition=NULL,plan_path=NULL",
        "UPDATE plan_execution SET rc=1",
        "UPDATE plan_execution SET rc=NULL,timed_out=1",
        "UPDATE plan_execution SET publication='pending'",
    ],
    ids=["stale_reservation", "incomplete_with_commit", "invalid", "failed_run", "timed_out", "publication_pending"],
)
def test_the_writer_itself_refuses_a_verdict_without_its_preconditions(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts, change: str
) -> None:
    captured(registered, tmp_path, slot, checkouts, commit({P: "# Plan\n"}))
    store = PlanStore(lambda: registered)
    record = store.load(KEY)
    assert record is not None and record.base_commit is not None
    registered.execute(change)
    with pytest.raises(StoreRefused, match="stale_reservation" if "reservation" in change else "changed_answer"):
        store.verdict(record.admission, record.base_commit, head(slot), Verified("e" * 40), 1)
    assert stored(registered) == []


def test_a_dispatched_attempt_always_has_a_base(registered: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError, match="base_commit IS NOT NULL"):
        registered.execute("UPDATE plan_attempt SET phase='dispatching'")
    registered.execute("UPDATE plan_attempt SET phase='dispatching',base_commit=?", ("b" * 40,))


def test_a_stale_reservation_refuses_and_stores_nothing(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts
) -> None:
    captured(registered, tmp_path, slot, checkouts, commit({P: "# Plan\n"}))
    registered.execute("UPDATE reservation SET generation=2")
    assert verifier(registered, checkouts).verify(KEY) == VerifyRefused("stale_reservation")
    assert stored(registered) == []


def test_the_insert_is_conditional_never_rewritten_and_a_differing_row_is_inconsistent(
    registered: sqlite3.Connection, slot: FakeWorktree, tmp_path: Path, checkouts: Checkouts
) -> None:
    captured(registered, tmp_path, slot, checkouts, commit({P: "# Plan\n"}))
    store = PlanStore(lambda: registered)
    record = store.load(KEY)
    assert record is not None and record.base_commit is not None
    x = head(slot)
    with pytest.raises(StoreRefused, match="changed_answer"):
        store.verdict(record.admission, record.base_commit, record.base_commit, Rejected("paths"), 1)
    assert stored(registered) == []
    assert store.verdict(record.admission, record.base_commit, x, Rejected("paths"), 1) == Rejected("paths")
    assert store.verdict(record.admission, record.base_commit, x, Verified("e" * 40), 2) == Rejected("paths")
    assert stored(registered) == [("rejected", "paths", 0, 1.0)]

    class Racing(PlanStore):
        """Another verifier stored its row between this one's collect and insert."""

        def collect(self, key: AttemptKey) -> StoredExecution | None:
            found = super().collect(key)
            return None if found is None else dataclasses.replace(found, verification=None)

    assert PlanVerifier(Racing(lambda: registered), checkouts, lambda: 3).verify(KEY) == VerifyUnavailable("inconsistent")


def test_the_real_composition_opens_the_factory_database(tmp_path: Path) -> None:
    store = Store(SCHEMA)
    assert open_plan_verifier(tmp_path / "factory.db", store).verify(KEY) == VerifyRefused("not_captured")
    store.close_shared()


def test_every_rule_a_verdict_can_name_is_one_the_store_reads_back() -> None:
    assert set(RULES) == set(get_args(Rule.__value__)) and len(RULES) == len(set(RULES))
