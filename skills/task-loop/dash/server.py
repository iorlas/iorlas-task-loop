#!/usr/bin/env python3
"""task-loop dashboard: one read-only server per machine. Python 3.8+, standard library only.

    python3 server.py [--port 7878]

Started by `tl.py dash ensure`. Binds 127.0.0.1 plus the Tailscale address when there is one; TASK_LOOP_DASH_BIND
(comma list, e.g. 0.0.0.0 inside a container) overrides. Exits after TASK_LOOP_DASH_IDLE_H hours (default 6) with
no task-loop event and no page request.

Sources, all local and read-only:
  ~/.config/task-loop/{repos.json,events.jsonl,sessions/}   written by tl.py and its SessionStart hook
  bd list --json in each repo                                the task tree (re-read only when .beads changed)
  ~/.claude/projects/**.jsonl                                Claude sessions and their subagents
  ~/.claude/plugins/data/codex-openai-codex/state/*/jobs     Codex runs (each names the Claude session that started it)
  ~/.codex/sessions/**/rollout-*.jsonl                       Codex runs started directly (codex exec)
  ~/.config/agent-runs/{runs,lanes}                          worker runs and lane limits any launcher publishes
                                                             (docs/contracts/agent-runs-v1.md; delegate is one producer)
"""

import argparse
import glob
import hashlib
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
HOME = Path.home()
PROJECTS = HOME / ".claude" / "projects"
CODEX_JOBS = HOME / ".claude" / "plugins" / "data" / "codex-openai-codex" / "state"
CODEX_SESSIONS = HOME / ".codex" / "sessions"
LIVE_SECONDS = 90          # a transcript written within this is still running
RETAIN = 7 * 86400         # finished tasks and runs stay visible this long
TAIL_BYTES = 6_000_000     # never read more than this from the end of a transcript
STARTED = time.time()
_last_seen = [time.time()]


def config_dir():
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", HOME / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config"))
    return base / "task-loop"


def agent_runs_dir():
    """The agent-runs v1 contract folder: the only place task-loop learns about other tools' workers."""
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", HOME / "AppData" / "Roaming")) / "agent-runs"
    return Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "agent-runs"


def version():
    h = hashlib.sha256()
    for p in sorted(HERE.glob("*")):
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


VERSION = version()
_cache = {}
_lock = threading.Lock()


def cached(key, ttl, fn):
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    val = fn()
    with _lock:
        _cache[key] = (time.time(), val)
    return val


def parse_ts(s):
    if not s:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def read_json(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def tail_lines(path, limit=TAIL_BYTES):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - limit))
            data = f.read()
    except OSError:
        return []
    lines = data.decode("utf-8", "replace").splitlines()
    return lines[1:] if size > limit else lines


