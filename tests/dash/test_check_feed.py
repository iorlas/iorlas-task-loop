"""Check output through the owning evidence reader and the dashboard's typed projection."""

import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import checking, factory
from doubles import CHECKS, REQUIRED, TARGET, D
from sqlite_sidecar import transaction

from taskloop import check_feed, check_store
from taskloop.attempt_status import StatusPorts
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey
from taskloop.check_feed import LINE_CAP, READ_CAP, CheckLog, CheckPage, CheckState, decode
from taskloop.check_store import CheckStore
from taskloop.command_conclusion import CommandConclusion
from taskloop.dash_model import AttemptBody, Comment, FeedPage, Fields, Ready
from taskloop.dash_task import TaskPorts, build_body, build_feed
from taskloop.evidence_files import EvidenceFiles
from taskloop.operations import Failed

__all__ = ["checking", "factory"]

KEY = AttemptKey("checks", "checks-token", 1)
LOG = CheckLog(position=0, name="lint", state=CheckState.RUNNING)


def texts(page: CheckPage) -> list[str]:
    return [record.text for record in page.records if record.text is not None]


def test_missing_evidence_is_read_only_and_a_later_file_is_followed_from_start(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path / "absent")
    page = files.check_feed(KEY, 1, (LOG,), None)
    assert not page.available and not files.root.exists()
    files.check_log(KEY, 1, "lint").write_bytes(b"first\nsecond\n")
    page = files.check_feed(KEY, 1, (LOG,), page.cursor)
    assert page.available and not page.replaced and texts(page) == ["first\n", "second\n"]
    assert not files.check_feed(KEY, 1, (LOG,), page.cursor).records


