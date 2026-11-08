"""delegate's status answer (v 1) read into a StatusSnapshot. The one reader of that shape: a key delegate
renames or drops fails here, and tests/adapters/test_delegate_status.py runs it on a real answer."""
import math
from typing import Any

from tlkernel.snapshots import AccountStatus, NeedInput, StatusSnapshot, WindowStatus


def _num(v: object) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None


def _dict(v: object, what: str) -> dict[str, Any]:
    if not isinstance(v, dict):
        raise ValueError(f"delegate status: {what} is not an object")
    return v


def _strings(v: object) -> list[str]:
    return [str(x) for x in v] if isinstance(v, list) else []


def snapshot_of(j: object) -> StatusSnapshot:
    """Raises ValueError when the answer lacks `ts`, `accounts`, `cockpit.accounts` (each row with `id`, `state`) or an account's `out`."""
    top = _dict(j, "the answer")
    at = _num(top.get("ts"))
    if at is None:
        raise ValueError("delegate status: no ts")
    flat = _dict(top.get("accounts"), "accounts")
    rows = _dict(top.get("cockpit"), "cockpit").get("accounts")
    if not isinstance(rows, list):
        raise ValueError("delegate status: cockpit.accounts is not a list")
    accounts: list[AccountStatus] = []
    for row in rows:
        r = _dict(row, "a cockpit account")
        if not isinstance(r.get("id"), str) or not isinstance(r.get("state"), str):
            raise ValueError("delegate status: a cockpit account has no id or state")
        old = _dict(flat.get(r["id"], {}), "account " + r["id"])
        if not isinstance(old.get("out", False), bool):
            raise ValueError("delegate status: account out is not a bool")
        unlock = r.get("unlock") if isinstance(r.get("unlock"), dict) else {}
        reason = old.get("reason")
        accounts.append(AccountStatus(
            id=r["id"], label=str(r.get("label") or ""), family=str(r.get("family") or ""), kind=str(r.get("kind") or ""),
            model=str(r.get("model") or ""), state=r["state"], emoji=str(r.get("emoji") or ""), reason=str(r.get("reason") or ""),
            unlock_at=_num(unlock.get("at")), warnings=_strings(r.get("warnings")),
            windows=[WindowStatus(name=str(w.get("name") or "?"), used_pct=_num(w.get("used_pct")), resets_at=_num(w.get("resets_at")))
                     for w in r.get("windows") or [] if isinstance(w, dict)],
            five=_num(old.get("five")), week=_num(old.get("week")),
            out=bool(old.get("out")), out_until=_num(old.get("out_until")), out_reason=reason if isinstance(reason, str) else None,
            notes=_strings(old.get("notes"))))
    need = [NeedInput(what=str(n.get("what") or ""), why=str(n.get("why") or ""), how=str(n.get("how") or ""))
            for n in top.get("needs_input") or [] if isinstance(n, dict)]
    return StatusSnapshot(at=at, accounts=accounts, needs_input=need)