def first_json(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return json.loads(f.readline())
    except (OSError, ValueError):
        return {}


# ---- task-loop records ----------------------------------------------------------------------------------------------

def events():
    f = config_dir() / "events.jsonl"

    def load():
        out = []
        cut = time.time() - RETAIN
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                for ln in fh:
                    try:
                        e = json.loads(ln)
                    except ValueError:
                        continue
                    if e.get("t", 0) >= cut:
                        out.append(e)
        except OSError:
            pass
        return out
    try:
        m = f.stat().st_mtime
    except OSError:
        return []
    with _lock:
        hit = _cache.get("events")
    if hit and hit[2] == m:
        return hit[1]
    val = load()
    with _lock:
        _cache["events"] = (time.time(), val, m)
    return val


def repos():
    r = read_json(config_dir() / "repos.json", {}) or {}
    return [p for p in r if os.path.isdir(p)]


def beads_of(repo):
    """bd list for one repo, re-run only when bd's last-touched marker moved (or every 60 s)."""
    marker = Path(repo) / ".beads" / "last-touched"
    try:
        m = marker.stat().st_mtime
    except OSError:
        m = 0
    key = "beads:" + repo
    with _lock:
        hit = _cache.get(key)
    if hit and hit[2] == m and time.time() - hit[0] < 60:
        return hit[1]
    if hit and time.time() - hit[0] < 5:
        return hit[1]
    exe = shutil.which("bd")
    beads = hit[1] if hit else []
    if exe:
        try:
            r = subprocess.run([exe, "list", "--json", "--all", "-n", "0"], cwd=repo, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=30)
            if r.returncode == 0:
                beads = json.loads(r.stdout)
        except (subprocess.SubprocessError, ValueError, OSError):
            pass
    with _lock:
        _cache[key] = (time.time(), beads, m)
    return beads


def transcript_of(session):
    if not session:
        return None
    idx = read_json(config_dir() / "sessions" / (session + ".json"), {}) or {}
    p = idx.get("transcript")
    if p and os.path.exists(p):
        return p

    def find():
        hits = glob.glob(str(PROJECTS / "*" / (session + ".jsonl")))
        return max(hits, key=os.path.getmtime) if hits else None
    return cached("tr:" + session, 30, find)


def session_dirs(session):
    return cached("sd:" + session, 30, lambda: glob.glob(str(PROJECTS / "*" / session)))


# ---- runs: one adapter per harness ----------------------------------------------------------------------------------

def claude_events(path, t0=None, t1=None):
    """Claude transcript (session, subagent, or claude -p stream) -> timeline events."""
    out, pending = [], {}
    for ln in tail_lines(path):
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if d.get("type") not in ("assistant", "user"):
            continue
        t = parse_ts(d.get("timestamp"))
        if t0 and t and t < t0 - 1:
            continue
        if t1 and t and t > t1 + 1:
            break
        content = (d.get("message") or {}).get("content")
        if isinstance(content, str):
            if d["type"] == "user" and content.strip() and not d.get("isMeta"):
                out.append({"t": t, "kind": "user", "text": content.strip()[:4000]})
            continue
        if not isinstance(content, list):
            continue
        for x in content:
            if not isinstance(x, dict):
                continue
            k = x.get("type")
            if k == "tool_use":
                inp = x.get("input") or {}
                text = (inp.get("command") or inp.get("description") or inp.get("file_path") or inp.get("pattern")
                        or inp.get("query") or inp.get("prompt") or inp.get("url") or "")
                e = {"t": t, "kind": "cmd", "tool": x.get("name", ""), "text": str(text).strip()[:600], "state": "run"}
                pending[x.get("id")] = e
                out.append(e)
            elif k == "tool_result":
                e = pending.pop(x.get("tool_use_id"), None)
                if e:
                    e["state"] = "fail" if x.get("is_error") else "ok"
                    e["dur"] = (t - e["t"]) if t and e["t"] else None
                    c = x.get("content")
                    if isinstance(c, list):
                        c = " ".join(y.get("text", "") for y in c if isinstance(y, dict))
                    e["detail"] = str(c)[:3000]
            elif k == "text" and x.get("text", "").strip():
                if d["type"] == "assistant":
                    out.append({"t": t, "kind": "msg", "text": x["text"].strip()[:6000]})
                elif not d.get("isMeta") and not x["text"].startswith("<"):
                    out.append({"t": t, "kind": "user", "text": x["text"].strip()[:4000]})
    return out


CODEX_LINE = re.compile(r"^\[(?P<ts>[^\]]+)\] (?P<body>.*)$")


def codex_log_events(path, t0=None, t1=None):
    """The codex plugin's job log -> timeline events."""
    out, open_cmd = [], None
    for ln in tail_lines(path):
        m = CODEX_LINE.match(ln)
        if not m:
            if out and out[-1]["kind"] == "msg":
                out[-1]["text"] = (out[-1]["text"] + "\n" + ln)[:6000]
            continue
        t, body = parse_ts(m["ts"]), m["body"]
        if body.startswith("Running command: "):
            open_cmd = {"t": t, "kind": "cmd", "tool": "shell", "text": clean_cmd(body[17:]), "state": "run"}
            out.append(open_cmd)
        elif body.startswith(("Command completed: ", "Command failed: ")):
            ok = body.startswith("Command completed")
            target = open_cmd if open_cmd and open_cmd.get("state") == "run" else None
            if target is None:
                target = {"t": t, "kind": "cmd", "tool": "shell", "text": clean_cmd(body.split(": ", 1)[1])}
                out.append(target)
            target.update(state="ok" if ok else "fail", dur=(t - target["t"]) if t and target.get("t") else None)
            open_cmd = None
        elif body.startswith(("Assistant message captured: ", "Assistant message: ")):
            text = body.split(": ", 1)[1]
            if not (out and out[-1]["kind"] == "msg" and out[-1]["text"][:40] == text[:40]):
                out.append({"t": t, "kind": "msg", "text": text})
        elif body.strip() and body.strip() not in ("Assistant message", "Assistant message captured"):
            out.append({"t": t, "kind": "note", "text": re.sub(r"\s*\([0-9a-f-]{20,}\)\.?", "", body)})
    return out


def rollout_events(path, t0=None, t1=None):
    """A Codex rollout file (codex exec / app-server) -> timeline events."""
    out, pending = [], {}
    for ln in tail_lines(path):
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        t = parse_ts(d.get("timestamp"))
        p = d.get("payload") or {}
        typ = p.get("type")
        if d.get("type") == "response_item":
            if typ == "message" and p.get("role") == "assistant":
                text = " ".join(c.get("text", "") for c in p.get("content", []) if isinstance(c, dict)).strip()
                if text:
                    out.append({"t": t, "kind": "msg", "text": text[:6000]})
            elif typ in ("function_call", "custom_tool_call", "local_shell_call"):
                args = p.get("arguments") or p.get("input") or ""
                try:
                    j = json.loads(args) if isinstance(args, str) else args
                    cmd = j.get("cmd") or j.get("command") or args
                    if isinstance(cmd, list):
                        cmd = " ".join(cmd)
                except (ValueError, AttributeError):
                    cmd = args
                e = {"t": t, "kind": "cmd", "tool": p.get("name", "shell"), "text": clean_cmd(str(cmd))[:600], "state": "run"}
                pending[p.get("call_id")] = e
                out.append(e)
            elif typ in ("function_call_output", "custom_tool_call_output"):
                e = pending.pop(p.get("call_id"), None)
                if e:
                    o = str(p.get("output", ""))
                    m = re.search(r"[Ee]xit code:? (-?\d+)", o)
                    e["state"] = "fail" if m and m.group(1) != "0" else "ok"
                    e["dur"] = (t - e["t"]) if t and e["t"] else None
                    e["detail"] = o[:3000]
        elif d.get("type") == "event_msg" and typ == "user_message":
            out.append({"t": t, "kind": "user", "text": str(p.get("message", ""))[:4000]})
    return out


def clean_cmd(s):
    s = re.sub(r"\s*\(exit -?\d+\)\s*$", "", s)
    s = re.sub(r"^(/bin/)?(z|ba)?sh -l?c ", "", s).strip()
    if len(s) > 1 and s[0] in "'\"" and s[-1] == s[0]:
        s = s[1:-1]
    return s


def engine_events(path, t0=None, t1=None):
    """The engine's own log (engine.py): one line per node, decision, command."""
    out = []
    for ln in tail_lines(path):
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        e = {"t": d.get("t"), "kind": d.get("kind", "note"), "text": d.get("text", "")}
        if e["kind"] == "cmd":
            e["tool"], e["state"] = "sh", "ok"
        if e["kind"] == "note" and out and out[-1]["kind"] == "cmd" and str(e["text"]).startswith("exit "):
            out[-1]["state"] = "ok" if d.get("exit") == 0 else "fail"
            out[-1]["detail"] = e["text"]
            continue
        if d.get("data") is not None:
            e["detail"] = json.dumps(d["data"], indent=1)[:6000]
        if d.get("cost"):
            e["text"] += "  ($%.2f, %ss)" % (d["cost"], d.get("secs", "?"))
        out.append(e)
    return out


def engine_runs(bead, t0, t1):
    runs = []
    for path in glob.glob(str(config_dir() / "engine" / ("%s-*.jsonl" % bead))):
        first = first_json(path)
        start = first.get("t") or os.path.getmtime(path)
        if start < t0 - 5 or (t1 and start > t1 + 5):
            continue
        tail = "\n".join(tail_lines(path, 4000)[-3:])
        closed = '"close: ' in tail
        st, m = status_of(path, closed)
        if closed:
            st = "completed" if ('close: landed' in tail or 'close: done' in tail) else "failed"
        runs.append({"id": "engine:" + path, "kind": "engine", "title": "Engine", "role": "runs the task",
                     "status": st, "started": start, "updated": m, "ended": m if closed else None})
    return runs


ADAPTERS = {"engine": engine_events, "claude": claude_events, "subagent": claude_events, "claude-p": claude_events,
            "codex": codex_log_events, "codex-exec": rollout_events}


def status_of(path, done_hint=False):
    try:
        m = os.path.getmtime(path)
    except OSError:
        return "missing", None
    if done_hint:
        return "completed", m
    return ("running" if time.time() - m < LIVE_SECONDS else "idle"), m


def subagent_runs(session, t0=0, t1=None):
    runs = []
    for d in session_dirs(session):
        for path in glob.glob(os.path.join(d, "subagents", "agent-*.jsonl")):
            first = parse_ts(first_json(path).get("timestamp")) or os.path.getmtime(path)
            if first < t0 - 1 or (t1 and first > t1 + 1):
                continue
            meta = read_json(path[:-6] + ".meta.json", {}) or {}
            tail = "\n".join(tail_lines(path, 30000)[-20:])
            done = '"SubagentHandback"' in tail or '"stop_reason":"end_turn"' in tail
            st, m = status_of(path, done)
            runs.append({"id": "subagent:" + path, "kind": "subagent", "title": meta.get("description") or "Subagent",
                         "model": meta.get("model", ""), "role": meta.get("agentType", ""), "status": st,
                         "started": first, "updated": m, "ended": m if done else None})
    return runs


def codex_jobs(since):
    def load():
        jobs = []
        for meta in glob.glob(str(CODEX_JOBS / "*" / "jobs" / "*.json")):
            try:
                if os.path.getmtime(meta) < since:
                    continue
            except OSError:
                continue
            j = read_json(meta, {}) or {}
            if not j.get("id"):
                continue
            log = j.get("logFile") or meta[:-5] + ".log"
            status = j.get("status", "?")
            if status == "running" and not pid_alive(j.get("pid")):
                status = "dead"
            try:
                upd = max(os.path.getmtime(meta), os.path.getmtime(log) if os.path.exists(log) else 0)
            except OSError:
                upd = None
            jobs.append({"id": "codex:" + log, "kind": "codex", "session": j.get("sessionId"),
                         "cwd": j.get("workspaceRoot", ""), "title": (j.get("summary") or "Codex task").split("\n")[0][:110],
                         "model": "Codex", "role": j.get("kindLabel", ""), "status": status,
                         "started": parse_ts(j.get("startedAt") or j.get("createdAt")),
                         "ended": parse_ts(j.get("completedAt")), "updated": upd, "thread": j.get("threadId")})
        return jobs
    return cached("codexjobs:%d" % int(since / 60), 4, load)


def codex_rollouts(since):
    """Codex runs started directly (codex exec), not through the codex plugin."""
    def load():
        out = []
        days = {time.strftime("%Y/%m/%d", time.localtime(time.time() - i * 86400)) for i in range(8)}
        for day in days:
            for path in glob.glob(str(CODEX_SESSIONS / day / "rollout-*.jsonl")):
                try:
                    m = os.path.getmtime(path)
                except OSError:
                    continue
                if m < since:
                    continue
                meta = (first_json(path).get("payload") or {})
                st, _ = status_of(path)
                out.append({"id": "codex-exec:" + path, "kind": "codex-exec", "cwd": meta.get("cwd", ""),
                            "thread": meta.get("id") or meta.get("session_id"), "title": "Codex run",
                            "model": meta.get("model_provider", "Codex"), "status": st,
                            "started": parse_ts(meta.get("timestamp")), "updated": m, "ended": None})
        return out
    return cached("rollouts:%d" % int(since / 60), 5, load)


def contract_runs(since):
    """Run records under agent-runs v1 (docs/contracts/agent-runs-v1.md). Unknown fields ignored, other versions skipped."""
    def load():
        out = []
        for f in glob.glob(str(agent_runs_dir() / "runs" / "*.json")):
            try:
                if os.path.getmtime(f) < since:
                    continue
            except OSError:
                continue
            r = read_json(f, {}) or {}
            if not isinstance(r, dict) or r.get("v") != 1 or not r.get("id"):
                continue
            kind = r.get("kind") or "other"
            path, adapter = None, None
            if r.get("session"):
                path, adapter = transcript_of(r["session"]), "claude-p"
            if not path and r.get("thread"):
                hits = glob.glob(str(CODEX_SESSIONS / "*" / "*" / "*" / ("rollout-*%s.jsonl" % r["thread"])))
                path, adapter = (hits[0], "codex-exec") if hits else (None, None)
            if not path and r.get("transcript") and os.path.exists(r["transcript"]):
                path, adapter = r["transcript"], ("codex-exec" if kind == "codex" else "claude-p")
            st = r.get("status") or "running"
            upd = os.path.getmtime(path) if path and os.path.exists(path) else (r.get("ended") or r.get("started"))
            if st == "running" and upd and time.time() - upd > 6 * 3600:
                st = "dead"
            out.append({"id": "%s:%s" % (adapter, path) if path else "none:" + str(r["id"]), "kind": kind,
                        "parent": r.get("parent_session"), "cwd": r.get("cwd", ""), "thread": r.get("thread"),
                        "title": r.get("title") or kind + " run", "model": r.get("model", ""),
                        "role": r.get("lane", ""), "status": st, "started": r.get("started"),
                        "ended": r.get("ended"), "updated": upd, "producer": r.get("producer")})
        return out
    return cached("contractruns:%d" % int(since / 60), 4, load)


def contract_lanes():
    """Lanes records under agent-runs v1, fresh ones only."""
    out = []
    for f in glob.glob(str(agent_runs_dir() / "lanes" / "*.json")):
        r = read_json(f, {}) or {}
        if not isinstance(r, dict) or r.get("v") != 1 or time.time() - float(r.get("at") or 0) > 6 * 3600:
            continue
        for ln in r.get("lanes") or []:
            if isinstance(ln, dict) and ln.get("name"):
                out.append({"producer": r.get("producer"), "name": ln["name"], "out_until": ln.get("out_until"),
                            "why": ln.get("why"), "usage": [u for u in ln.get("usage") or [] if isinstance(u, dict)]})
    return out


def pid_alive(pid):
    if os.name == "nt":  # os.kill(pid, 0) terminates the process on Windows; trust the job's own status
        return True
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def path_of(run_id):
    return run_id.split(":", 1)[1] if ":" in run_id else ""


def run_for_path(kind, path, title, started=None):
    st, m = status_of(path)
    return {"id": kind + ":" + path, "kind": kind, "title": title, "status": st, "started": started, "updated": m}


# ---- tasks: a bead + the sessions and workers that worked on it ------------------------------------------------------

def task_spans():
    """For each bead: the spans (session, worktree, from, to) between a claim and that session's next record."""
    evs = sorted(events(), key=lambda e: e.get("t", 0))
    spans, open_by_session = {}, {}
    for e in evs:
        s, k, b = e.get("session") or e.get("actor"), e.get("kind"), e.get("bead")
        if k == "claim" and b:
            for prev in spans.get(b, []):  # the bead moved to another session (reclaim): the old span ended
                if prev["to"] is None:
                    prev["to"], prev["end"] = e["t"], "reclaimed"
            span = {"bead": b, "session": e.get("session"), "actor": e.get("actor"), "worktree": e.get("worktree"),
                    "repo": e.get("repo"), "slot": e.get("slot"), "from": e["t"], "to": None, "stage": None,
                    "title": e.get("title"), "end": None, "workers": []}
            spans.setdefault(b, []).append(span)
            open_by_session[s] = span
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


def same_tree(a, b):
    if not a or not b:  # realpath("") is the current folder
        return False
    a, b = os.path.normcase(os.path.realpath(a or "")), os.path.normcase(os.path.realpath(b or ""))
    return bool(a and b) and (a == b or a.startswith(b + os.sep))


def runs_for_span(span):
    t0, t1 = span["from"], span["to"]
    runs = []
    sess = span.get("session")
    tr = transcript_of(sess)
    if tr:
        st, m = status_of(tr)
        runs.append({"id": "claude:%s@%s@%s" % (tr, t0, t1 or ""), "kind": "claude", "title": "Orchestrator session",
                     "role": "orchestrator", "status": st if not t1 else "completed", "started": t0, "updated": m,
                     "ended": t1, "session": sess})
    runs += engine_runs(span["bead"], t0, t1)
    if sess:
        runs += subagent_runs(sess, t0, t1)
        for j in codex_jobs(t0 - 60):
            if j.get("session") != sess or not j.get("started") or j["started"] < t0 - 1 or (t1 and j["started"] > t1 + 1):
                continue
            if span.get("worktree") and j.get("cwd") and not same_tree(j["cwd"], span["worktree"]):
                continue  # one session may drive several tasks, each in its own worktree
            runs.append(j)
    wt = span.get("worktree") or ""
    threads = {r.get("thread") for r in runs if r.get("thread")}
    contract = []
    for j in contract_runs(t0 - 60):
        if j.get("thread") and j["thread"] in threads:
            continue
        if j.get("parent") != sess or not j.get("started") or j["started"] < t0 - 1 or (t1 and j["started"] > t1 + 1):
            continue
        if span.get("worktree") and j.get("cwd") and not same_tree(j["cwd"], span["worktree"]):
            continue
        contract.append(j)
    runs += contract
    threads |= {r.get("thread") for r in contract if r.get("thread")}
    starts = [r["started"] for r in contract if r.get("started") and r.get("kind") == "codex"]
    for j in codex_rollouts(t0 - 60):
        if j.get("thread") in threads:
            continue
        if any(abs((j.get("started") or 0) - s0) < 30 for s0 in starts):
            continue  # the launcher already recorded this run (its thread id may not be written yet)
        if wt and same_tree(j.get("cwd"), wt) and j.get("started") and j["started"] >= t0 - 1 and \
                (not t1 or j["started"] <= t1 + 1):
            runs.append(j)
    for w in span.get("workers", []):
        if w.get("worker_kind") == "claude-p":
            tr2 = transcript_of(w.get("ref"))
            if tr2:
                r = run_for_path("claude-p", tr2, w.get("title") or "claude -p worker", w.get("t"))
                runs.append(r)
    seen, out = set(), []
    for r in runs:
        if r["id"] not in seen:
            seen.add(r["id"])
            out.append(r)
    out.sort(key=lambda r: r.get("started") or 0)
    return out


def summary():
    spans = task_spans()
    now = time.time()
    repo_list = repos()
    data = {"version": VERSION, "now": now, "repos": [], "host": socket.gethostname()}
    for repo in repo_list:
        beads = beads_of(repo)
        by_id = {b["id"]: b for b in beads}
        tasks = []
        for b in beads:
            if b.get("issue_type") == "epic" and not b.get("parent"):
                pass
            sp = spans.get(b["id"], [])
            last = sp[-1] if sp else None
            live = None
            if last and last["to"] is None and b.get("status") == "in_progress":
                tr = transcript_of(last.get("session"))
                upd = os.path.getmtime(tr) if tr and os.path.exists(tr) else last["from"]
                live = {"session": last.get("session"), "actor": last.get("actor"), "worktree": last.get("worktree"),
                        "slot": last.get("slot"), "since": last["from"], "stage": last.get("stage"), "updated": upd}
            closed_t = parse_ts(b.get("closed_at"))
            tasks.append({
                "id": b["id"], "title": b.get("title", ""), "status": b.get("status"), "type": b.get("issue_type"),
                "priority": b.get("priority"), "parent": b.get("parent"), "labels": b.get("labels") or [],
                "assignee": b.get("assignee"), "deps": len(b.get("dependencies") or []),
                "updated": parse_ts(b.get("updated_at")), "closed": closed_t, "live": live,
                "spans": len(sp), "slot": "slot" in (b.get("labels") or []),
            })
        data["repos"].append({"path": repo, "name": os.path.basename(repo), "tasks": tasks,
                              "counts": count_status(tasks), "known": len(by_id)})
    data["lanes"] = contract_lanes()
    return data


def count_status(tasks):
    c = {}
    for t in tasks:
        if t["slot"]:
            continue
        c[t["status"]] = c.get(t["status"], 0) + 1
    c["live"] = sum(1 for t in tasks if t["live"])
    return c


def resolve_repo(repo, bead=""):
    """A link may name a repo by path or by folder name, or not at all: find the registered repo it means."""
    known = repos()
    if repo in known:
        return repo
    named = [p for p in known if os.path.basename(p.rstrip("/\\")) == repo]
    if named:
        return named[0]
    return next((p for p in known if bead and any(x["id"] == bead for x in beads_of(p))), "")


def task_detail(repo, bead):
    spans = task_spans().get(bead, [])
    repo = resolve_repo(repo, bead)
    b = next((x for x in beads_of(repo) if x["id"] == bead), {}) if repo else {}
    return {"bead": {k: b.get(k) for k in ("id", "title", "status", "description", "acceptance_criteria", "assignee",
                                           "labels", "priority", "parent", "issue_type", "notes", "updated_at")},
            "spans": [dict({k: v for k, v in s.items() if k != "workers"}, runs=runs_for_span(s)) for s in spans]}


def all_runs(hours):
    since = time.time() - hours * 3600
    runs = []
    for path in glob.glob(str(PROJECTS / "*" / "*" / "subagents" / "agent-*.jsonl")):
        try:
            if os.path.getmtime(path) < since:
                continue
        except OSError:
            continue
        sess = os.path.basename(os.path.dirname(os.path.dirname(path)))
        for r in subagent_runs(sess, 0, None):
            if r["id"] == "subagent:" + path:
                r["where"] = os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(path)))).split("-")[-1]
                runs.append(r)
    for j in codex_jobs(since) + codex_rollouts(since) + contract_runs(since):
        j = dict(j)
        j["where"] = os.path.basename(j.get("cwd") or "")
        runs.append(j)
    order = {"running": 0, "queued": 1, "dead": 2, "failed": 2, "idle": 3, "completed": 4}
    runs.sort(key=lambda r: (order.get(r.get("status"), 5), -(r.get("updated") or 0)))
    return runs[:300]


