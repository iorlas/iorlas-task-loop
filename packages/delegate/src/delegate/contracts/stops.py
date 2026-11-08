"""The stop facts of an answer: contract.json's reasons table (scope, permanence, retry kind, health effect) and the `stop` object built
from a row."""

import json
from pathlib import Path

from delegate.contracts.json_types import Json

CONTRACT_FILE = Path(__file__).resolve().parents[1] / "data" / "contract.json"


def load_contract() -> dict[str, Json]:
    with open(CONTRACT_FILE, encoding="utf-8") as f:
        data: dict[str, Json] = json.load(f)
    return data


CONTRACT = load_contract()
_RAW_REASONS = CONTRACT["reasons"]
REASONS: dict[str, dict[str, str]] = {
    name: {k: v for k, v in row.items() if isinstance(v, str)}
    for name, row in (_RAW_REASONS.items() if isinstance(_RAW_REASONS, dict) else [])
    if isinstance(row, dict)
}


def facts(reason: str | None) -> dict[str, str] | None:
    """-> the contract row of a reason (scope, permanence, retry kind, health effect), or None for a name contract.json does not list."""
    return REASONS.get(reason) if reason is not None else None


def benches_pair(reason: str | None) -> bool:
    """True when the reason may count against a (account, model) pair's health. bad_request is a caller fault: never (61 5.1)."""
    row = facts(reason)
    return row is not None and row["health"] in ("breaker", "exhausted")


def stop_facts(reason: str | None, retry_after: float | None = None, fix: str | None = None) -> dict[str, Json]:
    """-> the `stop` object an answer carries: {reason, scope, permanence, retry: {kind, at}}. An unknown reason still gets a row
    (open reasons, closed facts): machine / needs_owner / none."""
    row = facts(reason) or {"scope": "machine", "permanence": "needs_owner", "retry": "none"}
    perm, kind = row["permanence"], row["retry"]
    if retry_after and kind in (
        "none",
        "predicted",
    ):  # a time the account ends by itself: transient, whatever the table says for the general case
        perm, kind = "transient", "predicted"
    elif kind == "predicted":  # nothing to wait for: a person must act
        kind, perm = "none", "needs_owner"
    stop: dict[str, Json] = {
        "reason": reason,
        "scope": row["scope"],
        "permanence": perm,
        "retry": {"kind": kind, "at": retry_after if kind in ("predicted", "poll") else None},
    }
    if fix:
        stop["fix"] = fix
    return stop
