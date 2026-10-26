"""Stable run fingerprints and the lifecycle record contract.

A fingerprint is what the lifecycle report groups failures by: the same cause with different bead ids, session
refs, paths, commit shas, durations or quoted payloads must produce the same string, while two different causes
must not. It is derived from the run's `why` only, never from the run name or the clock, so it can be recomputed
from a trace row years later.

Pure: Python 3.8+, standard library only. engine.py imports this module; it must not import engine.
"""

import hashlib
import re
import statistics
from datetime import datetime, timedelta, timezone

# origin() writes one of these; an older row may have none at all.
STARTED_BECAUSE = ("first", "answer", "resume", "retry", "fresh")

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
URL = re.compile(r"\bhttps?://\S+", re.I)
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
SHA = re.compile(r"\b[0-9a-f]{7,40}\b", re.I)
# A token that may be a bead id: tl-19i, lifesim-d5f.46, tl-fsj, t-1-1. _bead_token decides.
CANDIDATE = re.compile(r"\b[a-z][a-z0-9]*(?:[.-][a-z0-9]+)+\b", re.I)
BEAD_PREFIXES = ("tl", "lifesim", "task", "bead", "fld")
SESSION = re.compile(r"\b(?:ref|ses|session|run|thread)[-_][A-Za-z0-9._-]+\b", re.I)
# Absolute POSIX/Windows paths, and relative paths with a separator and a file extension (Assets/Player.cs,
# Assets\Player.cs). A bare word pair such as and/or is not a path.
PATH = re.compile(r"(?:[A-Za-z]:)?(?:[\\/][\w.@%+~-]+){2,}"
                  r"|(?:[\w.@%+~-]+[\\/])+[\w.@%+~-]*\.[A-Za-z0-9]{1,8}\b")
QUOTED = re.compile(r"`[^`]*`|\"[^\"]*\"|'[^']*'")
BRACES = re.compile(r"\{[^{}]*\}")
NUMBER = re.compile(r"\b\d+(?:\.\d+)?\b")
SPACE = re.compile(r"\s+")
EDGE = " :;,.-|/"


def normalize_started_because(value, prev_run=""):
    """One of STARTED_BECAUSE: an older or damaged value becomes retry (a run came before) or first."""
    v = str(value or "").strip().lower()
    if v in STARTED_BECAUSE:
        return v
    return "retry" if str(prev_run or "").strip() else "first"


def _bead_token(token):
    """True when token is an id, not a descriptive hyphenated word."""
    if any(ch.isdigit() for ch in token):
        return True
    return re.split(r"[.-]", token)[0].lower() in BEAD_PREFIXES


def fingerprint(why):
    """A stable, readable slug for a failure reason ("" when there is no text)."""
    text = str(why or "")
    if not text.strip():
        return ""
    text = ANSI.sub("", text).lower()
    text = URL.sub(" <url> ", text)
    # Whole paths before sessions and before embedded SHAs/UUIDs: Assets/Player2.cs is a path, not a bead, and
    # /repo/thread-1234abc/Player.cs is one path, not a session plus a sha. Paths first also keeps a session-like
    # segment inside a Windows or POSIX path from being split off.
    text = PATH.sub(" <path> ", text)
    text = SESSION.sub(" <session> ", text)
    text = UUID.sub(" <id> ", text)
    text = SHA.sub(" <sha> ", text)
    text = CANDIDATE.sub(lambda m: " <bead> " if _bead_token(m.group(0)) else m.group(0), text)
    text = QUOTED.sub(" <quoted> ", text)
    text = BRACES.sub(" <json> ", text)
    text = NUMBER.sub(" <n> ", text)
    text = SPACE.sub(" ", text).strip(EDGE)
    if not text:
        return ""
    if len(text) > 120:
        text = text[:112].rstrip(EDGE) + "#" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
    return text


