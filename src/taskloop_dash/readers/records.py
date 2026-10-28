"""The task-loop records the dash reads and never writes: the event index, registered repos, traces, engine logs, and the spans a
bead's claims make. Each is one file or folder under the config dir (taskloop.contracts.paths names them)."""

import glob
import json
import os
from typing import Any

from taskloop.contracts.paths import RepoDirs
from taskloop_dash.env import RETAIN, STALE_RUN, Env
from taskloop_dash.tails import read_dict
from taskloop_dash.views import names

Span = dict[str, Any]


def pid_alive(pid: object) -> bool:
    try:
        os.kill(int(str(pid)), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


class Records:
    def __init__(self, env: Env) -> None:
        self.env = env

    def events(self) -> list[dict[str, Any]]:
        """events.jsonl rows of the last week, re-read when the file changes."""
        cut = self.env.clock() - RETAIN

        def load(path: str) -> list[dict[str, Any]]:
            out: list[dict[str, Any]] = []
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    for ln in fh:
                        try:
                            e = json.loads(ln)
                        except ValueError:
                            continue
                        if isinstance(e, dict) and e.get("t", 0) >= cut:
                            out.append(e)
            except OSError:
                pass
            return out
        return self.env.files.get(str(self.env.config.events()), load, [])

    def repos(self) -> list[str]:
        known = read_dict(self.env.config.repos())
        return [p for p in known if os.path.isdir(p)]

    def traces(self) -> dict[str, dict[str, Any]]:
        """run -> its traces.jsonl line, re-read when the file changes."""
        def load(path: str) -> dict[str, dict[str, Any]]:
            out: dict[str, dict[str, Any]] = {}
            for ln in self.env.tails.tail_lines(path, 20_000_000):
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if isinstance(r, dict) and r.get("run"):
                    out[r["run"]] = r
            return out
        return self.env.files.get(str(self.env.config.traces()), load, {})

    def engine_logs(self, retain: bool = True) -> dict[str, list[str]]:
        """bead -> its engine logs, oldest first."""
        cut = self.env.clock() - RETAIN if retain else 0
        out: dict[str, list[str]] = {}
        for p in glob.glob(str(self.env.config.engine_log("*"))):
            bead = names.bead_of(names.run_name(p))
            if not bead:
                continue
            try:
                if os.path.getmtime(p) < cut:
                    continue
            except OSError:
                continue
            out.setdefault(bead, []).append(p)
        for v in out.values():
            v.sort()
        return out

    def run_path(self, run: object) -> str | None:
        if not names.is_run_name(run):
            return None
        p = self.env.config.engine_log(str(run))
        return str(p) if p.exists() else None

    def run_alive(self, path: str, run: dict[str, Any] | None, span: Span | None) -> bool:
        """A run with no close: running while the engine lock in its worktree names a live process for its bead; without a lock to
        read, while its log moved lately."""
        bead = names.bead_of(names.run_name(path))
        wt = (run or {}).get("worktree") or (span or {}).get("worktree") or ""
        if wt:
            lock = read_dict(RepoDirs(wt).engine_lock())
            if lock:
                return lock.get("bead") == bead and bool(lock.get("pid")) and pid_alive(lock.get("pid"))
            if run:
                return False
        stderr = path[:-6] + ".stderr"
        try:
            m = max(os.path.getmtime(path), os.path.getmtime(stderr) if os.path.exists(stderr) else 0)
        except OSError:
            return False
        return self.env.clock() - m < STALE_RUN

    def task_spans(self) -> dict[str, list[Span]]:
        """For each bead: the spans (session, worktree, from, to) between a claim and that session's next record."""
        evs = sorted(self.events(), key=lambda e: e.get("t", 0))
        spans: dict[str, list[Span]] = {}
        for e in evs:
            k, b = e.get("kind"), e.get("bead")
            if k == "claim" and b:
                for prev in spans.get(b, []):  # the bead moved to another session (reclaim): the old span ended
                    if prev["to"] is None:
                        prev["to"], prev["end"] = e["t"], "reclaimed"
                spans.setdefault(b, []).append({
                    "bead": b, "session": e.get("session"), "actor": e.get("actor"), "worktree": e.get("worktree"),
                    "repo": e.get("repo"), "slot": e.get("slot"), "from": e["t"], "to": None, "stage": None,
                    "title": e.get("title"), "end": None, "workers": []})
            elif b and b in spans:
                span = spans[b][-1]
                if k == "stage":
                    span["stage"] = e.get("text")
                    span["stage_t"] = e["t"]
                elif k == "worker":
                    span["workers"].append(e)
                elif k in ("close", "block") and span["to"] is None:
                    span["to"], span["end"] = e["t"], k
                elif k == "land":
                    span["sha"] = e.get("sha")
        return spans
