"""The Prompt tab displays immutable, complete, digest-validated input as text."""

import sqlite3
from pathlib import Path
from typing import NoReturn

import pytest
from test_dash_read import KEY, Tracker, reads_of

from taskloop.dash_model import AttemptBody
from taskloop.dash_task import TaskPorts, build_body
from taskloop.discussion import frame
from taskloop.evidence_files import EvidenceFiles
from taskloop.operations import Failed


class NoTracker(Tracker):
    def fields(self, task_id: str) -> NoReturn:
        raise AssertionError("Saved input never polls or reconstructs tracker discussion")


def test_prompt_beyond_64k_is_complete_saved_text(registered: sqlite3.Connection, tmp_path: Path) -> None:
    files = EvidenceFiles(tmp_path)
    block = frame(["Author: owner; time: 2026-11-13T12:00:00Z", "<script>decision</script>\n**plain text**"])
    text = "Requirements\n" + "é" * 40000 + "\n" + block
    ref = files.put_input(KEY, text)
    registered.execute("UPDATE attempt SET input_path=?,input_digest=?", (ref.path, ref.digest))
    ports = TaskPorts(reads_of(registered), files, NoTracker())
    first = build_body(ports, "tasks", "tl-1", "plan", 1)
    second = build_body(ports, "tasks", "tl-1", "plan", 1)
    assert isinstance(first, AttemptBody) and isinstance(second, AttemptBody)
    assert first.input == second.input == text
    assert first.input is not None
    assert first.input.endswith(block) and "| <script>decision</script>" in first.input


@pytest.mark.parametrize("damage", ["missing", "digest"])
def test_missing_or_damaged_prompt_is_unavailable(
    registered: sqlite3.Connection, tmp_path: Path, damage: str,
) -> None:
    if damage == "missing":
        registered.execute("UPDATE attempt SET input_path='missing.txt'")
    else:
        registered.execute("UPDATE attempt SET input_digest='wrong'")
    body = build_body(TaskPorts(reads_of(registered), EvidenceFiles(tmp_path), NoTracker()), "tasks", "tl-1", "plan", 1)
    assert isinstance(body, Failed) and body.kind == "unavailable" and body.reason == "input" and body.detail
