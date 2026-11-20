"""Released source reads retain the exact identity, artifact and settings."""

from dataclasses import replace
from pathlib import Path

import pytest
from git_porcelain.testing import FakeRepo
from land_conflict_bench import bench

from taskloop.agents.settings import AgentSetting, OpenCodePolicy, encode_policy
from taskloop.attempt_reads import StoreRefused
from taskloop.attempt_types import AttemptKey
from taskloop.harness_choice import HarnessKind
from taskloop.land_conflict.admit import admit
from taskloop.land_conflict.models import Outcome


def test_retained_read_survives_release_without_weakening_live_load(on_slot: Path, repo: FakeRepo, tmp_path: Path) -> None:
    b = bench(on_slot, repo, tmp_path)
    inputs = b.ports.attempts.retained(b.request.source)
    assert inputs is not None and inputs.checked == b.request.checked
    assert (inputs.setting.model, inputs.setting.effort, inputs.setting.harness.value) == ("m", "e", "codex")
    assert inputs.setting.access.model_dump()["sandbox"] == "workspace-write"
    assert b.ports.files.read(inputs.input_ref) == "The exact retained requirements.\n"
    with pytest.raises(StoreRefused):
        b.ports.attempts.load(b.request.source)
    for key in (replace(b.request.source, dispatch_token="wrong"), replace(b.request.source, reservation_generation=2),
                AttemptKey("missing", "implement-token", 1)):
        assert b.ports.attempts.retained(key) is None
    b.con.close()


@pytest.mark.parametrize("damage", ["missing", "digest", "utf8", "outside", "settings"])
def test_invalid_original_inputs_never_reserve(on_slot: Path, repo: FakeRepo, tmp_path: Path, damage: str) -> None:
    b = bench(on_slot, repo, tmp_path)
    if damage == "missing":
        b.artifact.unlink()
    elif damage == "digest":
        b.artifact.write_text("changed")
    elif damage == "utf8":
        b.artifact.write_bytes(b"\xff")
        b.con.execute("UPDATE attempt SET input_digest=?", ("a8100ae6aa1940d0b663bb31cd466142ebbdbd5187131b92d93818987832eb89",))
    elif damage == "outside":
        b.con.execute("UPDATE attempt SET input_path='../outside'")
    else:
        b.con.execute("UPDATE attempt SET access_policy='{}'")
    result = admit(b.ports, b.request)
    assert result.outcome in (Outcome.INPUT, Outcome.UNAVAILABLE) and result.explanation
    assert b.con.execute("SELECT * FROM reservation").fetchall() == []
    assert b.con.execute("SELECT * FROM land_conflict").fetchall() == []
    b.con.close()


@pytest.mark.parametrize("field,value", [("repo_id", "other"), ("backlog", "elsewhere"), ("task_id", "tl-2"),
                                       ("tracker_root", "/other"), ("checked", "f" * 40)])
def test_source_identity_must_match(on_slot: Path, repo: FakeRepo, tmp_path: Path, field: str, value: str) -> None:
    b = bench(on_slot, repo, tmp_path)
    result = admit(b.ports, b.request.model_copy(update={field: value}))
    assert result.outcome is Outcome.SOURCE and result.explanation
    assert b.con.execute("SELECT * FROM reservation").fetchall() == []
    b.con.close()


def test_captured_nondefault_harness_and_policy_survive_admission(on_slot: Path, repo: FakeRepo, tmp_path: Path) -> None:
    b = bench(on_slot, repo, tmp_path)
    setting = AgentSetting(harness=HarnessKind.OPENCODE, model="vendor/model", effort="low", access=OpenCodePolicy())
    b.con.execute("UPDATE attempt SET harness=?,provider=?,model=?,effort=?,access_policy=?", (
        setting.harness.value, setting.provider.value, setting.model, setting.effort, encode_policy(setting.access)))
    result = admit(b.ports, b.request)
    assert result.outcome is Outcome.ADMITTED and result.record is not None
    assert result.record.inputs.setting == setting
    assert b.ports.store.find(b.request) == result.record
    b.con.close()
