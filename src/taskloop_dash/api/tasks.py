"""The home page: one row per bead the engine ran in the last week, newest state first; and one bead's runs with their blocks."""

import socket
from typing import Any, Final

from taskloop.contracts import log as rec
from taskloop_dash.api.asks import Asks
from taskloop_dash.api.lanes import Lanes
from taskloop_dash.env import Env
from taskloop_dash.readers.beads import Beads, basename
from taskloop_dash.readers.records import Records, Span
from taskloop_dash.readers.runlogs import RunLogs
from taskloop_dash.views import names
from taskloop_dash.views import timeline as tlv

Row = dict[str, Any]
TASK_STATES: Final = {
    "running": 0,
    "asks": 1,
    "paused": 2,
    "queued": 2,
    "blocked_by": 2,
    "waiting": 3,
    "stopped": 4,
    "failed": 4,
    "blocked": 4,
    "landed": 5,
    "done": 5,
}


def slot_of(run: Row | None, span: Span | None, trace: Row | None) -> str:
    for wt in ((run or {}).get("slot"), (span or {}).get("slot")):
        if wt:
            return str(wt)
    wt = (run or {}).get("worktree") or (trace or {}).get("worktree") or (span or {}).get("worktree") or ""
    return basename(wt)


def repo_name(span: Span | None, trace: Row | None, ask: Row | None) -> str:
    r = (span or {}).get("repo") or (ask or {}).get("repo") or (trace or {}).get("repo_url") or ""
    return basename(r).removesuffix(".git")


def wait_label(recs: list[Any], now: float) -> str:
    """"waiting for Codex until 09:02" while the engine sleeps in its slot for a lane, else "". The engine logs the wait's start
    (the lane, until) before it sleeps; its end, or the next step, ends the wait."""
    last = next((r for r in reversed(recs) if isinstance(r, (rec.WaitStart, rec.WaitEnd, rec.StepStart))), None)
    if not isinstance(last, rec.WaitStart) or str(last.what) != "lane" or float(last.until or 0) <= now:
        return ""
    who = names.lane_name(last.holder or "", "")
    return (f"waiting for {who} until {names.when(last.until)}") if who else ""