def test_tail_is_latest_and_follow_does_not_drop_lines_at_the_page_limit(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    path = files.check_log(KEY, 1, "lint")
    path.write_bytes(b"old\n" * 40)
    initial = files.check_feed(KEY, 1, (LOG,), None)
    assert len(initial.records) == 20 and len(texts(initial)) == 19
    appended = [f"line {number}\n" for number in range(53)] + ["bad \ufffd\n"]
    with path.open("ab") as stream:
        stream.write("".join(appended[:-1]).encode() + b"bad \xff\n")
    cursor, found = initial.cursor, []
    for _ in range(4):
        page = files.check_feed(KEY, 1, (LOG,), cursor)
        assert len(page.records) <= 20
        found.extend(texts(page))
        cursor = page.cursor
    assert found == appended


def test_running_partial_lines_wait_and_completion_flushes_with_one_typed_summary(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    path = files.check_log(KEY, 1, "lint")
    path.write_bytes(b"whole\npart")
    initial = files.check_feed(KEY, 1, (LOG,), None)
    assert texts(initial) == ["whole\n"]
    assert not files.check_feed(KEY, 1, (LOG,), initial.cursor).records
    with path.open("ab") as stream:
        stream.write(b"ial\nlast")
    following = files.check_feed(KEY, 1, (LOG,), initial.cursor)
    assert texts(following) == ["partial\n"]
    ended = LOG.model_copy(update={"state": CheckState.FINISHED, "conclusion": CommandConclusion.FAILED})
    final = files.check_feed(KEY, 1, (ended,), following.cursor)
    assert texts(final) == ["last"]
    assert final.records[-1].offset is None and final.records[-1].conclusion == CommandConclusion.FAILED
    assert not files.check_feed(KEY, 1, (ended,), final.cursor).records


def test_lifecycle_changes_without_output_are_emitted_even_when_evidence_is_unavailable(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    initial = files.check_feed(KEY, 1, (LOG,), None)
    ended = LOG.model_copy(update={"state": CheckState.UNFINISHED})
    final = files.check_feed(KEY, 1, (ended,), initial.cursor)
    assert not final.available and len(final.records) == 1
    assert final.records[0].state == CheckState.UNFINISHED
    assert not files.check_feed(KEY, 1, (ended,), final.cursor).records


@pytest.mark.parametrize("change", ["replace", "truncate", "block", "attempt"])
def test_changed_identity_resets_to_a_tail(tmp_path: Path, change: str) -> None:
    files = EvidenceFiles(tmp_path)
    path = files.check_log(KEY, 1, "lint")
    path.write_bytes(b"original\n")
    initial = files.check_feed(KEY, 1, (LOG,), None)
    key, block = KEY, 1
    if change == "replace":
        path.rename(path.with_suffix(".old"))
    elif change == "block":
        block = 2
    elif change == "attempt":
        key = AttemptKey("another", "token", 1)
    files.check_log(key, block, "lint").write_bytes(b"new\n")
    page = files.check_feed(key, block, (LOG,), initial.cursor)
    assert page.replaced and texts(page) == ["new\n"]


def test_oversized_lines_progress_in_bounded_fragments_and_share_a_read_budget(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    other = CheckLog(position=1, name="tests", state=CheckState.RUNNING)
    first = files.check_log(KEY, 1, "lint")
    second = files.check_log(KEY, 1, "tests")
    first.write_bytes(b"")
    second.write_bytes(b"")
    page = files.check_feed(KEY, 1, (LOG, other), None)
    first.write_bytes(b"x" * READ_CAP + b"\n")
    second.write_bytes(b"y\n")
    collected: list[str] = []
    for _ in range(4):
        page = files.check_feed(KEY, 1, (LOG, other), page.cursor)
        assert all(len(text.encode()) <= LINE_CAP for text in texts(page))
        collected.extend(texts(page))
    assert "".join(collected) == "x" * READ_CAP + "\ny\n"
    tail = files.check_feed(KEY, 1, (LOG, other), None)
    assert len(tail.records) <= 20
    assert sum(len(text.encode()) for text in texts(tail)) <= READ_CAP


def test_budget_is_shared_across_files_in_position_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(check_feed, "READ_CAP", 32)
    files = EvidenceFiles(tmp_path)
    other = CheckLog(position=1, name="tests", state=CheckState.RUNNING)
    paths = [files.check_log(KEY, 1, log.name) for log in (LOG, other)]
    for path in paths:
        path.write_bytes(b"")
    page = files.check_feed(KEY, 1, (LOG, other), None)
    for path, value in zip(paths, (b"aaa\n", b"bbb\n"), strict=True):
        path.write_bytes(value * 12)
    collected: list[str] = []
    for _ in range(4):
        previous = decode(page.cursor)
        page = files.check_feed(KEY, 1, (LOG, other), page.cursor)
        current = decode(page.cursor)
        assert sum(log.offset for log in current.logs) - sum(log.offset for log in previous.logs) <= 32
        collected.extend(texts(page))
    assert collected == ["aaa\n"] * 12 + ["bbb\n"] * 12


def test_unreadable_and_escaped_paths_are_unavailable(tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path / "evidence")
    path = files.check_log(KEY, 1, "lint")
    path.mkdir()
    assert not files.check_feed(KEY, 1, (LOG,), None).available
    outside = tmp_path / "outside.log"
    outside.write_text("must not be served\n")
    path.rmdir()
    path.symlink_to(outside)
    page = files.check_feed(KEY, 1, (LOG,), None)
    assert not page.available and not texts(page)


class Tracker:
    def ready(self) -> tuple[Ready, ...]:
        return ()

    def titles(self, task_ids: tuple[str, ...]) -> dict[str, str]:
        return {}

    def fields(self, task_id: str) -> tuple[Fields, tuple[Comment, ...]] | None:
        return None

    def notice(self) -> str | None:
        return None


def ports_of(con: sqlite3.Connection, files: EvidenceFiles) -> TaskPorts:
    reads = StatusPorts(AttemptStore(lambda: con), lambda _entry: "matching", lambda: 10, lambda _key: None, lambda: "boot")
    return TaskPorts(reads, files, Tracker())


def test_projection_uses_result_identity_and_typed_outcomes(checking: sqlite3.Connection, tmp_path: Path) -> None:
    files, store = EvidenceFiles(tmp_path), CheckStore(lambda: checking, transaction)
    store.start(CHECKS, 1, 0, "lint", "a" * 64, 60, 3)
    files.check_log(CHECKS, 1, "lint").write_bytes(b"passed (display text only)\n")
    ports = ports_of(checking, files)
    page = build_feed(ports, "tasks", "tl-1", "checks", 1, None)
    assert isinstance(page, FeedPage)
    output, summary = page.events
    assert (output.type, output.block, output.name, output.state, output.passed) == ("check", 1, "lint", "running", None)
    assert output.id == "1:0:0" and output.at == summary.at
    store.finish(CHECKS, 1, 0, CommandConclusion.FAILED, 1, 4)
    final = build_feed(ports, "tasks", "tl-1", "checks", 1, page.cursor)
    assert isinstance(final, FeedPage) and len(final.events) == 1
    assert final.events[0].state == "finished" and final.events[0].passed is False
    body = build_body(ports, "tasks", "tl-1", "checks", 1)
    assert isinstance(body, AttemptBody)
    assert (body.result.checks[0].block, body.result.checks[0].name) == (output.block, output.name)
    assert body.result.checks[0].output == output.text
    store.start(CHECKS, 2, 0, "lint", "a" * 64, 60, 5)
    files.check_log(CHECKS, 2, "lint").write_bytes(b"new block\n")
    reset = build_feed(ports, "tasks", "tl-1", "checks", 1, final.cursor)
    assert isinstance(reset, FeedPage) and reset.replaced and reset.events[0].block == 2


def test_restart_numbering_and_unknown_attempts(checking: sqlite3.Connection, tmp_path: Path) -> None:
    store, files = CheckStore(lambda: checking, transaction), EvidenceFiles(tmp_path)
    store.start(CHECKS, 1, 0, "lint", "a" * 64, 60, 3)
    checking.execute("UPDATE checks_attempt SET phase='concluded',conclusion='passed',concluded_at=5,released_at=6,parked=?", (D,))
    checking.execute("DELETE FROM reservation WHERE attempt_id='checks'")
    again = AttemptKey("again", "again-token", 1)
    check_store.insert(checking, check_store.ChecksAdmitted(again, "implement", 2, "s2", D, TARGET, REQUIRED, 100.0))
    checking.execute("INSERT INTO reservation VALUES ('s2','r',1,'again')")
    store.start(again, 1, 0, "lint", "a" * 64, 60, 3)
    for key in (CHECKS, again):
        files.check_log(key, 1, "lint").write_text(key.attempt_id + "\n")
    ports = ports_of(checking, files)
    for number, expected in ((1, "checks\n"), (2, "again\n")):
        page = build_feed(ports, "tasks", "tl-1", "checks", number, None)
        assert isinstance(page, FeedPage) and page.events[0].text == expected
        assert decode(page.cursor or "").attempt == expected.strip()
    assert build_feed(ports, "tasks", "tl-1", "checks", 3, None) is None
    assert build_feed(ports, "tasks", "absent", "checks", 1, None) is None
    broken = replace(ports.reads, store=AttemptStore(lambda: sqlite3.connect(f"file:{tmp_path / 'missing.db'}?mode=ro", uri=True)))
    assert isinstance(build_feed(replace(ports, reads=broken), "tasks", "tl-1", "checks", 1, None), Failed)


def test_checks_numbering_spans_implement_attempts(checking: sqlite3.Connection, tmp_path: Path) -> None:
    store, files = CheckStore(lambda: checking, transaction), EvidenceFiles(tmp_path)
    store.start(CHECKS, 1, 0, "lint", "a" * 64, 60, 3)
    files.check_log(CHECKS, 1, "lint").write_bytes(b"original implement\n")
    checking.execute("UPDATE checks_attempt SET phase='concluded',conclusion='passed',concluded_at=5,released_at=6,parked=?", (D,))
    checking.execute("DELETE FROM reservation WHERE attempt_id='checks'")
    checking.execute(
        """INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,task_id,tracker_root,repo_id,slot,
        input_path,input_digest,schema_version,model,effort,access_policy,deadline,number,seq,slot_head,previous_attempt_id,repeat_reason,
        phase,base_commit,end_commit,after_commit,engine_digest,workflow_digest,workflow_sha,admitted_at)
        SELECT 'another','another-token',1,step,adapter,backlog,task_id,tracker_root,repo_id,slot,input_path,input_digest,
        schema_version,model,effort,access_policy,deadline,2,3,slot_head,'implement','unsafe',phase,base_commit,end_commit,NULL,engine_digest,workflow_digest,workflow_sha,admitted_at
        FROM attempt WHERE attempt_id='implement'"""
    )
    checking.execute("INSERT INTO slot_release VALUES ('another','another-token',1,?,7,'kept')", (D,))
    key = AttemptKey("fresh", "fresh-token", 1)
    check_store.insert(checking, check_store.ChecksAdmitted(key, "another", 1, "s2", D, TARGET, REQUIRED, 100.0))
    checking.execute("INSERT INTO reservation VALUES ('s2','r',1,'fresh')")
    store.start(key, 1, 0, "lint", "a" * 64, 60, 8)
    files.check_log(key, 1, "lint").write_bytes(b"another implement\n")
    ports = ports_of(checking, files)
    for number, text in ((1, "original implement\n"), (2, "another implement\n")):
        page = build_feed(ports, "tasks", "tl-1", "checks", number, None)
        assert isinstance(page, FeedPage) and page.events[0].text == text
