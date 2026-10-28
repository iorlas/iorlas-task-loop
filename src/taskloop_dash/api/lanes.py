"""The lanes: what delegate says about them (`route.py status --json`, never cached) and the lane records other tools publish under
agent-runs v1. task-loop never reads a vendor."""

import glob
import json
import math
import subprocess
import sys
import time
from typing import Any, Final

from taskloop_dash.env import Env
from taskloop_dash.tails import read_dict
from taskloop_dash.views import names

LOGIN_CMD: Final = {"Codex": "codex login", "Grok": "opencode auth login"}
LANE_RECORD_MAX_AGE = 6 * 3600


def logged_out(notes: str) -> bool:
    low = notes.lower()
    return "logged out" in low or "logged_out" in low or "not logged in" in low


def lane_banners(j: dict[str, Any], now: float | None = None) -> dict[str, dict[str, Any]]:
    """name -> {until, reason, text} for each lane of `route.py status --json` that stops an unattended run. A credit lane that is
    out, a lane only busy (all slots taken), or unknown subscription use, does not: no banner."""
    now = time.time() if now is None else now
    out: dict[str, dict[str, Any]] = {}
    for n, ln in (j.get("lanes") or {}).items():
        if not isinstance(ln, dict) or ln.get("kind") == "credit" or ln.get("reason") == "busy":
            continue
        notes = " ".join(str(x) for x in ln.get("notes") or [])
        gone = ln.get("reason") == "logged_out" or (ln.get("out") and logged_out(notes))
        if not (ln.get("out") or gone):
            continue
        who = names.lane_name(n, ln.get("family") or "") or str(n).lower()
        until = ln.get("out_until")
        if gone:
            text = "%s logged out: run %s" % (who, LOGIN_CMD.get(who, "claude auth login"))
        else:
            past = until and until < now  # delegate still says out after its own end: say so, never a bare old time
            text = "%s out%s" % (who, (" (its end, %s, has passed)" % names.when(until)) if past
                                 else (" until " + names.when(until)) if until else "")
        out[n] = {"until": until, "reason": "logged_out" if gone else ln.get("reason"), "text": text}
    return out


def status_lanes(j: object) -> dict[str, dict[str, Any]]:
    """name -> lane record of a `route.py status --json` answer, in delegate's own order: its v1 dict, or the named list
    agent-runs v1 records carry."""
    lanes = j.get("lanes") if isinstance(j, dict) else None
    if isinstance(lanes, dict) and all(isinstance(ln, dict) for ln in lanes.values()):
        return {str(n): ln for n, ln in lanes.items()}
    if isinstance(lanes, list) and all(isinstance(ln, dict) and isinstance(ln.get("name"), str) and ln["name"] for ln in lanes):
        named = {ln["name"]: ln for ln in lanes}
        if len(named) == len(lanes):
            return named
    raise ValueError("invalid lanes")


def _number(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def cockpit_usage(ln: dict[str, Any]) -> list[dict[str, Any]]:
    """The lane's usage windows: delegate's `usage` list, plus the bare `five`/`week` percentages older answers carry."""
    supplied = ln.get("usage")
    usage = [{"window": str(u.get("window") or "?"), "used_pct": u.get("used_pct"), "resets_at": u.get("resets_at")}
             for u in (supplied if isinstance(supplied, list) else []) if isinstance(u, dict)]
    for u in usage:
        if not _number(u["used_pct"]):
            u["used_pct"] = None
    for key, window in (("five", "5h"), ("week", "week")):
        if _number(ln.get(key)) and not any(u["window"] == window for u in usage):
            usage.append({"window": window, "used_pct": ln[key]})
    return usage


def cockpit_lanes(j: dict[str, Any]) -> list[dict[str, Any]]:
    """One record per lane for the cockpit: only what delegate said, in its order."""
    return [{"name": n, "family": ln.get("family"), "kind": ln.get("kind"), "model": ln.get("model"),
             "emoji": ln.get("emoji"), "out": ln.get("out"), "out_until": ln.get("out_until"),
             "reason": ln.get("reason", ln.get("why")),
             "notes": [str(x) for x in ln.get("notes") or []], "usage": cockpit_usage(ln)}
            for n, ln in status_lanes(j).items()]


def _check_lanes(lanes: dict[str, dict[str, Any]]) -> None:
    for ln in lanes.values():
        until = ln.get("out_until")
        if until is not None and not _number(until):
            raise ValueError("invalid unlock time")
        if until is not None:
            names.when(until)  # finite numbers can still exceed the platform's timestamp range
        if ln.get("out") is not None and not isinstance(ln["out"], bool):
            raise ValueError("invalid lane state")
        if ln.get("notes") is not None and not isinstance(ln["notes"], list):
            raise ValueError("invalid lane notes")


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
        """The banner and the cockpit: what delegate says about its lanes (route.py status --json v1). `status --json` only
        reports, it spends no quota. Never cached: the page polls every 2.5 s."""
        routes = glob.glob(str(self.env.home / ".claude/plugins/cache/*/iorlas-delegate/*/skills/delegate/route.py"))
        if not routes:
            return {"ok": False, "say": "delegate is not installed"}

        def version_of(p: str) -> list[int]:
            return [int(x) if x.isdigit() else 0 for x in p.split("/iorlas-delegate/")[1].split("/")[0].split(".")]
        try:
            r = subprocess.run([sys.executable, max(routes, key=version_of), "status", "--json"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
        except (OSError, subprocess.SubprocessError) as e:  # it never ran, or never answered
            return {"ok": False, "say": "delegate status failed: %s" % e}
        if isinstance(r.returncode, int) and r.returncode != 0:
            err = ((r.stderr or "").strip().splitlines() or [""])[-1][:200]
            return {"ok": False, "say": "delegate status exited %d%s" % (r.returncode, ": " + err if err else "")}
        text = (r.stdout or "").strip()
        j = None
        if "{" in text:
            try:
                j = json.loads(text[text.index("{"):])  # one object, pretty-printed or not
            except ValueError:
                j = None
        if not isinstance(j, dict):
            return {"ok": False, "say": "delegate status printed no JSON status"}
        try:
            lanes = status_lanes(j)
            _check_lanes(lanes)
        except (ValueError, OverflowError, OSError) as e:
            return {"ok": False, "say": "delegate status malformed: %s" % e}
        det = lane_banners({"lanes": lanes}, self.env.clock())
        return {"ok": not det, "out": sorted(det), "detail": det, "needs_input": j.get("needs_input") or [],
                "lanes": cockpit_lanes(j), "at": self.env.clock()}
