"""The usage readers: each fills a Lane's windows, five-hour and weekly use, and out mark from what its vendor lets us read. FleetBuilder
calls them
by the `reader` key of the lane in routing.json (READERS). Also the login cache that `status`, `next` and a run share."""

import os
from collections.abc import Callable

from timefmt import fmt_span

from delegate.adapters import statusline
from delegate.adapters.codex_account import rate_limits as fetch_codex_limits
from delegate.adapters.harness.claude import ClaudeHarness
from delegate.app import env, harnesses
from delegate.app.fleet import AuthCache
from delegate.contracts.json_types import Json, as_num, as_str, obj
from delegate.contracts.routing import Settings
from delegate.contracts.state import StateDoc, UsageCache
from delegate.domain.lanes.lane import Lane, apply_burn, window
from delegate.domain.time.spec import WEEK_MIN, local, next_weekly, to_epoch


def remembering(attr: str, cache: UsageCache) -> Callable[[StateDoc], None]:
    """The state change that stores a usage reading under `attr`."""

    def put(s: StateDoc) -> None:
        setattr(s, attr, cache)

    return put


def binding(group: list[dict[str, Json]]) -> dict[str, Json]:
    """The window closest to its limit binds."""
    return max(group, key=lambda w: as_num(w.get("usedPercent")) or 0, default={})


def span_name(mins: float) -> str:
    return "5-hour" if mins <= 360 else "daily" if mins <= 1500 else "weekly" if mins <= 14400 else "monthly"


def add_window(
    lane: Lane, used: float | None, resets_at: float | None, span: float, source: str, at: float | None, bucket: str | None = None
) -> None:
    if used is not None or resets_at is not None:
        lane.windows.append(
            {
                "name": (bucket + " " if bucket else "") + span_name(span),
                "used": used,
                "resets_at": resets_at,
                "span": span,
                "source": source,
                "at": at,
            }
        )


def codex_buckets(res: dict[str, Json]) -> list[tuple[str, str, dict[str, Json]]]:
    """-> [(bucket id, label, bucket dict)]: the top-level rateLimits plus every rateLimitsByLimitId entry (per-model limits), each once."""
    rl = obj(res.get("rateLimits"))
    out: dict[str, Json] = {as_str(rl.get("limitId")) or "codex": rl}
    for k, b in obj(res.get("rateLimitsByLimitId")).items():
        out.setdefault(k, b)
    return [(k, as_str(b.get("limitName")) or k, b) for k, b in out.items() if isinstance(b, dict)]


def _mins(w: dict[str, Json]) -> float:
    return as_num(w.get("windowDurationMins")) or 300


def read_codex(lane: Lane, S: Settings, st: StateDoc, t: float, ai_usage: Json = None) -> None:
    cached = st.codex_limits
    if cached and t - cached.at <= 60 and not os.environ.get("DELEGATE_NOCACHE"):
        res, err = (cached.data if isinstance(cached.data, dict) else None), None
    else:
        res, err = fetch_codex_limits()
        if res is not None:
            env.update_state(remembering("codex_limits", UsageCache(at=t, data=res)))
    if res is None:
        lane.notes.append(err or "")
        return
    lane.read_at = cached.at if cached and res is cached.data else t
    rl = obj(res.get("rateLimits"))
    # (bucket label, window): every window of every bucket, by length not by slot (Pro Lite sends its only, weekly, window as primary)
    ws: list[tuple[str | None, dict[str, Json]]] = []
    for bid, label, b in codex_buckets(res):
        for w in (b.get("primary"), b.get("secondary")):
            if w and isinstance(w, dict):
                ws.append((None if bid == (as_str(rl.get("limitId")) or "codex") else label, w))
    for label, w in ws:
        span = _mins(w)
        used, resets = as_num(w.get("usedPercent")), as_num(w.get("resetsAt"))
        add_window(lane, window(used, resets, span, t)[0], resets, span, "live read (codex app-server)", lane.read_at, label)
    lane.spend_blocked = bool(rl.get("spendControlReached")) or any(
        w in str(rl.get("rateLimitReachedType") or "").lower() for w in ("credit", "spend")
    )
    pr = binding([w for _, w in ws if _mins(w) <= 1440])
    se = binding([w for _, w in ws if _mins(w) > 1440])
    lane.five_reset, lane.week_reset = as_num(pr.get("resetsAt")), as_num(se.get("resetsAt"))
    lane.five, _, _ = window(as_num(pr.get("usedPercent")), lane.five_reset, _mins(pr), t)
    lane.week, wmins, lane.pace = window(
        as_num(se.get("usedPercent")), lane.week_reset, as_num(se.get("windowDurationMins")) or WEEK_MIN, t
    )
    apply_burn(lane, S, wmins)
    if rl.get("rateLimitReachedType") or res.get("ordinaryUsageAllowed") is False or (lane.five or 0) >= 98 or (lane.week or 0) >= 98:
        lane.out, lane.out_reason = True, "limit"
        resets = [x for x, u in ((lane.five_reset, lane.five), (lane.week_reset, lane.week)) if x and u is not None and u >= 95]
        lane.out_until = max(resets) if resets else t + 3600


Windows = dict[str, dict[str, Json]]  # {five_hour, weekly, fable}: each {used, resets_at}


