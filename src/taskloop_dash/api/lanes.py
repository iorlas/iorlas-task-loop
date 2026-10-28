"""The lanes: what delegate says about them (the StatusSnapshot `tl lanes` / `tl usage` file; the dash runs nothing) and the
lane records other tools publish under agent-runs v1. task-loop never reads a vendor."""

import glob
from typing import Any, Final

from taskloop.contracts.snapshots import LaneStatus
from taskloop.contracts.stores import StatusStore
from taskloop_dash.env import Env
from taskloop_dash.tails import read_dict
from taskloop_dash.views import names

LOGIN_CMD: Final = {"Codex": "codex login", "Grok": "opencode auth login"}
LANE_RECORD_MAX_AGE = 6 * 3600
STATUS_MAX_AGE = 3600  # a snapshot older than this is said to be old, never shown as the lanes' state


def logged_out(notes: str) -> bool:
    low = notes.lower()
    return "logged out" in low or "logged_out" in low or "not logged in" in low


def lane_banners(lanes: list[LaneStatus], now: float) -> dict[str, dict[str, Any]]:
    """name -> {until, reason, text} for each lane that stops an unattended run. A credit lane that is out, a lane only busy (all
    slots taken), or unknown subscription use, does not: no banner."""
    out: dict[str, dict[str, Any]] = {}
    for ln in lanes:
        if ln.kind == "credit" or ln.out_reason == "busy":
            continue
        gone = ln.out_reason == "logged_out" or (ln.out and logged_out(" ".join(ln.notes)))
        if not (ln.out or gone):
            continue
        who = names.lane_name(ln.id, ln.family) or ln.id.lower()
        until = ln.out_until
        if gone:
            text = "%s logged out: run %s" % (who, LOGIN_CMD.get(who, "claude auth login"))
        else:
            past = until and until < now  # delegate still says out after its own end: say so, never a bare old time
            text = "%s out%s" % (who, (" (its end, %s, has passed)" % names.when(until)) if past
                                 else (" until " + names.when(until)) if until else "")
        out[ln.id] = {"until": until, "reason": "logged_out" if gone else ln.out_reason, "text": text}
    return out


OUT_STATES: Final = ("resting", "logged_out", "spend")


def card(ln: LaneStatus) -> dict[str, Any]:
    """One lane as the cockpit card reads it."""
    return {"name": ln.id, "label": ln.label, "family": ln.family, "kind": ln.kind, "model": ln.model, "emoji": ln.emoji,
            "state": ln.state, "out": ln.state in OUT_STATES, "out_until": ln.unlock_at, "reason": ln.reason, "notes": ln.warnings,
            "usage": [{"window": w.name, "used_pct": w.used_pct, "resets_at": w.resets_at} for w in ln.windows]}


class Lanes:
    def __init__(self, env: Env) -> None:
        self.env = env

    def contract_lanes(self) -> list[dict[str, Any]]:
        """Lane records under agent-runs v1, fresh ones only."""
        out: list[dict[str, Any]] = []
        for f in glob.glob(str(self.env.agent_runs / "lanes" / "*.json")):
            r = read_dict(f)
            if r.get("v") != 1 or self.env.clock() - float(r.get("at") or 0) > LANE_RECORD_MAX_AGE:
                continue
            for ln in r.get("lanes") or []:
                if isinstance(ln, dict) and ln.get("name"):
                    out.append({"producer": r.get("producer"), "name": ln["name"], "out_until": ln.get("out_until"),
                                "why": ln.get("why"), "usage": [u for u in ln.get("usage") or [] if isinstance(u, dict)]})
        return out

    def delegate_status(self) -> dict[str, Any]:
        """The banner and the cockpit: the StatusSnapshot that `tl lanes` / `tl usage` filed (delegate's status, read once there).
        Nothing is run here; a missing or old snapshot says so."""
        snap = StatusStore(self.env.config).read()
        if snap is None:
            return {"ok": False, "say": "no delegate status filed yet: run tl lanes"}
        now = self.env.clock()
        if now - snap.at > STATUS_MAX_AGE:
            return {"ok": False, "say": "delegate status is %s old: run tl lanes" % "%d min" % ((now - snap.at) // 60)}
        det = lane_banners(snap.lanes, now)
        return {"ok": not det, "out": sorted(det), "detail": det,
                "needs_input": [{"what": n.what, "why": n.why, "how": n.how} for n in snap.needs_input],
                "lanes": [card(ln) for ln in snap.lanes], "at": snap.at}
