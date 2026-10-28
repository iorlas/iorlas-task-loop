"""/api/live/overview (87 §6): one line per bead that is running, queued or paused, each the state line of its run (the same `state`
object the bead page shows) plus the slot line and the lanes strip. Sources are handed in: engine logs through LiveRun, tickets and
the cheap lane snapshot from the caller, so one call spawns nothing."""

from typing import Final

from taskloop_dash.api.live import LiveRun
from taskloop_dash.views import live_state
from taskloop_dash.views.arrows import words

ORDER: Final = {"running": 0, "queued": 1, "paused": 2}


def paused_until(why: str, lanes: list[dict]) -> tuple[str, float | None]:
    """(lane id, when it is back) for the lane a pause text names, from the snapshot."""
    named = set(words(why))
    for ln in lanes:
        if ln.get("name") in named:
            return ln["name"], ln.get("out_until")
    return "", None


def bead_row(entry: dict, lanes: list[dict], now: float) -> dict | None:
    """The line of one run: its state, or paused when it ended asking for a lane; None for a run that ended any other way."""
    run: LiveRun = entry["run"]
    events = run.events()
    st = live_state.state_of(events, now, entry["alive"])
    worker, steps = live_state.worker_of(events), [e for e in events if e["k"] == "step_start"]
    started = next((e["t"] for e in events if e["k"] == "run_start"), None)
    row = {
        "bead": entry["bead"],
        "repo": entry.get("repo", ""),
        "run": entry["name"],
        "title": entry.get("title", ""),
        "state": st["what"],
        "since": st["since"],
        "label": st["label"],
        "detail": st["detail"],
        "lane": worker["lane"],
        "model": worker["model"],
        "step": steps[-1]["step"] if steps else "",
        "elapsed": (now - started) if started else None,
        "until": None,
    }
    if st["what"] == "ended":
        close = next((e for e in reversed(events) if e["k"] == "close"), {})
        why = str(close.get("why") or "")
        if not why.startswith("paused:"):
            return None
        lane, until = paused_until(why, lanes)
        row.update(group="paused", state="paused", label=why.split("\n", maxsplit=1)[0], lane=lane or row["lane"], until=until)
    else:
        row["group"] = "running"
    return row


def lane_chip(ln: dict) -> dict:
    """One lane of the strip: out or ok, when it is back, the highest usage window."""
    used = [u["used_pct"] for u in ln.get("usage", []) if u.get("used_pct") is not None]
    return {
        "id": ln.get("name"),
        "state": "out" if ln.get("out") else "ok",
        "out_until": ln.get("out_until"),
        "used_pct": max(used, default=None),
    }


def overview(entries: list[dict], queue: list[dict], lanes: list[dict], now: float) -> dict:
    """entries: {bead, repo, title, name, run, alive}; queue: {repo, bead, prio, since, ahead}; lanes: the lane snapshot."""
    rows = [r for r in (bead_row(e, lanes, now) for e in entries) if r]
    for q in queue:
        rows.append(
            {
                "bead": q["bead"],
                "repo": q.get("repo", ""),
                "run": "",
                "title": q.get("title", ""),
                "state": "queued",
                "group": "queued",
                "since": q.get("since"),
                "label": f"no free slot · {q.get('ahead', 0)} ahead in line",
                "detail": "",
                "lane": None,
                "model": None,
                "step": "",
                "elapsed": None,
                "until": None,
                "ahead": q.get("ahead", 0),
            }
        )
    rows.sort(key=lambda r: (ORDER[r["group"]], r.get("since") or 0))
    return {"now": now, "beads": rows, "queue": queue, "lanes": [lane_chip(ln) for ln in lanes]}