def run_fingerprint(outcome, why):
    """A trace row's fingerprint: "" for a landed/done run, else the normalised cause (never empty)."""
    if str(outcome or "") in ("landed", "done"):
        return ""
    return fingerprint(why) or "unknown"


# ---- weekly lifecycle report ------------------------------------------------------------------------------------------

DAY = 86400.0
WEEK = 7 * DAY
LANDED = ("landed",)
# Study 04's audit found every verify/stuck/denied/budget/ticket ask avoidable and about half the decisions avoidable.
# A report cannot reproduce that hand judgement, so only the kind that is genuinely owner-only is excluded. Answer
# authorship is deliberately not part of this rule: a supervisor answering a real decision does not make it avoidable,
# and an owner answering a verify ask does not make it necessary.
UNAVOIDABLE_ASKS = ("decision",)


def utc_week_start(t):
    """The Monday 00:00 UTC at or before t, as epoch seconds."""
    d = datetime.fromtimestamp(float(t), timezone.utc)
    d = d.replace(hour=0, minute=0, second=0, microsecond=0)
    return (d - timedelta(days=d.weekday())).timestamp()


def utc_iso(t):
    return datetime.fromtimestamp(float(t), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def weeks(since, until, whole=False):
    """[start, end) UTC weeks clipped to [since, until); explicit half-open boundaries. whole=True: the window is one
    bucket, so a baseline over a window that is not week-aligned has window totals and window medians."""
    out = []
    start = utc_week_start(since)
    while start < until:
        end = until if whole else start + WEEK
        a, b = max(start, since), min(end, until)
        if b > a:
            out.append({"start": a, "end": b, "week_start": start, "week_end": end,
                        "days": (b - a) / DAY, "start_iso": utc_iso(a), "end_iso": utc_iso(b)})
        start = end
    return out


def span(run):
    """(started, ended) when both endpoints are usable; None for a legacy row missing one."""
    a, b = run.get("started"), run.get("ended")
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return None
    return (a, b) if b >= a else None


def overlap(a, b, since, until):
    return max(0.0, min(float(b), float(until)) - max(float(a), float(since)))


def uncached(tokens):
    """Uncached input tokens: delegate 0.22+ and Codex put cache reads in `in`; older rows had uncached-only `in`."""
    tk = tokens or {}
    try:
        i, c = int(tk.get("in") or 0), int(tk.get("cached") or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, i - c) if i >= c else max(0, i)


def _fingerprint(row):
    return (row.get("fingerprint") or fingerprint(row.get("reason") or row.get("why") or row.get("error") or "")
            or "")


def _is_done(row):
    return str(row.get("status") or row.get("outcome") or "").strip().lower() in (
        "done", "landed", "completed", "success", "ok", "passed")


def _median(xs):
    return round(statistics.median(xs), 1) if xs else None


def _ask_kind(row):
    """An ask row's kind, from the ask file or the trace row's why. Kept here so the report is pure."""
    kind = str(row.get("kind") or "").strip().lower()
    if kind in ("verify", "decision", "ticket", "stuck", "budget", "denied"):
        return kind
    why = str(row.get("why") or "")
    if why.startswith(("paused:", "waiting:", "failed:")):
        return ""
    if why.startswith("owner decision needed"):
        return "decision"
    if why.startswith("over budget"):
        return "budget"
    if why.startswith("needs a human"):
        return "denied"
    if why.startswith("verify:"):
        return "verify"
    if why.startswith("ticket:"):
        return "ticket"
    if why:
        return "stuck"
    return ""


def _ask_time(row):
    for k in ("t", "asked_t", "ts"):
        v = row.get(k)
        try:
            return float(v)
        except (TypeError, ValueError):
            pass
        if isinstance(v, str) and v.strip():
            try:
                return datetime.fromisoformat(v.strip().replace("Z", "+00:00")).timestamp()
            except ValueError:
                pass
    return None


def _records(records_by_run, run):
    if records_by_run is None:
        return None
    return records_by_run.get(run.get("run")) or records_by_run.get(str(run.get("run") or "")) or []


def _node_intervals(records):
    """(step, start, end) for node/end pairs; a lone end uses its `secs`."""
    out, open_nodes = [], {}
    for rec in records or []:
        if not isinstance(rec, dict):
            continue
        if rec.get("kind") == "node" and rec.get("step"):
            open_nodes[rec.get("id")] = rec
        elif rec.get("kind") == "end" and rec.get("step"):
            rid = rec.get("id")
            n = open_nodes.get(rid)
            if n and n.get("t") is not None and rec.get("t") is not None:
                out.append((rec.get("step"), float(n["t"]), float(rec["t"])))
            else:
                try:
                    t, secs = float(rec.get("t")), float(rec.get("secs"))
                except (TypeError, ValueError):
                    continue
                out.append((rec.get("step"), t - secs, t))
    return out


def _verify_intervals(records, sessions):
    """Verify node intervals; older logs without node/end pairs fall back to the verify session rows."""
    out = [x for x in _node_intervals(records) if x[0] == "verify"]
    if out:
        return out
    for s in sessions or []:
        if s.get("node") != "verify":
            continue
        try:
            t, secs = float(s.get("t")), float(s.get("secs"))
        except (TypeError, ValueError):
            continue
        out.append(("verify", t - secs, t))
    return out


def _gate_records(records):
    """(start, seconds) for each real (not cached) release gate."""
    out = []
    for rec in records or []:
        if not isinstance(rec, dict) or rec.get("kind") != "gate" or rec.get("cached"):
            continue
        try:
            t = float(rec.get("t"))
            secs = float(rec.get("secs"))
        except (TypeError, ValueError):
            try:
                t, start = float(rec.get("t")), float(rec.get("started_t"))
            except (TypeError, ValueError):
                continue
            secs = t - start
        if secs < 0:
            continue
        out.append((t - secs, secs))
    return out


def _hung_intervals(records):
    """(start, end) for a kill: first vendor error, else last observed event, to the kill."""
    out = []
    for rec in records or []:
        if not isinstance(rec, dict) or rec.get("kind") != "kill":
            continue
        if str(rec.get("why") or "") != "hung" and not rec.get("hung"):
            continue
        end = rec.get("kill_t", rec.get("observed_t"))
        start = rec.get("first_error_t")
        if start is None:
            start = rec.get("last_event_t")
        try:
            start, end = float(start), float(end)
        except (TypeError, ValueError):
            try:
                end, secs = float(rec.get("observed_t")), float(rec.get("secs"))
                start = end - secs
            except (TypeError, ValueError):
                continue
        if end >= start:
            out.append((start, end))
    return out


def _landings(traces):
    """Every landed trace, earliest per bead first, with its position in the bead's full run history."""
    by_bead = {}
    for r in traces or []:
        if not isinstance(r, dict) or not r.get("bead"):
            continue
        a = r.get("started")
        try:
            a = float(a)
        except (TypeError, ValueError):
            a = 0.0
        by_bead.setdefault(r["bead"], []).append((a, r))
    for rs in by_bead.values():
        rs.sort(key=lambda x: x[0])
    out = []
    for bead, rs in by_bead.items():
        for i, (_, r) in enumerate(rs):
            if str(r.get("outcome") or "") in LANDED:
                out.append({"bead": bead, "run": r, "index": i + 1, "runs": rs[:i + 1]})
    return out


def _dead_times(traces):
    """(started, gap minutes) from a bead's previous run; the caller keeps the ones in its week."""
    by_bead = {}
    for r in traces or []:
        if not r.get("bead"):
            continue
        try:
            a = float(r.get("started"))
        except (TypeError, ValueError):
            continue
        by_bead.setdefault(r["bead"], []).append((a, r))
    out = []
    for rs in by_bead.values():
        rs.sort(key=lambda x: x[0])
        for (a0, r0), (a1, r1) in zip(rs, rs[1:]):
            try:
                gap = (a1 - float(r0.get("ended"))) / 60.0
            except (TypeError, ValueError):
                continue
            if gap < 0:
                gap = 0.0
            because = normalize_started_because(r1.get("started_because"), r1.get("prev_run") or r0.get("run"))
            out.append((a1, because, gap))
    return out


def _streaks(history, since, until):
    """Max consecutive non-done calls with the same fingerprint, per (lane, model), in the window."""
    if history is None:
        return None
    rows = []
    for h in history or []:
        if not isinstance(h, dict):
            continue
        t = _ask_time(h)
        if t is None or not (since <= t < until):
            continue
        lane = str(h.get("lane") or h.get("family") or h.get("role") or "?")
        model = str(h.get("model") or "?")
        if _is_done(h):
            rows.append((t, lane, model, None))
            continue
        # A missing reason is the same "unknown" cause the trace contract records, not a row to skip: skipping it
        # would let a known-cause streak continue across an unrelated failure.
        rows.append((t, lane, model, _fingerprint(h) or "unknown"))
    rows.sort(key=lambda x: x[0])
    current, best = {}, {}
    for _, lane, model, fp in rows:
        key = (lane, model)
        if fp is None:
            current.pop(key, None)
            continue
        cur = current.get(key)
        if cur and cur["fingerprint"] == fp:
            cur["max"] += 1
        else:
            current[key] = {"lane": lane, "model": model, "fingerprint": fp, "max": 1}
        cur = current[key]
        old = best.get(key)
        if old is None or cur["max"] > old["max"]:
            best[key] = dict(cur)
    return sorted(best.values(), key=lambda x: (-x["max"], x["lane"], x["model"]))


def _asks_in_week(asks, since, until):
    rows = []
    for a in asks or []:
        if not isinstance(a, dict):
            continue
        t = _ask_time(a)
        if t is None or not (since <= t < until):
            continue
        rows.append(a)
    return rows


def _quota_per_landed(observations, since, until, landed):
    """Historical quota consumption only from at least two timestamped readings; one snapshot is unavailable."""
    if not observations or not landed:
        return None
    series = {}
    for o in observations:
        try:
            t, pct = float(o.get("t")), float(o.get("used_pct"))
        except (TypeError, ValueError):
            continue
        if not (since <= t < until):
            continue
        key = (str(o.get("lane") or "?"), str(o.get("window") or "?"))
        series.setdefault(key, []).append((t, pct))
    used = 0.0
    seen = False
    for rows in series.values():
        if len({t for t, _ in rows}) < 2:
            continue
        seen = True
        rows.sort()
        used += sum(max(0.0, rows[i][1] - rows[i - 1][1]) for i in range(1, len(rows)))
    return round(used / landed, 2) if seen else None


def lifecycle_report(traces, records_by_run=None, asks=(), history=None, quota=None, since=None, until=None,
                     reverts=None, quota_observations=None, whole=False):
    """The weekly lifecycle report as data. Pure: callers load traces, engine logs, asks, delegate history and git facts.

    `reverts` maps a landing run name (or bead) to {"status": reverted|fixed_forward|clean|censored|unknown}; the caller
    owns the git read and the seven-day follow-up. `history is None` means delegate history was unavailable (not empty).
    """
    traces = [r for r in traces or [] if isinstance(r, dict)]
    since, until = float(since), float(until)
    landings = _landings(traces)
    dead = _dead_times(traces)
    out = []
    for w in weeks(since, until, whole):
        a, b, days = w["start"], w["end"], w["days"]
        total = non = over180 = 0.0
        timed = runs = non_untimed = 0
        tokens = 0
        for r in traces:
            try:
                start = float(r.get("started"))
            except (TypeError, ValueError):
                continue
            if not (a <= start < b):
                continue
            runs += 1
            for sess in r.get("sessions") or []:
                tokens += uncached(sess.get("tokens"))
            if not span(r) and str(r.get("outcome") or "") not in LANDED:
                non_untimed += 1
        # Slot time is clipped to the half-open week: a run crossing midnight Sunday is split between the two weeks,
        # never counted whole on both sides. A run whose start is outside the window still contributes the part that
        # happened inside it, so a report never drops or double counts slot-min at its edges.
        for r in traces:
            sp = span(r)
            if not sp:
                continue
            if a <= sp[0] < b:
                timed += 1
            ov = overlap(sp[0], sp[1], a, b)
            if not ov:
                continue
            total += ov
            if str(r.get("outcome") or "") not in LANDED:
                non += ov
            if sp[1] - sp[0] > 180 * 60:
                over180 += ov
        def when(x):
            try:
                return float(x["run"].get("ended"))
            except (TypeError, ValueError):
                pass
            try:
                return float(x["run"].get("started"))
            except (TypeError, ValueError):
                return None

        week_landings = [x for x in landings if when(x) is not None and a <= when(x) < b]
        nland = len({x["bead"] for x in week_landings})
        touched_beads = set()
        for r in traces:
            try:
                t = float(r.get("started"))
            except (TypeError, ValueError):
                continue
            if r.get("bead") and a <= t < b:
                touched_beads.add(r["bead"])
        touched = len(touched_beads)
        run1 = len({x["bead"] for x in week_landings if x["index"] == 1})
        asks_w = _asks_in_week(asks, a, b)
        avoidable = sum(1 for x in asks_w if _ask_kind(x) not in UNAVOIDABLE_ASKS)
        fp_beads = {}
        for r in traces:
            if str(r.get("outcome") or "") in ("landed", "done"):
                continue
            try:
                t = float(r.get("started"))
            except (TypeError, ValueError):
                continue
            if not (a <= t < b):
                continue
            fp = r.get("fingerprint") or run_fingerprint(r.get("outcome"), r.get("why"))
            if fp and r.get("bead"):
                fp_beads.setdefault(fp, set()).add(r["bead"])
        fingerprints = [{"fingerprint": fp, "beads": len(beads), "count": len(beads),
                         "per_day": round(len(beads) / days, 2),
                         "beads_per_day": round(len(beads) / days, 2)}
                        for fp, beads in fp_beads.items()]
        fingerprints.sort(key=lambda x: (-x["beads"], x["fingerprint"]))
        fingerprints = fingerprints[:5]
        verify = 0.0
        gates = []
        hung = 0.0
        kills = 0
        week_records = False
        for r in traces:
            sp = span(r)
            if sp:
                if not overlap(sp[0], sp[1], a, b):
                    continue
            else:
                try:
                    start = float(r.get("started"))
                except (TypeError, ValueError):
                    continue
                if not (a <= start < b):
                    continue
            recs = _records(records_by_run, r) if isinstance(records_by_run, dict) else None
            if recs is None:
                continue
            if recs:
                week_records = True
            for step, s0, s1 in _verify_intervals(recs, r.get("sessions")):
                verify += overlap(s0, s1, a, b) / 60.0
            for s0, secs in _gate_records(recs):
                # The gate table is a duration per gate, not a rate; count a gate in the week it finished and keep
                # its observed minutes (a gate crossing Sunday midnight is not split).
                if a <= s0 + secs < b:
                    gates.append(secs / 60.0)
            for s0, s1 in _hung_intervals(recs):
                ov = overlap(s0, s1, a, b)
                if not ov:
                    continue
                hung += ov / 60.0
                if a <= s1 < b:
                    kills += 1
        reverts = reverts or {}
        rev = fixed = censored = eligible = 0
        rev_unknown = False
        rev_counted = set()
        for x in week_landings:
            if x["bead"] in rev_counted:
                continue
            rev_counted.add(x["bead"])
            info = reverts.get(x["run"].get("run")) or reverts.get(x["bead"])
            if not info:
                rev_unknown = True
                continue
            status = str(info.get("status") or "") if isinstance(info, dict) else str(info or "")
            if status in ("reverted", "fixed_forward", "clean"):
                eligible += 1
                if status == "reverted":
                    rev += 1
                elif status == "fixed_forward":
                    fixed += 1
            elif status == "censored":
                censored += 1
            else:
                rev_unknown = True
        quota_pct = _quota_per_landed(quota_observations, a, b, nland)
        by_because = {}
        for t, because, gap in dead:
            if a <= t < b:
                by_because.setdefault(because, []).append(gap)
        dead_w = {k: _median(by_because.get(k, [])) for k in STARTED_BECAUSE}
        streaks_w = _streaks(history, a, b)
        unavailable = []
        if runs and timed < runs:
            unavailable.append("slot-min")
        if not total or non_untimed:
            unavailable.append("non-landing-slot-min-share")
        if not nland:
            unavailable += ["slot-min-per-landed", "runs-per-landed", "beads-landed-on-run-1",
                            "uncached-input-per-landed", "reverts-per-100-landings"]
        if not week_records:
            unavailable += ["verify-stage-slot-min", "hung-step-slot-min"]
        if not gates:
            unavailable.append("median-release-gate-minutes")
        if history is None:
            unavailable.append("max-consecutive-same-fingerprint")
        if rev_unknown:
            unavailable.append("reverts-per-100-landings")
        if quota_pct is None:
            unavailable.append("quota-percent-per-landed")
        per_day = round(nland / days, 2)
        slot_per = round(total / 60.0 / nland, 1) if nland else None
        non_share = round(non / total, 4) if total and not non_untimed else None
        run1_share = round(run1 / nland, 4) if nland else None
        over = round(over180 / 60.0, 1)
        verify_min = round(verify, 1) if week_records else None
        hung_min = round(hung, 1) if week_records else None
        gate_median = _median(gates)
        uncached_per = round(tokens / nland, 1) if nland else None
        revert_rate = round((rev + fixed) / eligible * 100, 2) if eligible else None
        row = {
            **w,
            "landed": nland,
            "landed_beads": nland,
            "landed_beads_per_day": per_day,
            "landed_per_day": per_day,
            "slot_min": round(total / 60.0, 1),
            "slot_min_per_landed": slot_per,
            "slot_min_per_landed_bead": slot_per,
            "non_landing_slot_min": round(non / 60.0, 1),
            "non_landing_share": non_share,
            "non_landing_slot_min_share": non_share,
            "asks": len(asks_w),
            "asks_total": len(asks_w),
            "avoidable_asks": avoidable,
            "avoidable_asks_per_week": avoidable,
            "landed_run1": run1,
            "run1": run1,
            "beads_landed_on_run_1": run1,
            "landed_run1_share": run1_share,
            "landed_run1_share_of_landed": run1_share,
            "landed_run1_share_touched": round(run1 / touched, 4) if touched else None,
            "touched": touched,
            "beads_touched": touched,
            "runs": runs,
            "runs_per_landed": round(runs / nland, 2) if nland else None,
            "runs_per_landed_bead": round(runs / nland, 2) if nland else None,
            "dead_time_min": dead_w,
            "median_dead_time_min": dead_w,
            "median_dead_time_per_started_because": dead_w,
            "fingerprints": fingerprints,
            "fingerprint_top5": fingerprints,
            "fingerprint_streaks": streaks_w,
            "max_consecutive_same_fingerprint": streaks_w,
            "max_consecutive_same_fingerprint_non_done_runs": streaks_w,
            "slot_min_over_180": over,
            "slot_min_runs_over_180": over,
            "slot_min_in_runs_over_180_min": over,
            "verify_slot_min": verify_min,
            "verify_stage_slot_min": verify_min,
            "hung_slot_min": hung_min,
            "hung_step_slot_min": hung_min,
            "hung_kills": kills,
            "release_gate_median_min": gate_median,
            "median_release_gate_min": gate_median,
            "median_release_gate_minutes": gate_median,
            "release_gates": len(gates),
            "uncached_input": tokens,
            "uncached_input_per_landed": uncached_per,
            "uncached_input_tokens_per_landed_bead": uncached_per,
            "reverts": rev,
            "reverted": rev,
            "fixed_forward": fixed,
            "revert_censored": censored,
            "revert_eligible": eligible,
            "reverts_per_100": revert_rate,
            "reverts_per_100_landings": revert_rate,
            "quota_pct_per_landed": quota_pct,
            "quota_percent_per_landed_bead": quota_pct,
            "unavailable": sorted(set(unavailable)),
        }
        out.append(row)
    return {"v": 1, "since": since, "until": until, "since_iso": utc_iso(since), "until_iso": utc_iso(until),
            "window": {"since": since, "until": until, "since_iso": utc_iso(since), "until_iso": utc_iso(until)},
            "weeks": out, "quota": quota, "quota_snapshot": quota, "history_available": history is not None}


# ---- tl-7y6.1.2: the KPI registry (what an experiment sidecar may measure) ---------------------------------------------
# Every KPI is a key the week row above already carries: the registry only names the measures the lifecycle report
# computes (tl-7y6.1.1); it never calculates anything itself. `unavailable` is the token the report lists in
# week["unavailable"] when a measure cannot be computed; a None value says the same. `tl report lifecycle` prints each
# id in brackets at the end of its line, so a sidecar's `metric` is always an id the report has printed.

KPIS = (
    {"id": "landed_beads_per_day", "key": "landed_beads_per_day", "label": "landed beads/day"},
    {"id": "slot_min_per_landed", "key": "slot_min_per_landed", "label": "slot-min per landed bead",
     "unavailable": "slot-min-per-landed"},
    {"id": "non_landing_slot_min_share", "key": "non_landing_slot_min_share", "label": "non-landing slot-min share",
     "unavailable": "non-landing-slot-min-share"},
    {"id": "avoidable_asks_per_week", "key": "avoidable_asks_per_week", "label": "avoidable asks/week"},
    {"id": "landed_run1_share", "key": "landed_run1_share", "label": "beads landed on run 1",
     "unavailable": "beads-landed-on-run-1"},
    {"id": "runs_per_landed", "key": "runs_per_landed", "label": "runs per landed bead",
     "unavailable": "runs-per-landed"},
    {"id": "slot_min_over_180", "key": "slot_min_over_180", "label": "slot-min in runs >180 min"},
    {"id": "verify_stage_slot_min", "key": "verify_stage_slot_min", "label": "verify-stage slot-min",
     "unavailable": "verify-stage-slot-min"},
    {"id": "hung_step_slot_min", "key": "hung_step_slot_min", "label": "hung-step slot-min",
     "unavailable": "hung-step-slot-min"},
    {"id": "median_release_gate_minutes", "key": "median_release_gate_minutes", "label": "median release-gate minutes",
     "unavailable": "median-release-gate-minutes"},
    {"id": "uncached_input_tokens_per_landed_bead", "key": "uncached_input_tokens_per_landed_bead",
     "label": "uncached input tokens per landed bead", "unavailable": "uncached-input-per-landed"},
    {"id": "reverts_per_100_landings", "key": "reverts_per_100_landings", "label": "reverts per 100 landings",
     "unavailable": "reverts-per-100-landings"},
    {"id": "quota_percent_per_landed_bead", "key": "quota_percent_per_landed_bead",
     "label": "quota % consumed per landed bead", "unavailable": "quota-percent-per-landed"},
)

KPI_BY_ID = {k["id"]: k for k in KPIS}


def kpi_value(week, kpi_id):
    """A week row's value for a KPI id, or None when the report marked it unavailable (never 0 for a missing measure)."""
    k = KPI_BY_ID.get(kpi_id)
    if k is None or not isinstance(week, dict):
        return None
    if k.get("unavailable") and k["unavailable"] in (week.get("unavailable") or []):
        return None
    v = week.get(k["key"])
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None
