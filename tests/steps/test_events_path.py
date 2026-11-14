"""Show resolves events locations without opening them or changing execution state."""

import sqlite3
from pathlib import Path

import pytest

from taskloop.attempt_status import Shown, StatusPorts, show_attempt
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey
from taskloop.evidence_files import EvidenceFiles
from taskloop.result_data import as_data
from taskloop.step_render import human

KEY = AttemptKey("attempt", "dispatch", 1)


@pytest.mark.parametrize("state", ["absent", "empty", "truncated", "unreadable"])
def test_agent_events_location_is_read_only_before_launch(
    registered: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str,
) -> None:
    files = EvidenceFiles(tmp_path / "custom artifacts with spaces")
    expected = files.events_path(KEY)
    if state != "absent":
        expected.parent.mkdir(parents=True)
        if state == "unreadable":
            expected.mkdir()  # Opening as a log would fail even for a privileged test user.
        else:
            expected.write_text("" if state == "empty" else '{"unfinished":')
    before = sorted(files.root.rglob("*"))
    changes = registered.total_changes
    # Guard the owning evidence content reader instead of depending on filesystem permissions.
    def content(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Show must not read event content")

    monkeypatch.setattr(EvidenceFiles, "activity_tail", content)
    monkeypatch.setattr(EvidenceFiles, "activity_after", content)
    monkeypatch.setattr(EvidenceFiles, "open_events", content)
    reads = StatusPorts(AttemptStore(lambda: registered), lambda _entry: "gone", lambda: 10, lambda _key: None, lambda: "boot")
    shown = show_attempt(reads, files.root, "tasks", "tl-1")
    assert isinstance(shown, Shown)
    assert shown.events_path == expected and as_data(shown)["events_path"] == str(expected)
    assert f"Events: {expected}" in human("tl step show", shown, None)
    assert sorted(files.root.rglob("*")) == before and registered.total_changes == changes