def normalize_usage(raw: Json) -> Windows | None:
    """get_usage's result (or its `plan`, or its `windows` list) -> {five_hour, weekly, fable}, each {used, resets_at}; None if no window
    matches."""
    if isinstance(raw, dict) and isinstance(raw.get("plan"), dict):
        raw = raw["plan"]
    if isinstance(raw, dict):
        raw = raw.get("windows")
    out: Windows = {}
    for w in raw if isinstance(raw, list) else []:
        if not isinstance(w, dict) or w.get("percentUsed") is None:
            continue
        label = str(w.get("label", "")).lower()
        key = (
            "fable"
            if "fable" in label
            else "five_hour"
            if "5" in label and "hour" in label
            else "weekly"
            if "week" in label and "all" in label
            else None
        )
        used = w["percentUsed"]
        if key and isinstance(used, str | int | float):
            out[key] = {"used": float(used), "resets_at": to_epoch(w.get("resetsAt"))}
    return out or None


AUTH_TTL = 300  # a login check answers for this long: it spawns a CLI, cheap but not free
AUTH_TIMEOUT = harnesses.AUTH_TIMEOUT
LOGOUT_CHECK_S = 15
AUTH_FILE_TTL = 600  # what a non-cheap status, doctor, a login probe and a successful run left, as read by `next` and `status --cheap`


def auth_cache() -> AuthCache:
    return AuthCache(env.states(), not os.environ.get("DELEGATE_NOCACHE"))


def claude_logged_out() -> bool:
    """True only when `claude auth status` answers loggedIn false; no CLI or an unreadable answer is not a logout (an Agent-tool host may
    have no CLI)."""
    c = auth_cache().fresh("CLAUDE_SUBSCRIPTION", env.now(), AUTH_FILE_TTL)
    if c:
        return c.ok is False
    v = ClaudeHarness().login_probe(LOGOUT_CHECK_S)[0]
    if isinstance(v, bool):
        auth_cache().remember("CLAUDE_SUBSCRIPTION", v, "claude auth status", env.now())
    return v is False


def _windows_of(data: Json) -> Windows | None:
    """The cached usage windows, if what the cache holds is a mapping."""
    return {k: obj(v) for k, v in data.items()} if isinstance(data, dict) else None


def _claude_windows(
    lane: Lane, st: StateDoc, t: float, stale: float, ai_usage: Json
) -> tuple[Windows | None, tuple[str, float | None] | None]:
    """-> (the usage windows, (where the numbers came from, when they were taken)): the caller's get_usage, else the saved one, else the
    status line."""
    usage: Windows | None = None
    src: tuple[str, float | None] | None = None
    if ai_usage:
        usage = normalize_usage(ai_usage)
        if usage:
            env.update_state(remembering("claude_usage", UsageCache(at=t, data=usage)))
            src = ("manual mark (get_usage passed in)", t)
    if usage is None:
        saved = st.claude_usage
        if saved and t - saved.at <= stale:
            usage = _windows_of(saved.data)
            src = ("manual mark (get_usage passed in)", saved.at)
            lane.notes.append(f"usage from {fmt_span(t - saved.at)} ago")
    if usage is None:
        read = statusline.read(t, stale)
        if read:
            usage, updated = read
            lane.notes.append("usage from the status-line file")
            src = ("live read (status line)", updated)
    return usage, src


def _apply_claude_windows(lane: Lane, S: Settings, usage: Windows, src: tuple[str, float | None], t: float) -> None:
    f5, wk = usage.get("five_hour") or {}, usage.get("weekly") or {}
    lane.five_reset, lane.week_reset = as_num(f5.get("resets_at")), as_num(wk.get("resets_at"))
    lane.five, _, _ = window(as_num(f5.get("used")), lane.five_reset, 300, t)
    lane.week, wmins, lane.pace = window(as_num(wk.get("used")), lane.week_reset, WEEK_MIN, t)
    if f5:
        add_window(lane, lane.five, lane.five_reset, 300, src[0], src[1])
    if wk:
        add_window(lane, lane.week, lane.week_reset, WEEK_MIN, src[0], src[1])
    apply_burn(lane, S, wmins)
    if (lane.five or 0) >= 98 or (lane.week or 0) >= 98:
        lane.out, lane.out_reason = True, "limit"
        lane.out_until = (lane.week_reset if (lane.week or 0) >= 98 else lane.five_reset) or t + 3600


def read_claude_subscription(lane: Lane, S: Settings, st: StateDoc, t: float, ai_usage: Json = None) -> None:
    stale = S.usage_stale_minutes * 60
    usage, src = _claude_windows(lane, st, t, stale, ai_usage)
    if claude_logged_out():
        lane.out, lane.out_reason = True, "logged_out"
        lane.notes.append("claude is logged out: run `claude auth login`")
    weekly_spec = S.claude_weekly_reset
    if usage:
        assert src is not None  # every way `usage` got a value set `src`
        _apply_claude_windows(lane, S, usage, src, t)
    elif weekly_spec:
        nxt = next_weekly(weekly_spec, t)
        if nxt:
            lane.week_reset = nxt
            add_window(lane, None, nxt, WEEK_MIN, "manual mark (claude_weekly_reset in config)", None)
            lane.notes.append(f"weekly reset {local(nxt)} (config); use unknown")


def read_none(lane: Lane, S: Settings, st: StateDoc, t: float, ai_usage: Json = None) -> None:
    """No usage reading (Grok): only refusals mark the lane out."""


READERS = {"codex_app_server": read_codex, "claude_subscription": read_claude_subscription, "none": read_none}
