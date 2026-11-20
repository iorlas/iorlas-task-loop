"""Pure TaskEvent contracts: closed causes, causal identity, context and existing reason spelling."""

import json
from collections.abc import Mapping

import pytest
from pydantic import ValidationError

from taskloop.task_event import TaskEvent
from taskloop.task_event_cause import Family
from taskloop.task_event_codec import decode, encode, reason


def payload(cause: dict[str, object], *, checks: bool = False) -> dict[str, object]:
    return {
        "attempt_id": "agent", "agent_step": "implement", "cause_id": "checks" if checks else "agent",
        "step": "check" if checks else "implement", "cause": cause,
    }


def event(cause: dict[str, object], *, checks: bool = False) -> TaskEvent:
    return decode(json.dumps(payload(cause, checks=checks)))


CASES: tuple[tuple[Mapping[str, object], bool, str], ...] = (
    ({"family": "disposition", "reason": "needs_owner", "explanation": "Which target?"}, False, "failed:needs_owner"),
    ({"family": "disposition", "reason": "incomplete", "explanation": "Work remains"}, False, "failed:incomplete"),
    *(({"family": "run", "reason": word}, False, f"failed:run:{word}") for word in (
        "timeout", "vendor_blip", "bad_request", "hung", "crash", "killed", "secrets", "exit", "worker_failed",
        "logged_out", "rate_limited", "credit_exhausted", "network", "setup",
    )),
    *(({"family": "answer", "reason": word}, False, f"failed:answer:{word}") for word in (
        "missing", "json_invalid", "schema_invalid",
    )),
    *(({"family": "rejection", "reason": word}, False, f"failed:rejected:{word}") for word in (
        "commit_absent", "not_descendant", "chain_length", "paths", "mode", "file_size", "nothing_written", "plan_missing",
        "plan_encoding", "plan_empty", "plan_size", "plan_change_map", "plan_depth", "plan_heading",
    )),
    *(({"family": "checks", "reason": word}, True, f"failed:{word}") for word in (
        "main_moved", "expired", "claim_lost", "commit_missing", "slot:unborn", "slot:moved", "slot:redirected", "slot:branch",
        "environment:platform", "environment:path_long", "environment:roots", "environment:remove_unsafe", "environment:profile",
        "environment:moved", "environment:reset", "environment:dirty", "environment:sandbox",
    )),
    *(({"family": "checks", "profile": word}, True, f"failed:profile:{word}") for word in (
        "missing", "no_commit", "not_json", "not_object", "unknown_key", "bad_value", "too_large", "duplicate_check",
        "required_undefined", "not_a_file",
    )),
    *(({"family": "checks", "setup": word}, True, f"failed:setup:{word}") for word in (
        "failed", "timed_out", "lingering", "dirty", "interrupted",
    )),
    *(({"family": "checks", "check": {"name": "unit:test:結果", "conclusion": word}}, True, f"failed:unit:test:結果:{word}")
      for word in ("failed", "timed_out", "lingering", "dirty", "undefined", "interrupted", "not_run")),
    *(({"family": "stuck", "reason": word}, word == "checks_refused", f"stuck:{word}") for word in (
        "expired_admitted", "entry_lost", "uncollected", "conflict", "setup_failed", "checks_refused",
    )),
    ({"family": "repeat"}, False, "repeats_exhausted"),
    *(({"family": "repeat", "leftovers": {"reason": word, "paths": ["a.py"]}}, False, f"repeats_exhausted:{word}")
      for word in ("uncommitted", "unsafe", "ignored")),
    *(({"family": "merge", "reason": word, "explanation": "Retained work"}, False, f"merge:{word}") for word in (
        "branch_diverged", "branch_moved", "slot_moved", "unsupported_conflict", "needs_owner", "exhausted",
        "invalid_resolution", "expired",
    )),
    *(({"family": "land", "reason": word, "explanation": "Land refused"}, True, f"land:{word}") for word in (
        "conflict", "checks_failed", "remote_rejected", "branch_moved", "claim_lost",
    )),
    *(({"family": "round", "reason": word}, checks, word)
      for word in ("claim_lost", "branch_moved") for checks in (True, False)),
)


@pytest.mark.parametrize(("cause", "checks", "expected"), CASES)
def test_round_trip_and_exact_reason(cause: dict[str, object], checks: bool, expected: str) -> None:
    found = event(cause, checks=checks)
    assert decode(encode(found)) == found
    assert reason(found) == expected


def test_every_cause_family_has_contract_examples() -> None:
    assert {cause["family"] for cause, _, _ in CASES} == {each.value for each in Family}