def run_events(run_id, limit=800):
    kind, rest = run_id.split(":", 1)
    t0 = t1 = None
    path = rest
    if kind == "claude" and "@" in rest:
        path, a, b = rest.rsplit("@", 2)
        t0, t1 = float(a) if a else None, float(b) if b else None
    fn = ADAPTERS.get(kind)
    if not fn or not os.path.exists(path):
        return []
    evs = fn(path, t0, t1)
    return evs[-limit:]


# ---- server ---------------------------------------------------------------------------------------------------------

def tailscale_ip():
    exe = shutil.which("tailscale") or ("/Applications/Tailscale.app/Contents/MacOS/Tailscale"
                                          if os.path.exists("/Applications/Tailscale.app") else None)
    if exe:
        try:
            r = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3)
            ip = r.stdout.strip().splitlines()[0] if r.returncode == 0 and r.stdout.strip() else ""
            if ip:
                return ip
        except (subprocess.SubprocessError, OSError, IndexError):
            pass
    cgnat = ipaddress.ip_network("100.64.0.0/10")
    for cmd in (["ip", "-4", "-o", "addr"], ["ifconfig"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        for ip in re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", out):
            if ipaddress.ip_address(ip) in cgnat:
                return ip
    return None


def bind_addrs():
    env = os.environ.get("TASK_LOOP_DASH_BIND")
    if env:
        return [x.strip() for x in env.split(",") if x.strip()]
    ts = tailscale_ip()
    return ["127.0.0.1"] + ([ts] if ts else [])


def urls(addrs, port):
    out = []
    for a in addrs:
        if a == "0.0.0.0":
            out.append("http://%s:%d" % (socket.gethostname(), port))
        else:
            out.append("http://%s:%d" % (a, port))
    return out


def make_handler(port, addrs):
    page = HERE / "index.html"

    class H(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path == "/api/version":
                    body = {"version": VERSION, "pid": os.getpid(), "urls": urls(addrs, port), "started": STARTED}
                elif u.path == "/api/summary":
                    _last_seen[0] = time.time()
                    body = summary()
                elif u.path == "/api/task":
                    body = task_detail(q.get("repo", ""), q.get("id", ""))
                elif u.path == "/api/runs":
                    body = all_runs(float(q.get("hours", "24")))
                elif u.path == "/api/events":
                    body = run_events(q.get("id", ""))
                elif u.path in ("/", "/index.html"):
                    return self.send(200, page.read_bytes(), "text/html; charset=utf-8")
                else:
                    return self.send(404, b"not found", "text/plain")
            except Exception as e:  # a broken transcript must not take the page down
                body = {"error": "%s: %s" % (type(e).__name__, e)}
                return self.send(500, json.dumps(body).encode(), "application/json")
            self.send(200, json.dumps(body, default=str).encode(), "application/json")
    return H


def idle_watch(hours):
    while True:
        time.sleep(300)
        f = config_dir() / "events.jsonl"
        try:
            last_event = f.stat().st_mtime
        except OSError:
            last_event = STARTED
        if time.time() - max(last_event, _last_seen[0], STARTED) > hours * 3600:
            os._exit(0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7878)
    a = ap.parse_args()
    addrs = bind_addrs()
    handler = make_handler(a.port, addrs)
    servers = []
    for addr in addrs:
        try:
            servers.append(ThreadingHTTPServer((addr, a.port), handler))
        except OSError as e:
            print("bind %s:%d failed: %s" % (addr, a.port, e), file=sys.stderr)
    if not servers:
        sys.exit(1)
    config_dir().mkdir(parents=True, exist_ok=True)
    (config_dir() / "dash.pid").write_text(str(os.getpid()))
    for s in servers[1:]:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    threading.Thread(target=idle_watch, args=(float(os.environ.get("TASK_LOOP_DASH_IDLE_H", "6")),), daemon=True).start()
    print("task-loop dashboard %s on %s" % (VERSION, ", ".join(urls(addrs, a.port))), flush=True)
    servers[0].serve_forever()


if __name__ == "__main__":
    main()
