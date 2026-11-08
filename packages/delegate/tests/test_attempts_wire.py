"""`RunResult.attempts`: the launches one call made, so the caller can see in-call retries (tl-7i9k.45, M-259). Additive: absent when the
call made a single launch."""

from pathlib import Path

from delegate import api
from delegate.app import answer
from delegate.contracts import codec, wire
from delegate.contracts.json_types import Json
from delegate.contracts.wire import Attempt, RunResult

TWO: Json = [
    {"kind": "first", "account": "L", "model": "m", "outcome": "schema_invalid", "secs": 3.5, "tokens": {"in": 10, "cached": 0, "out": 2}},
    {"kind": "schema_reask", "account": "L", "model": "m", "outcome": None, "secs": 1.0, "tokens": None},
]


def test_a_result_without_attempts_has_no_such_key():
    assert "attempts" not in api.as_json(codec.from_json(RunResult, answer.result(None)))


def test_attempts_round_trip_in_order():
    got = codec.from_json(RunResult, answer.result(None, attempts=TWO))
    attempts = got.attempts
    assert isinstance(attempts, list)
    assert [(a.kind, a.outcome) for a in attempts] == [("first", "schema_invalid"), ("schema_reask", None)]
    assert all(isinstance(a, Attempt) for a in attempts)
    assert api.as_json(got)["attempts"] == TWO


def test_the_contract_names_the_field_and_the_capability():
    assert "attempts" in wire.CAPABILITIES
    text = (Path(wire.__file__).parents[1] / "data" / "contract.json").read_text(encoding="utf-8")
    assert '"attempts"' in text
