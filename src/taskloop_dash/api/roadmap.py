"""The Roadmap tab: one lane per slot with its bead, stage rail, unlocks and last passes, then the queue in the order the loop takes
it, each with the beads it unblocks as a tree. Read only: the loop's state files are read, a dead loop's is left alone."""

import json
import time
from typing import Any

from taskloop.contracts import log as rec
from taskloop_dash import jsonl
from taskloop_dash.api.asks import Asks
from taskloop_dash.api.graph import Graph
from taskloop_dash.api.looks import Looks
from taskloop_dash.api.tasks import Tasks
from taskloop_dash.env import Env
from taskloop_dash.readers.beads import Beads, basename
from taskloop_dash.readers.loops import STOP_KINDS, loop_key
from taskloop_dash.readers.records import Records
from taskloop_dash.readers.runlogs import RunLogs
from taskloop_dash.views import bead_blocks, roadmap

LOG_TAIL = 400  # pass-log lines read


def lapsed(b: dict[str, Any], now_utc: str) -> bool:
    t = b.get("lease_expires_at") or ""
    return bool(t) and t < now_utc


class RoadmapApi:
    def __init__(self, env: Env, records: Records, beads: Beads, graph: Graph, tasks: Tasks, asks: Asks, looks: Looks, runlogs: RunLogs) -> None:
        self.env, self.records, self.beads, self.graph, self.tasks = env, records, beads, graph, tasks
        self.asks, self.looks, self.runlogs = asks, looks, runlogs

    def engine_version(self, log: str) -> str:
        """The task-loop version the run in engine log `log` runs now: its last reload record (a re-exec writes one)."""
        reloads = [r for r in jsonl.records(log) if isinstance(r, rec.Reload)]
        return reloads[-1].new if reloads else ""

    def running_slots(self, repo: str) -> dict[str, str]:
        """{bead: slot} of the beads a slot bead holds now (held_bead, in progress, lease not lapsed)."""
        out: dict[str, str] = {}
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.env.clock()))
        for b in self.env.ports.slot_beads(repo):
            held = (b.get("metadata") or {}).get("held_bead")
            if held and b.get("status") == "in_progress" and not lapsed(b, stamp):
                out[held] = b["title"].split()[-1]
        return out

    def loop_files(self, repo: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """(lanes, rows, waiting loops): one lane per slot, the repo's pass log rows oldest first."""
        cfg, key = self.env.config, loop_key(repo)
        loops: list[dict[str, Any]] = []
        own_stop: dict[int, str] = {}  # a state file carries its own stop request: {kind: now|after_current}
        for st in self.graph.loops.live(repo):
            kind = (st.get("stop") or {}).get("kind") if isinstance(st.get("stop"), dict) else None
            if kind in STOP_KINDS:
                own_stop[st["pid"]] = STOP_KINDS[kind]
            loops.append({"pid": st["pid"], "slot": st.get("slot") or "", "bead": st.get("bead"), "since": st.get("since"),
                          "started": st.get("started") or 0, "worktree": st.get("worktree") or "", "version": st.get("version") or ""})
        slots: list[str]
        running: dict[str, str]
        try:
            slots = [b["title"].split()[-1] for b in self.env.ports.slot_beads(repo)]
            running = self.running_slots(repo)
        except Exception:
            slots = []
            running = {}
        commanded = self.graph.loops.command_stops(repo)  # LoopCommand: the loops it names, by pid
        stop = {st["pid"]: commanded.get(st["pid"]) or own_stop.get(st["pid"], "") for st in loops}
        lanes, waiting = roadmap.lanes_of(slots, running, loops, stop)
        rows = []
        try:
            for line in cfg.loop_log(key).read_text(encoding="utf-8", errors="replace").splitlines()[-LOG_TAIL:]:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict) and row.get("bead"):
                    rows.append(row)
        except OSError:
            pass
        return lanes, rows, waiting

    def hand_run(self, lanes: list[dict[str, Any]], tasks: dict[str, Any], repo: str) -> None:
        """A bead run by hand (tl run-task) has a slot but no loop: it takes the lane of its slot, or one of its own."""
        held = {ln["bead"] for ln in lanes if ln["bead"]}
        for t in tasks.values():
            if t.get("state") == "running" and t["id"] not in held and t.get("repo") == repo:
                free = next((ln for ln in lanes if ln["slot"] == t.get("slot") and not ln["bead"]), None)
                since = self.env.clock() - (t.get("since") or 0)
                if free:
                    free["bead"], free["since"] = t["id"], since
                else:
                    lanes.append({"slot": t.get("slot") or "-", "bead": t["id"], "since": since})

    def trails(self, lanes: list[dict[str, Any]], tasks: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        logs = self.records.engine_logs(retain=False)
        for ln in lanes:
            b = ln["bead"]
            if not b or b not in logs:
                continue
            try:
                r = self.runlogs.run_timeline(logs[b][-1], alive=True)
            except Exception:
                continue
            ln["since"] = ln["since"] or (tasks.get(b) or {}).get("started")
            ln["engine"] = self.engine_version(logs[b][-1])
            out[b] = {"run": len(logs[b]), "stage": (tasks.get(b) or {}).get("stage") or "", "blocks": bead_blocks.trail(r["blocks"])}
        return out

    def api_roadmap(self, repo: str = "") -> dict[str, Any]:
        self.env.touch()
        g = self.graph.api_graph(repo)
        if g.get("error"):
            return dict(g, lanes=[], queue=[], held=[], done=[], summary={})
        path = self.beads.resolve_repo(g["repo"], "")

        def build() -> dict[str, Any]:
            beads = self.beads.beads_of(path)
            ranked, skipped = self.graph.loop_order(path, beads, self.graph.config_of(path))
            lanes: list[dict[str, Any]]
            rows: list[dict[str, Any]]
            waiting: list[dict[str, Any]]
            try:
                lanes, rows, waiting = self.loop_files(path)
            except Exception:
                lanes = []
                rows = []
                waiting = []
            api = self.tasks.api_tasks()
            tasks = {t["id"]: t for t in api["tasks"]}
            self.hand_run(lanes, tasks, g["repo"])
            trails = self.trails(lanes, tasks)
            mine = [a for a in self.asks.asks()["asks"] if basename(a.get("repo")) == g["repo"]]
            looks = [i for i in self.looks.look_items(path)[1] if i["status"] == "open"]
            return roadmap.build(g, lanes, ranked, skipped, rows, trails, rows=tasks, lane_records=api["lanes"], asks=mine,
                                 waiting=len(waiting), looks=looks, closed=[b for b in beads if b.get("status") == "closed"],
                                 installed=self.env.ports.installed_versions())

        return dict(self.env.ttl.get("roadmap:" + path, 5, build), repos=g["repos"])