def test_plan_causality() -> None:
    data = payload({"family": "run", "reason": "exit"}) | {"agent_step": "plan", "step": "plan"}
    found = decode(json.dumps(data))
    assert decode(encode(found)) == found


@pytest.mark.parametrize("field", ["attempt_id", "explanation"])
def test_event_and_context_are_frozen(field: str) -> None:
    found = event({"family": "run", "reason": "exit"})
    with pytest.raises(ValidationError):
        setattr(found if field == "attempt_id" else found.cause, field, "changed")


@pytest.mark.parametrize("changes", [
    {"cause_id": "other"}, {"step": "plan"}, {"agent_step": "plan"}, {"attempt_id": ""},
    {"cause_id": ""}, {"step": "unknown"}, {"cause_id": 5}, {"extra": "field"},
])
def test_invalid_agent_identity(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        decode(json.dumps(payload({"family": "run", "reason": "exit"}) | changes))


@pytest.mark.parametrize("changes", [{"cause_id": "agent"}, {"agent_step": "plan"}, {"step": "implement"}])
def test_checks_require_distinct_cause_and_implement_owner(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        decode(json.dumps(payload({"family": "checks", "reason": "main_moved"}, checks=True) | changes))


@pytest.mark.parametrize("cause", [
    {"family": "disposition", "reason": "needs_owner", "explanation": "Decision"},
    {"family": "run", "reason": "exit"}, {"family": "answer", "reason": "missing"},
    {"family": "rejection", "reason": "paths"}, {"family": "repeat"},
    {"family": "merge", "reason": "expired", "explanation": "Stopped"},
    {"family": "stuck", "reason": "entry_lost"},
])
def test_agent_causes_cannot_claim_checks_identity(cause: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        event(cause, checks=True)


@pytest.mark.parametrize("cause", [
    {"family": "checks", "reason": "expired"}, {"family": "stuck", "reason": "checks_refused"},
])
def test_checks_causes_cannot_claim_agent_identity(cause: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        event(cause)


@pytest.mark.parametrize("cause", [
    {}, {"family": "unknown"}, {"family": "run", "reason": "unknown"},
    {"family": "disposition", "reason": "planned", "explanation": "Successful"},
    {"family": "disposition", "reason": "implemented", "explanation": "Successful"},
    {"family": "disposition", "reason": "unchanged", "explanation": "Successful"},
    {"family": "disposition", "reason": "needs_owner"},
    {"family": "disposition", "reason": "needs_owner", "explanation": ""},
    {"family": "run", "reason": "exit", "rc": True},
    {"family": "run", "reason": "exit", "rc": "1"},
    {"family": "run", "reason": "exit", "rc": 0},
    {"family": "run", "reason": "timeout", "timed_out": False},
    {"family": "run", "reason": "timeout", "timed_out": "true"},
    {"family": "run", "reason": "timeout", "deadline": "10"},
    {"family": "run", "reason": "timeout", "deadline": float("nan")},
    {"family": "run", "reason": "timeout", "deadline": float("inf")},
    {"family": "run", "reason": "exit", "leftovers": {"reason": "unsafe", "paths": []}},
    {"family": "answer", "reason": "valid"}, {"family": "answer", "reason": "validation_pending"},
    {"family": "answer", "reason": "missing", "failure": {"rule": "shape", "explanation": "Broken"}},
    {"family": "answer", "reason": "json_invalid", "failure": {"rule": "missing", "explanation": "Broken"}},
    {"family": "answer", "reason": "schema_invalid", "failure": {"rule": "json", "explanation": "Broken"}},
    {"family": "answer", "reason": "schema_invalid", "failure": {"rule": "unknown", "explanation": "Broken"}},
    {"family": "rejection", "reason": "committed"},
    {"family": "stuck", "reason": "hung"}, {"family": "stuck", "reason": "wait"},
    {"family": "stuck", "reason": "setup_failed", "rc": 1},
    {"family": "repeat", "leftovers": {"reason": "unknown", "paths": ["a"]}},
    {"family": "repeat", "leftovers": {"reason": "unsafe"}},
    {"family": "repeat", "leftovers": {"reason": "unsafe", "paths": [3]}},
    {"family": "repeat", "reason": "unsafe"},
    {"family": "merge", "reason": "running", "explanation": "Transient"},
    {"family": "merge", "reason": "unknown", "explanation": "Transient"},
    {"family": "merge", "reason": "git", "explanation": "Transient"},
    {"family": "merge", "reason": "target", "explanation": "Transient"},
    {"family": "merge", "reason": "expired"},
    {"family": "land", "reason": "main_moved", "explanation": "Transient"},
    {"family": "land", "reason": "conflict"},
    {"family": "land", "reason": "conflict", "explanation": "Stopped", "checks": [{"name": "x", "conclusion": "failed"}]},
    {"family": "round", "reason": "changed"},
    {"family": "round", "reason": "branch_moved", "deadline": 10},
])
def test_unknown_successful_transient_or_incompatible_agent_payloads(cause: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        event(cause)


@pytest.mark.parametrize("cause", [
    {"family": "checks"}, {"family": "checks", "reason": "passed"}, {"family": "checks", "reason": "unknown"},
    {"family": "checks", "reason": "main_moved", "setup": "failed"},
    {"family": "checks", "reason": "expired", "checks": [{"name": "x", "conclusion": "failed"}] * 2},
    {"family": "checks", "check": {"name": "x", "conclusion": "failed"},
     "checks": [{"name": "x", "conclusion": "timed_out"}]},
    {"family": "checks", "setup": "passed"}, {"family": "checks", "setup": "undefined"},
    {"family": "checks", "profile": "unknown"},
    {"family": "checks", "check": {"name": "x", "conclusion": "passed"}},
    {"family": "checks", "check": {"name": "x", "conclusion": "unknown"}},
    {"family": "checks", "check": {"name": "", "conclusion": "failed"}},
    {"family": "checks", "check": {"name": "x", "conclusion": "failed", "extra": 1}},
    {"family": "checks", "check": {"name": "x"}},
])
def test_invalid_checks_payloads(cause: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        event(cause, checks=True)


def stop() -> dict[str, object]:
    identity = {"pid": 20, "pgid": 20, "start": "start", "boot": "boot"}
    return {
        "attempt_id": "agent", "dispatch_token": "dispatch", "generation": 1,
        "entry": identity, "agent": identity, "cause": "deadline", "requested_signal": 15, "requested_at": 10.0,
    }


@pytest.mark.parametrize("cause", [
    {"family": "run", "reason": "timeout"}, {"family": "stuck", "reason": "entry_lost"},
])
def test_stop_attribution_and_optional_context_survive(cause: dict[str, object]) -> None:
    found = event(cause | {"stop": stop(), "rc": -15, "deadline": 9.5, "explanation": "Retained explanation"})
    assert decode(encode(found)) == found
    assert json.loads(encode(found))["cause"]["stop"]["cause"] == "deadline"


@pytest.mark.parametrize("reason_word", ["timeout", "credit_exhausted"])
def test_timeout_can_have_a_zero_return_code(reason_word: str) -> None:
    found = event({"family": "run", "reason": reason_word, "timed_out": True, "rc": 0})
    assert decode(encode(found)) == found


@pytest.mark.parametrize("changes", [
    {"attempt_id": "other"}, {"generation": True}, {"requested_at": float("inf")}, {"requested_at": "10"},
    {"requested_signal": "15"}, {"proof": {}}, {"phase": "reported"}, {"extra": True},
    {"entry": {"pid": "20", "pgid": 20, "start": "start", "boot": "boot"}},
])
def test_stop_context_is_validated_and_matches_causal_identity(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        event({"family": "run", "reason": "timeout", "stop": stop() | changes})


@pytest.mark.parametrize("cause", [
    {"family": "answer", "reason": "schema_invalid", "failure": {"rule": "paths_shape", "explanation": "Expected paths"}},
    {"family": "checks", "reason": "main_moved", "deadline": 12.0,
     "checks": [{"name": "tests", "conclusion": "failed", "log": "/evidence/tests.txt"}]},
    {"family": "repeat", "leftovers": {"reason": "unsafe", "paths": ["a.py", "b.py"]}},
    {"family": "merge", "reason": "unsupported_conflict", "explanation": "Binary conflict", "source": "source",
     "target": "main", "conflicts": ["image.png"]},
    {"family": "land", "reason": "checks_failed", "explanation": "Failed on main", "source": "source", "target": "main",
     "checks": [{"name": "tests", "conclusion": "failed", "log": "/evidence/tests.txt"}]},
])
def test_family_specific_structured_context_survives(cause: dict[str, object]) -> None:
    found = event(cause, checks=cause["family"] == "checks")
    assert decode(encode(found)) == found
    assert json.loads(encode(found))["cause"] | cause == json.loads(encode(found))["cause"]


@pytest.mark.parametrize("text", ["", "{", "[]", "null", '"failed:needs_owner"', '{"attempt_id": "agent"}'])
def test_decode_rejects_malformed_or_unstructured_input(text: str) -> None:
    with pytest.raises(ValueError):
        decode(text)
