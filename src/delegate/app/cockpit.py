"""The cockpit: one row per known lane (state, reason, unlock time, windows, model), the pick `next worker` would make, and the text of it.
`lane_view` is pure given its inputs."""

from collections.abc import Sequence
from typing import Final, NamedTuple

from any_agent.classify import limit_words as window_words
from any_agent.classify import says_login, says_spend
from any_agent.harnesses.opencode import OpenCodeHarness

from delegate.app import env, harnesses, onboard, usage
from delegate.app.decide import busy_jitter
from delegate.app.fleet import mark_busy
from delegate.contracts.json_types import Json, arr, as_num, as_str, obj
from delegate.contracts.routing import CallArgs, Settings
from delegate.contracts.state import OutState, StateDoc
from delegate.domain.holds.book import HoldBook
from delegate.domain.lanes.lane import Lane
from delegate.domain.lanes.leases import LeaseBook
from delegate.domain.lanes.profiles import LOGIN_CMD
from delegate.domain.routing.router import Router
from delegate.domain.time.spec import fmt_in, local, when

Login = tuple[bool | None, str, float | None]  # (ok, why, checked_at)
NO_SANDBOX = "unavailable (no sandbox): opencode lanes need macOS sandbox-exec"


def needs_input(lanes: dict[str, Lane]) -> list[dict[str, Json]]:
    need: list[dict[str, Json]] = []
    cs = lanes.get("CLAUDE_SUBSCRIPTION")
    if cs and not cs.usage_known and env.session_host() == "desktop":
        need.append(
            {
                "what": "claude_usage",
                "why": "Claude subscription use is unknown",
                "how": "in the Claude desktop app call the get_usage tool and pass its windows as --claude-usage JSON "
                "({five_hour:{used,resets_at},weekly:{used,resets_at}})",
            }
        )
    ox = lanes.get("OPENAI_SUBSCRIPTION")
    if ox and not ox.usage_known and not ox.out:
        need.append(
            {
                "what": "codex_login",
                "why": ox.notes[0] if ox.notes else "codex limits unreadable",
                "how": "ask the user to run `codex login`, or report the lane out with `route.py report`",
            }
        )
    return need


def finished_runs(n: int) -> list[dict[str, Json]]:
    """The last n finished runs, newest last: the dashboard's view of history.jsonl (the file itself stays private)."""
    keys = ("run_id", "ts", "role", "task", "lane", "model", "done", "outcome", "secs", "cost", "tokens", "denials")
    return [{k: getattr(r, k) for k in keys} for r in env.history_store().runs(n)]


EMOJI: Final = {"ready": "✅", "resting": "⏳", "logged_out": "🔑", "spend": "💸", "slow": "🐢", "off": "⛔", "unknown": "❓"}
LEGEND: Final = {
    "ready": "ready",
    "resting": "usage limit",
    "logged_out": "logged out",
    "spend": "spend/credit limit",
    "slow": "slow/hung",
    "off": "disabled",
    "unknown": "no read yet",
}
LABELS: Final = {
    "CLAUDE_SUBSCRIPTION": "Claude subscription",
    "OPENAI_SUBSCRIPTION": "ChatGPT / Codex",
    "GROK_SUBSCRIPTION": "SuperGrok / OpenCode",
    "DEEPSEEK_FREE": "DeepSeek / OpenCode Free",
    "ZAI_CODING_SUBSCRIPTION": "Z.ai GLM Coding Plan",
}
SLOW_WINDOW = 2 * 3600  # a hang or timeout this recent, with no good run on the lane since, keeps it marked slow
SLOW_KINDS = ("hung", "timeout")


def login_state(name: str, st: StateDoc, t: float) -> Login:
    """-> (ok, why, checked_at): probe_login cached a few minutes in state, so a status call costs one process per lane at most."""
    c = usage.auth_cache().fresh(name, t, usage.AUTH_TTL, st)
    if c:
        return c.ok, c.why, c.at
    ok, why = harnesses.probe_login(name)
    usage.auth_cache().remember(name, ok, why, t)
    return ok, why, t


def lane_model(cfg: dict[str, Json], name: str) -> str | None:
    """'model effort' the lane's family gets in the worker role (else the first role that uses the family, else its first model)."""
    fam = obj(obj(cfg["lanes"])[name])["family"]
    roles = obj(cfg["roles"])
    for role in [roles.get("worker"), *roles.values()]:
        for raw_step in arr(obj(role).get("steps", [])):
            step = obj(raw_step)
            if step.get("on") == fam:
                return f"{step['model']} {step['effort']}"
    return next((m for m, v in obj(cfg["models"]).items() if obj(v)["family"] == fam), None)


