"""A delegate call: its Result, the write-idle watcher, call_delegate (moved unchanged from engine.py, E2)."""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import tl
from core import procs


class Result:
    def __init__(self, data=None, text="", ref="", cost=0.0, secs=0.0, error="", backend="", alive=None, stop="",
                 started_t=None, ended_t=None, first_error_t=None, last_event_t=None, kill_t=None):
        self.data, self.text, self.ref, self.cost, self.secs, self.error, self.backend = (
            data, text, ref, cost, secs, error, backend)
        self.alive = alive or []  # pids of a stopped call's worker that outlived every signal
        self.stop = stop          # why the engine stopped the call ("" = it was not stopped)
        # Process observations, not completion summaries: None means the boundary was not observed.
        self.started_t, self.ended_t = started_t, ended_t
        self.first_error_t, self.last_event_t, self.kill_t = first_error_t, last_event_t, kill_t


POLL = 5  # seconds between the engine's looks at a running delegate call


def agent_run_session(run_id):
    """The worker's session file, from delegate's agent-runs v1 record of the run (docs/contracts/agent-runs-v1.md):
    its transcript, else its Claude session or Codex thread. "" while the record or the file is not there."""
    try:
        rec = json.loads((tl.config_dir().parent / "agent-runs" / "runs" / (run_id + ".json")).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(rec, dict):
        return ""
    if rec.get("transcript") and os.path.exists(rec["transcript"]):
        return rec["transcript"]
    for ref in (rec.get("transcript"), rec.get("session"), rec.get("thread")):  # OpenCode (xai): a session id into its DB
        if tl.opencode_id(ref):
            return tl.transcript_of("xai", ref)
    if rec.get("session"):
        return tl.transcript_of("claude", str(rec["session"]))
    return tl.transcript_of("openai", str(rec["thread"])) if rec.get("thread") else ""


_OC_SEEN = {}  # OpenCode session id -> last update time read


def file_mtime(path):
    sid = tl.opencode_id(path)
    if sid:  # an OpenCode session: its newest message or part; a DB that cannot be read now keeps the last time seen
        t = tl.opencode_updated(sid)
        if t is None:
            return _OC_SEEN.get(sid)
        _OC_SEEN[sid] = t
        return t
    try:
        return os.stat(path).st_mtime
    except OSError:
        return None


class Idle:
    """The write timeout, following the worker (tl-bxk.10.20): fld.27.10, ae6v and fld.6 lost 47 min of live work to a
    wall-clock cap while the worker waited on 5 min Unity runs. Activity is the worker's session file moving or any
    output of the call. warn / stop: seconds without it; cap: seconds in all, active or not. A call whose session file
    cannot be found keeps the wall-clock limit it had."""

    def __init__(self, warn, stop, cap, on_warn=None, clock=time.time, mtime=file_mtime, session=agent_run_session):
        self.warn, self.stop, self.cap, self.on_warn = warn, stop, cap, on_warn
        self.clock, self.mtime, self.session = clock, mtime, session
        self.t0 = self.out = 0.0
        self.warned, self.path = None, ""

    def begin(self):
        self.t0 = self.out = self.clock()
        self.warned, self.path, self.active = None, "", None

    def touch(self):  # the call printed something
        self.out = self.clock()

    def check(self, worker, wall):
        """"" while the call may go on, else why it is stopped. worker: what route.py named (run_id once it has)."""
        now = self.clock()
        rid = worker.get("run_id")
        if rid and not self.path:
            self.path = self.session(rid)
        seen = self.mtime(self.path) if self.path else None
        if seen is None:  # never seen, or lost: the wall limit from the start, and no sooner than `stop` after the last sign
            end = self.t0 + wall if self.active is None else max(self.t0 + wall, self.active + self.stop)
            return "timeout %d min" % (wall // 60) if now >= end else ""
        if now - self.t0 >= self.cap:
            return "hard cap %d min" % (self.cap // 60)
        last = self.active = max(self.t0, self.out, seen)
        quiet = now - last
        if quiet >= self.stop:
            return "no worker output for %d min" % (quiet // 60)
        if quiet >= self.warn and self.warned != last:
            self.warned = last
            if self.on_warn:
                self.on_warn("write: no worker output for %d min" % (quiet // 60))
        return ""

    def wait(self, p, worker, wall):
        """Wait for the call to end: "" when it did, else why the engine must stop it."""
        while True:
            try:
                p.wait(timeout=POLL)
                return ""
            except subprocess.TimeoutExpired:
                why = self.check(worker, wall)
                if why:
                    return why


def live_file(log_path, n, step):
    """Where delegate appends the worker's live events for call n of a run: <engine log without .jsonl>.live/<NN>-<step>.jsonl."""
    log_path = str(log_path)
    base = log_path[:-len(".jsonl")] if log_path.endswith(".jsonl") else log_path
    return "%s.live/%02d-%s.jsonl" % (base, n, re.sub(r"[^A-Za-z0-9_-]+", "-", step or "call").strip("-") or "call")


def call_delegate(route, role, prompt, schema, cwd, resume, timeout, log_path, writer=None, parent="", task="",
                  title="", access="", idle=None, live=""):
    """One AI step through `route.py run` (worker-run v2). Returns (Result, the answer object or None)."""
    with tempfile.TemporaryDirectory() as d:
        bf, sf = os.path.join(d, "brief.md"), os.path.join(d, "schema.json")
        Path(bf).write_text(prompt, encoding="utf-8")
        Path(sf).write_text(json.dumps(schema))
        cmd = [sys.executable, route, "run", role, "--brief", bf, "--cwd", cwd, "--schema", sf,
               "--unattended", "--parent", parent, "--task", task, "--title", title[:120]]
        if resume:
            cmd += ["--resume", resume]
        if writer:
            cmd += ["--authored-by", writer]
        if access:
            cmd.append(access)
        # unpinned: a worker's git may run on other repos; engine.assert_tree catches a redirect after the node
        stop, obs = {}, {}
        try:
            res, secs = procs.run_proc(cmd, cwd, timeout + 120, log_path, idle=idle, stop=stop, obs=obs,
                                       env={"DELEGATE_LIVE_FILE": live} if live else None)
        except BaseException as e:  # the stop ran inside run_proc: keep its observations for the engine's kill record
            try:
                e.engine_stop = dict(stop)
                e.engine_obs = dict(obs)
            except Exception:
                pass
            raise
    timing = dict(started_t=obs.get("started_t"), ended_t=obs.get("ended_t"),
                  first_error_t=obs.get("first_error_t"), last_event_t=obs.get("last_event_t"),
                  kill_t=obs.get("kill_t"))
    if res is None:
        why = stop.get("why") or "timeout"
        return Result(secs=secs, error="timeout (%s)" % why, backend="delegate", ref=resume or "", alive=stop.get("alive"),
                      stop=why, **timing), None
    code, out = res
    try:
        j = json.loads(out.strip().splitlines()[-1]) if out.strip() else None
    except ValueError:
        j = None
    if not isinstance(j, dict):
        return Result(text=out[-2000:], secs=secs, error="route.py exit %d, no answer object" % code,
                      backend="delegate", **timing), None
    st = j.get("status")
    err = "" if st == "done" else "%s: %s" % (st, j.get("say") or "")
    return Result(j.get("data"), j.get("text") or "", j.get("ref") or "", float(j.get("cost") or 0),
                  float(j.get("secs") or secs), err, j.get("family") or "delegate", **timing), j
