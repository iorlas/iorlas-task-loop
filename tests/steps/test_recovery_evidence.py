"""Recovery generations never share mutable native output or accepted capture bytes."""

from pathlib import Path

import pytest
from any_agent import RunOutcome, Summary
from test_recovery_registration import WORKER, intended
from test_recovery_store import KEY, database

from taskloop.evidence_files import EvidenceError, EvidenceFiles
from taskloop.recovery.state_store import callback
from taskloop.recovery.store import RecoveryStore


def test_delayed_generation_writes_cannot_change_accepted_evidence(tmp_path: Path) -> None:
    con = database(tmp_path / "factory.db")
    store, files = RecoveryStore(lambda: con), EvidenceFiles(tmp_path / "artifacts")
    first = intended(store, "first")
    first_schema, first_native = files.prepare(KEY, {"type": "object"}, first)
    first_root = files.launch_root(KEY, first)
    first_input = files.put_launched_input(KEY, "first prompt", first)
    registered = store.register(first, WORKER, lambda: 10)
    assert registered.intent is not None
    old = callback(registered.intent)
    second = intended(store, "second")
    second_schema, second_native = files.prepare(KEY, {"type": "object"}, second)
    second_root = files.launch_root(KEY, second)
    second_input = files.put_launched_input(KEY, "second prompt", second)
    registered = store.register(second, WORKER.model_copy(update={"start": "second"}), lambda: 10)
    assert registered.intent is not None
    current = callback(registered.intent)
    assert first_schema != second_schema and first_native != second_native
    assert first_root != second_root and first_input != second_input
    raw = RunOutcome(out="current", summary=Summary(text="accepted"))
    accepted = files.capture(KEY, raw, current)
    assert files.capture_refs(KEY, raw, current) == accepted
    assert files.capture(KEY, raw, current) == accepted
    Path(first_native).write_text("late native output")
    files.capture(KEY, RunOutcome(out="old", summary=Summary(text="late answer")), old)
    assert files.read(accepted.stdout) == "current" and files.read(accepted.answer) == "accepted"
    assert files.capture_refs(KEY, raw, current) == accepted
    with pytest.raises(EvidenceError, match="Conflicting"):
        files.capture(KEY, RunOutcome(out="different"), current)
    assert files.read(accepted.stdout) == "current"
    con.close()
