"""The Snapshot's lane cards, built from the StatusSnapshot `tl lanes` filed (delegate's status, read once there). Pure: no file, no
process.

Filled: `state` (`stale` when the snapshot is older than STATUS_MAX_AGE, else `locked` only when the lane's typed `out` is set, else
delegate's lane state with its locked words read as `watch`), `name` / `plan` (the typed `family` / `kind`), `window_pct` / `week_pct` (the
contract's typed `five` / `week`; delegate's `windows[].name` is a free string and is never read for meaning), `locked_until`,
`model`, `status_t`. Unset: `resets_at` and `forecast_pct` (delegate's contract types no reset time for
`five` / `week`; the history keeps each window's own `resets_at`, and `usage.forecast` projects it once a typed reset exists),
`forecast`, `slots`, `running`, `waiting`."""

from typing import Final, Literal

from taskloop.contracts.dash import LaneCard
from taskloop.contracts.snapshots import LaneStatus, StatusSnapshot

STATUS_MAX_AGE: Final = 3600  # a snapshot older than this greys every card
State = Literal["ok", "watch", "locked", "stale"]
# delegate's `cockpit.lanes[].state` enum (contract.json status_schema); a state it adds later reads `watch`, never `ok`
STATE: Final[dict[str, State]] = {
    "ready": "ok", "slow": "watch", "unknown": "watch", "resting": "locked", "logged_out": "locked", "spend": "locked", "off": "locked"}


def state_of(ln: LaneStatus, age_s: float) -> State:
    """`stale` beats everything; `locked` only when the lane is out (never on delegate's state word alone)."""
    if age_s > STATUS_MAX_AGE:
        return "stale"
    if ln.out:
        return "locked"
    st = STATE.get(ln.state, "watch")
    return "watch" if st == "locked" else st


def lane_cards(snap: StatusSnapshot | None, now: float) -> list[LaneCard]:
    if snap is None:
        return []
    out: list[LaneCard] = []
    for ln in snap.lanes:
        st = state_of(ln, now - snap.at)
        out.append(LaneCard(
            id=ln.id, name=ln.family or ln.label or ln.id, plan=ln.kind, state=st, model=ln.model, window_pct=ln.five,
            week_pct=ln.week, locked_until=ln.out_until if st == "locked" else None, status_t=snap.at))
    return out