class Tasks:
    def __init__(self, env: Env, records: Records, runlogs: RunLogs, asks: Asks, beads: Beads, lanes: Lanes) -> None:
        self.env, self.records, self.runlogs, self.asks, self.beads, self.lanes = env, records, runlogs, asks, beads, lanes

    def state_of(
        self, bead: str, newest: str, recs: list[Any], run: Row, alive: bool, span: Span | None, trace: Row | None
    ) -> tuple[Row | None, Row | None, str, str]:
        """(the open ask, the blocker, state, label): running; an open ask; an open `blocks` dependency; the last run's close reason."""
        ask = self.asks.open_ask(bead)
        end = run["end"]
        state, label = end["outcome"], end["text"]
        blocked = None if alive or ask else self.beads.blocker_of(
            bead, (span or {}).get("repo") or self.asks.ask_file(bead).get("repo") or (trace or {}).get("repo_url") or "")
        if alive:
            state, label = "running", wait_label(recs, self.env.clock()) or tlv.live_label(self.runlogs.last_node(newest))
        elif ask:
            state, label = "asks", "waiting for your answer"
        elif blocked:
            state, label = (
                "blocked_by",
                "blocked by {}{}".format(blocked["id"], (" ({})".format(blocked["title"])) if blocked["title"] else ""),
            )
        elif state in ("asks", "waiting"):  # no ask is open: never say it waits for one
            if self.asks.ask_file(bead).get("status") == "answered":
                state, label = "queued", "answered: waits for the next run"
            else:
                why = (end.get("why") or "").split("\n")[0].strip()
                state, label = "stopped", "ask closed" + (": " + why[:120] if why else "")
        elif state == "paused":
            label = "paused: {}{}".format(end.get("reason") or "no lane", (" until " + end["until"]) if end.get("until") else "")
        elif state == "stopped":
            label = "stopped"
        return ask, blocked, state, label

    def totals(self, paths: list[str], newest: str, run: Row) -> Row:
        total, spent, nblocks, reds, longest, replans, checks_secs = 0, {"in": 0, "cached": 0, "out": 0}, 0, 0, 0, 0, 0
        writes, sendbacks, big_turn = 0, 0, 0
        for p in paths:
            r = run if p == newest else self.runlogs.run_timeline(p)
            total += r["secs"] or 0
            for k in spent:
                spent[k] += (r["tokens"] or {}).get(k) or 0
            nblocks += len(r["blocks"])
            for b in r["blocks"]:
                if b["kind"] == "checks":
                    reds += (b.get("result") or {}).get("status") == "fail"
                    longest = max(longest, b.get("secs") or 0)
                    checks_secs += b.get("secs") or 0
                replans += b["kind"] == "replan"
                if b["kind"] == "write":
                    writes += 1
                    big_turn = max(big_turn, ((b.get("tokens") or {}).get("in") or 0) + ((b.get("tokens") or {}).get("out") or 0))
                sendbacks += (b.get("arrow") or {}).get("cause") == "review_sendback"
        return {"secs": total, "tokens_all": spent, "blocks": nblocks, "red_checks": reds, "longest_check": longest, "replans": replans,
                "checks_secs": checks_secs, "writes": writes, "sendbacks": sendbacks, "big_turn": big_turn}

    def task_row(self, bead: str, paths: list[str], spans: dict[str, list[Span]], tr: dict[str, Row]) -> Row:
        newest = paths[-1]
        name = names.run_name(newest)
        span = (spans.get(bead) or [None])[-1]
        recs = self.runlogs.read(newest)
        run_rec, closed = self.runlogs.run_facts(recs)
        alive = not closed and self.records.run_alive(newest, run_rec, span)
        run = self.runlogs.run_timeline(newest, alive=alive)
        trace = tr.get(name)
        ask, blocked, state, label = self.state_of(bead, newest, recs, run, alive, span, trace)
        started = run["started"] or 0
        last_t = (recs[-1].t if recs else None) or started
        return {"id": bead, "title": (span or {}).get("title") or (ask or {}).get("title") or "", "state": state,
                "label": label, "slot": slot_of(run_rec, span, trace), "repo": repo_name(span, trace, ask),
                "runs": len(paths), "run": name, "started": started, "updated": last_t,
                "since": round(self.env.clock() - started) if alive and started else None,
                "run_secs": run["secs"], "ask": ask, "blocked_by": blocked, "end": run["end"], "tokens": run["tokens"],
                "stage": tlv.live_label(self.runlogs.last_node(newest)) if alive else "", **self.totals(paths, newest, run)}

    def api_tasks(self) -> Row:
        """The home page: one row per bead the engine ran in the last week, newest state first."""
        self.env.touch()
        spans, tr = self.records.task_spans(), self.records.traces()
        rows = []
        for bead, paths in self.records.engine_logs().items():
            try:
                rows.append(self.task_row(bead, paths, spans, tr))
            except Exception as e:  # one broken log must not hide the others
                rows.append({"id": bead, "title": "", "state": "failed", "label": f"unreadable log: {e}", "runs": len(paths),
                             "updated": 0, "slot": "", "repo": "", "ask": None})
        rows.sort(key=lambda r: (TASK_STATES.get(r["state"], 4), -(r.get("updated") or 0)))
        return {"version": self.env.version, "now": self.env.clock(), "host": socket.gethostname(), "tasks": rows,
                "lanes": self.lanes.contract_lanes()}

    def api_task_timeline(self, repo: str, bead: str) -> Row:
        """Every run of the bead, oldest first, each with its blocks and arrows."""
        paths = self.records.engine_logs(retain=False).get(bead, [])
        spans, tr = self.records.task_spans(), self.records.traces()
        runs: list[Row] = []
        for p in paths:
            alive = False
            if p == paths[-1]:
                rr, closed = self.runlogs.run_facts(self.runlogs.read(p))
                alive = not closed and self.records.run_alive(p, rr, (spans.get(bead) or [None])[-1])
            r = self.runlogs.run_timeline(p, alive=alive)
            r["because"] = tlv.because_text(r, runs[-1] if runs else None)
            runs.append(r)
        row = self.task_row(bead, paths, spans, tr) if paths else {"id": bead, "title": "", "state": "", "label": "no runs",
                                                                  "ask": self.asks.open_ask(bead)}
        return {"task": row, "runs": runs}