def off_reason(name: str, cfg: dict[str, Json], login: Login) -> str:
    if obj(obj(cfg["lanes"])[name]).get("opt_in") and env.profile_lanes().get(name) != "enabled":
        return f"disabled: `route.py config set profile.lanes.{name} enabled` turns it on"
    if env.profile_lanes().get(name) == "declined":
        return "declined: remove it from the profile in config.json to bring it back"
    if name in onboard.OPENCODE_LANES and not OpenCodeHarness.supported():
        return NO_SANDBOX
    if login[0] is False:
        return f"not configured: logged out, run `{LOGIN_CMD[name]}`"
    return "not configured: `route.py doctor` says what it needs" + (f" ({login[1]})" if login[0] is None and login[1] else "")


def classify_out(lane: Lane, rec: OutState | None) -> str:
    """Why a lane that is out is out -> logged_out | spend | slow | resting. rec is its state.json entry (older ones have no typed
    reason)."""
    r = lane.out_reason
    text = " ".join([rec.why if rec else "", *lane.notes])
    if r == "logged_out" or (r in (None, "error") and says_login(text)):
        return "logged_out"
    if lane.spend_blocked or says_spend(text):
        return "spend"
    if r == "hung":
        return "slow"
    return "resting"


def limit_words(text: str, lane: Lane) -> str:
    scored = [(u, w) for w in lane.windows if (u := as_num(w["used"])) is not None]
    top = max(scored, key=lambda p: p[0], default=None)
    return window_words(text, as_str(top[1]["name"]) if top and top[0] >= 95 else None)


def window_rows(lane: Lane, S: Settings, t: float) -> tuple[list[dict[str, Json]], list[dict[str, Json]]]:
    rows: list[dict[str, Json]] = []
    low: list[dict[str, Json]] = []
    for w in lane.windows:
        used, resets_at, at = as_num(w["used"]), as_num(w["resets_at"]), as_num(w["at"])
        rows.append(
            {
                "name": w["name"],
                "used_pct": None if used is None else round(used, 1),
                "resets_at": w["resets_at"],
                "resets_in_s": None if not resets_at else max(0, int(resets_at - t)),
                "source": w["source"],
                "age_s": None if at is None else max(0, int(t - at)),
            }
        )
        if used is None:
            continue
        (gwk, gfv, gname), (cwk, cfv, _) = lane.limits(S, False), lane.limits(S, True)
        gate, ceil = (gwk, cwk) if (as_num(w["span"]) or 0) > 1440 else (gfv, cfv)
        if used >= gate:
            low.append(
                {
                    "window": w["name"],
                    "used_pct": round(used, 1),
                    "limit": ceil if used >= ceil else gate,
                    "over": "ceiling" if used >= ceil else "gate",
                    "limit_name": "hard ceiling" if used >= ceil else gname,
                }
            )
    return rows, low


class Verdict(NamedTuple):
    """What a lane in use is: its state, the sentence for it, when it unlocks and why not."""

    state: str
    note: str
    why: str
    until: float | None
    locked: bool
    detail: str | None


def _out_verdict(name: str, lane: Lane, rec: OutState | None, login: Login) -> Verdict:
    kind = classify_out(lane, rec)
    text = (rec.why if rec else "") or (lane.notes[0] if lane.notes else "")
    detail = text[:160] or None
    until = lane.out_until
    if kind == "logged_out" or login[0] is False:
        why = f"waits for you to log in (`{LOGIN_CMD[name]}`); re-checked every {usage.AUTH_TTL // 60} min"
        return Verdict("logged_out", f"logged out: run `{LOGIN_CMD[name]}`", why, None, True, detail)
    if kind == "spend":
        note = "spending limit: " + (text[:70] or "credits used up")
        return Verdict(kind, note, "a spending limit has no timer: it ends when you top up or the cycle resets", until, True, detail)
    if kind == "slow":
        note = "hung: no output inside the watchdog window, benched for a while"
        return Verdict(kind, note, "the watchdog gave no end time", until, True, detail)
    return Verdict(kind, limit_words(text, lane), "the vendor gave no reset time", until, True, detail)


