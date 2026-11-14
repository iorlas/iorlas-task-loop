"""Captured compaction choices survive storage reopening, execution and retained-input reads, offline."""

from pathlib import Path

import pytest
from sqlite_store import Store
from test_attempt import ENTRY, KEY, AttemptSurroundings, app, fake, seed
from test_attempt import surroundings as attempt_surroundings

from taskloop.attempt_reads import StoreUnavailable, stored_setting
from taskloop.attempt_store import AttemptStore
from taskloop.factory_schema import SCHEMA

surroundings = attempt_surroundings


@pytest.mark.parametrize("limit", [None, 100000])
def test_reopened_attempt_uses_its_captured_compaction_for_launch_and_retained_inputs(
    tmp_path: Path, surroundings: AttemptSurroundings, limit: int | None,
) -> None:
    path = tmp_path / "factory.db"
    first = Store(SCHEMA).open_rw(path)
    assert first is not None
    seed(first, surroundings)
    first.execute("UPDATE attempt SET compaction_token_limit=?", (limit,))
    first.close()
    reopened = Store(SCHEMA).open_rw(path)
    assert reopened is not None
    try:
        store = AttemptStore(lambda: reopened)
        loaded = store.load(KEY)
        assert loaded is not None and loaded.admission.setting.compaction_token_limit == limit
        assert store.attempts("tasks", "tl-1")[0].run == loaded.admission.setting
        execution = fake()
        assert app(reopened, surroundings, execution).execute(KEY, ENTRY).reason == "verification"
        overrides = [item for item in execution.calls[0][1].argv if item.startswith("model_auto_compact_token_limit=")]
        assert overrides == ([] if limit is None else [f"model_auto_compact_token_limit={limit}"])
        # Retained inputs belong to implement attempts whose checked commit has been captured.
        reopened.execute("UPDATE attempt SET step='implement',after_commit=?,end_commit=?", ("a" * 40, "b" * 40))
        retained = store.retained(KEY)
        assert retained is not None and retained.setting == loaded.admission.setting
    finally:
        reopened.close()


@pytest.mark.parametrize("value", [True, "100000", 100000.0, 0, -1])
def test_malformed_stored_compaction_is_refused(value: object) -> None:
    with pytest.raises(StoreUnavailable):
        stored_setting("codex", "openai", "chosen", "high", '{"harness":"codex","sandbox":"workspace-write"}', value)
