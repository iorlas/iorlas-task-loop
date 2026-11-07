"""The engine delegates context policy and carries only prompt history."""
import pytest

from tlkernel import wire
from tlkernel.checkpoint import WriterSession
from tlkernel.config import ConfigError, load
from tlkernel.delegate import RunRequest
from tlkernel.trace import WriteRound


def test_writer_session_has_only_prompt_history():
    assert set(wire.names(WriterSession)) == {"seen", "last_stage"}


def test_engine_refuses_removed_context_policy():
    with pytest.raises(ConfigError, match="write_fresh_above_k"):
        load({"engine": {"write_fresh_above_k": 150}})


def test_request_marks_stage_boundary():
    request = RunRequest(role="worker", brief_path="whole", cwd="tree", schema_path="schema", boundary=True)
    assert request.boundary is True


def test_write_rows_have_no_fresh_reason():
    assert "fresh" not in wire.names(WriteRound)
