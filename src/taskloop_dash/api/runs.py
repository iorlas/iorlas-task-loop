"""One run's detail: a block (its transcript, checks and logs), the events of a transcript, and the few files of a run the page may read."""

import glob
import os
from pathlib import Path
from typing import Any

from taskloop_dash.env import Env
from taskloop_dash.readers.events import Event, Events
from taskloop_dash.readers.opencode import PREFIX, OpenCode, session_id
from taskloop_dash.readers.records import Records
from taskloop_dash.readers.runlogs import RunLogs
from taskloop_dash.views import names

FILE_BYTES = 4_000_000  # the most of a check log served
PLAN_STEM = "plan"


def split_window(rest: str) -> tuple[str, float | None, float | None]:
    """`path@t0@t1` (either time may be empty) -> (path, t0, t1); a plain path has no window."""
    parts = rest.rsplit("@", 2)
    if len(parts) == 3:
        try:
            return parts[0], float(parts[1]) if parts[1] else None, float(parts[2]) if parts[2] else None
        except ValueError:
            pass
    return rest, None, None


def servable(rel: object) -> bool:
    """A check log or the plan, never anything else: brief and evidence stay off an unauthenticated page."""
    if not isinstance(rel, str):
        return False
    parts = rel.replace("\\", "/").split("/")
    if ".." in parts:
        return False
    return (len(parts) == 1 and Path(rel).stem == PLAN_STEM and Path(rel).suffix == ".json") or (
        len(parts) >= 2 and parts[0] == "checks" and all(parts)
    )


class RunsApi:
    def __init__(self, env: Env, records: Records, runlogs: RunLogs, events: Events, opencode: OpenCode) -> None:
        self.env, self.records, self.runlogs, self.events, self.opencode = env, records, runlogs, events, opencode
        self.adapters = {"engine": events.engine, "claude": events.claude, "subagent": events.claude, "claude-p": events.claude,
                         "codex": events.codex_log, "codex-exec": events.rollout, "opencode": events.opencode_events}

    def run_events(self, run_id: str, limit: int = 800) -> list[Event]:
        kind, _, rest = run_id.partition(":")
        path, t0, t1 = split_window(rest)
        fn = self.adapters.get(kind)
        if not fn or (kind != "opencode" and not os.path.exists(path)):  # an OpenCode run is a session id, not a file
            return []
        return fn(path, t0, t1)[-limit:]

    def find_transcript(self, family: str, ref: object) -> str:
        if not ref:
            return ""
        if family == "openai":
            hits = glob.glob(str(self.env.codex_sessions / "*" / "*" / "*" / (f"rollout-*{ref}.jsonl")))
        else:
            hits = glob.glob(str(self.env.projects / "*" / (f"{ref}.jsonl")))
        return max(hits, key=os.path.getmtime) if hits else ""

    def transcript_for(self, s: dict[str, Any], fam: str) -> tuple[str, str, str]:
        """(transcript, adapter, its id) of a block's session: OpenCode is a session id into its DB, never a file."""
        if fam == "xai" or session_id(s.get("transcript")):
            tr = self.opencode.reference(s.get("transcript") or s.get("ref"))
            if not tr and session_id(s.get("ref")):
                tr = PREFIX + session_id(s["ref"])
            return tr, "opencode", tr[len(PREFIX):]
        tr = s.get("transcript") if s.get("transcript") and os.path.exists(s["transcript"]) else self.find_transcript(fam, s.get("ref"))
        return tr, ("codex-exec" if fam == "openai" else "claude-p"), tr

    def api_block(self, run: str, node: str, k: str | int = 0) -> dict[str, Any]:
        """One block: the transcript to show (an /api/events id, cut to the block's time), its round's checks with their logs, the
        engine lines of its step."""
        path = self.records.run_path(run)
        if not path:
            return {"error": "no such run"}
        d = self.runlogs.block_detail(path, node, int(k))
        if d.get("error"):
            return d
        s, b = d.get("session") or {}, d["block"]
        tr, adapter, tr_id = self.transcript_for(s, s.get("family") or b["who"]["family"])
        d["events_id"] = "{}:{}@{}@{}".format(adapter, tr_id, (b["t0"] or 0) - 30, (b["t1"] or 0) + 30) if tr else ""
        d["transcript"] = tr
        rdir = self.env.config.run_dir(run)
        for c in d["checks"]:
            rel = c.get("log") or ""
            c["log_url"] = (f"/api/file?run={run}&path={rel}") if rel and (rdir / rel).is_file() else ""
        return d

    def run_file(self, run: object, rel: object) -> bytes | None:
        """A check log or the plan of a run, never anything else (a symlink out of the folder included)."""
        if not names.is_run_name(run) or not servable(rel):
            return None
        base = self.env.config.run_dir(str(run)).resolve()
        try:
            p = (base / str(rel)).resolve()
        except (OSError, ValueError):
            return None
        if base not in p.parents or not p.is_file():
            return None
        with open(str(p), "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - FILE_BYTES))
            return f.read()