def _idle_verdict(
    name: str, lane: Lane, t: float, history: Sequence[dict[str, Json]], login: Login, meter: bool, low: list[dict[str, Json]]
) -> Verdict:
    last = next((h for h in reversed(history) if h.get("lane") == name), None)
    last_ts = as_num(last.get("ts")) if last else None
    if last and last.get("outcome") in SLOW_KINDS and t - (last_ts or 0) <= SLOW_WINDOW:
        note = f"hung {fmt_in(t - (last_ts or 0))} ago ({last['outcome']}), no good run since"
        return Verdict("slow", note, "not locked: it clears with its next good run", None, False, None)
    if login[0] is None or (meter and not lane.usage_known):
        note = "no read yet: " + (login[1] if login[0] is None and login[1] else (lane.notes[0] if lane.notes else "no usage reading"))
        return Verdict("unknown", note, "not locked", None, False, None)
    note = "ready" + ("" if meter else ", vendor shows no usage (a limit appears only when hit)")
    if low:
        lt = low[0]
        note = f"ready, low tokens: {lt['window']} {lt['used_pct']:.0f}% is over the {lt['limit_name']} {lt['limit']}%, last choice only"
    return Verdict("ready", note, "not locked", None, False, None)


def _verdict(
    name: str,
    lane: Lane,
    S: Settings,
    st: StateDoc,
    t: float,
    history: Sequence[dict[str, Json]],
    login: Login,
    meter: bool,
    low: list[dict[str, Json]],
) -> Verdict:
    if lane.out:
        return _out_verdict(name, lane, st.out.get(name), login)
    if login[0] is False:
        why = f"waits for you to log in (`{LOGIN_CMD[name]}`); re-checked every {usage.AUTH_TTL // 60} min"
        return Verdict("logged_out", f"logged out: run `{LOGIN_CMD[name]}`", why, None, True, None)
    if not lane.usable(S, True)[0]:  # over the hard ceiling with nothing recorded: resting until that window resets
        return Verdict("resting", lane.usable(S, True)[1], "no reset time for the window it is over", lane.back_at(S), True, None)
    return _idle_verdict(name, lane, t, history, login, meter, low)


def lane_view(
    name: str,
    cfg: dict[str, Json],
    lane: Lane | None,
    st: StateDoc,
    t: float,
    history: Sequence[dict[str, Json]] = (),
    running: int = 0,
    login: Login = (None, "", None),
    off_why: str | None = None,
) -> dict[str, Json]:
    """One lane's cockpit row. Pure given its inputs: lane is what gather built (None = disabled or not configured), history the recent
    finished runs."""
    S, c = env.settings_of(cfg), obj(obj(cfg["lanes"])[name])
    meter = c["reader"] != "none"
    v: dict[str, Json] = {
        "id": name,
        "label": c.get("label") or LABELS.get(name, name),
        "family": c["family"],
        "kind": c["kind"],
        "model": lane_model(cfg, name),
        "state": "off",
        "emoji": EMOJI["off"],
        "reason": off_why or "disabled or not configured",
        "detail": None,
        "unlock": {"locked": False, "known": False, "at": None, "in_s": None, "text": None, "why": "not in use"},
        "windows": [],
        "low_tokens": [],
        "warnings": list(lane.warn) if lane else [],
        "meter": meter,
        "login": {"ok": login[0], "why": login[1], "checked_at": login[2]},
        "running": running,
    }
    if lane is None:
        return v
    windows, low = window_rows(lane, S, t)
    v["windows"], v["low_tokens"] = windows, low
    verdict = _verdict(name, lane, S, st, t, history, login, meter, low)
    v["detail"] = verdict.detail
    v["state"], v["emoji"], v["reason"] = verdict.state, EMOJI[verdict.state], verdict.note
    if verdict.until and verdict.until > t and verdict.state != "logged_out":
        v["unlock"] = {
            "locked": True,
            "known": True,
            "at": verdict.until,
            "in_s": int(verdict.until - t),
            "text": when(verdict.until, t),
            "why": None,
        }
    else:
        v["unlock"] = {"locked": verdict.locked, "known": False, "at": None, "in_s": None, "text": None, "why": verdict.why}
    return v


def claude_why(cfg: dict[str, Json], lanes: dict[str, Lane]) -> str:
    """Why no non-Claude worker lane was usable when a Claude lane got the pick: 'OPENAI_SUBSCRIPTION out until ..; ZAI_CODING_SUBSCRIPTION
    not set up'."""
    S = env.settings_of(cfg)
    fams = {on for s in arr(obj(obj(cfg["roles"])["worker"])["steps"]) if (on := obj(s)["on"]) != "claude"}
    parts = []
    for name, c in obj(cfg["lanes"]).items():
        if obj(c)["family"] not in fams:
            continue
        ln = lanes.get(name)
        parts.append(f"{name} " + ("not set up" if ln is None else ln.usable(S, True)[1]))
    return "; ".join(parts) or "no other lane exists"


def next_worker(cfg: dict[str, Json], lanes: dict[str, Lane], st: StateDoc, t: float) -> dict[str, Json]:
    """The lane `next worker` would pick now: decide() on a copy, nothing written."""
    routing = env.typed_routing(cfg)
    cur = mark_busy(lanes, st, routing.settings, t, busy_jitter)
    d = Router(routing, HoldBook(st.holds), st.prev, t).route("worker", CallArgs(), cur).as_dict()
    if d["action"] == "run":
        r: dict[str, Json] = {
            "action": "run",
            "lane": d["lane"],
            "model": d["model"],
            "effort": d["effort"],
            "pass": d["pass"],
            "fallback": d["fallback"],
            "why": None,
        }
        if obj(obj(cfg["lanes"])[as_str(d["lane"])])["family"] == "claude":
            r["why"] = claude_why(cfg, cur)
        return r
    return {"action": d["action"], "lane": d.get("lane"), "model": None, "effort": None, "say": d.get("say") or d.get("error")}


def cockpit(cfg: dict[str, Json], lanes: dict[str, Lane], st: StateDoc, t: float) -> dict[str, Json]:
    """The cockpit dict: one row per known lane, configured or not, plus the pick `next worker` would make."""
    hist = finished_runs(60)
    book = LeaseBook(st.leases)
    rows: list[Json] = []
    for name in obj(cfg["lanes"]):
        lane = lanes.get(name)
        login = login_state(name, st, t)
        off = off_reason(name, cfg, login) if lane is None else None
        rows.append(lane_view(name, cfg, lane, st, t, hist, book.counts(name, t)["live"], login, off))
    return {"v": 1, "at": t, "legend": {EMOJI[k]: LEGEND[k] for k in EMOJI}, "next_worker": next_worker(cfg, lanes, st, t), "lanes": rows}


def cockpit_text(ck: dict[str, Json]) -> list[str]:
    t, nw = as_num(ck["at"]) or 0.0, obj(ck["next_worker"])
    rows = [obj(r) for r in arr(ck["lanes"])]
    pick = f"{nw['lane']} {nw['model']} {nw['effort']}" if nw["action"] == "run" else f"none ({as_str(nw.get('say') or nw['action'])[:60]})"
    width = max(len(as_str(r["id"])) for r in rows)
    mw = max(len(as_str(r["model"]) or "-") for r in rows)
    if nw.get("why"):
        pick += f" (Claude because {nw['why']})"
    nw_ = max([6] + [len(as_str(obj(w)["name"])) for r in rows for w in arr(r["windows"])])
    out = [f"delegate lanes, {local(t)}   next worker: {pick}"]
    for r in rows:
        out.append(f"{r['emoji']} {as_str(r['id']):<{width}}  {(as_str(r['model']) or '-'):<{mw}}  {r['reason']}")
        u = obj(r["unlock"])
        if u["locked"]:
            out.append("     " + ("unlocks " + as_str(u["text"]) if u["known"] else "unlock time unknown: " + as_str(u["why"])))
        for win in arr(r["windows"]):
            w = obj(win)
            used_pct, resets_at, age_s = as_num(w["used_pct"]), as_num(w["resets_at"]), as_num(w["age_s"])
            used = "?" if used_pct is None else f"{used_pct:.0f}%"
            reset = f", resets {when(resets_at, t)}" if resets_at and resets_at > t else ""
            age = "" if age_s is None else f", {fmt_in(age_s)} old" if age_s >= 60 else ", just now"
            out.append(f"     {as_str(w['name']):<{nw_}} {used:>4} used{reset}  [{w['source']}{age}]")
        out.extend("     ! " + as_str(x) for x in arr(r["warnings"]))
    run = [r for r in rows if r["running"]]
    if run:
        out.append("running: " + ", ".join(f"{r['id']} x{r['running']}" for r in run))
    out.append("  ".join(f"{k} {v}" for k, v in obj(ck["legend"]).items()))
    return out
