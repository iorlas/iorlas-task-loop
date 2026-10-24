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
from urllib.parse import parse_qs, quote, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gallery  # noqa: E402
import graph  # noqa: E402
import roadmap  # noqa: E402
import signals  # noqa: F401,E402
import timeline  # noqa: E402
from timeline import block_detail, run_timeline  # noqa: E402,F401  (the engine tests read them here)
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
        if t0 and t and t < t0:
            continue
        if t1 and t and t > t1:
            break
        p = d.get("payload") or {}
        typ = p.get("type")
        if d.get("type") == "response_item":
            if typ == "message" and p.get("role") == "assistant":
                text = " ".join(c.get("text", "") for c in p.get("content", []) if isinstance(c, dict)).strip()
                if text:
                    out.append({"t": t, "kind": "msg", "text": text[:6000]})
            elif typ in ("function_call", "custom_tool_call", "local_shell_call"):
                args = p.get("arguments") or p.get("input") or ""
                cmds = exec_cmds(args)
                try:
                    j = json.loads(args) if isinstance(args, str) else args
                    cmd = j.get("cmd") or j.get("command") or args
                    if isinstance(cmd, list):
                        cmd = " ".join(cmd)
                except (ValueError, AttributeError):
                    cmd = args
                if cmds:
                    cmd = "\n".join(cmds)
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


EXEC_CMD = re.compile(r'exec_command\(\{\s*"?cmd"?\s*:\s*("(?:[^"\\]|\\.)*")')


def exec_cmds(src):
    """The shell commands in a Codex `exec` tool call, whose input is code: text(await tools.exec_command({cmd:"..."}))."""
    if not isinstance(src, str) or "exec_command(" not in src:
        return []
    out = []
    for m in EXEC_CMD.finditer(src):
        try:
            out.append(json.loads(m.group(1)))
        except ValueError:
            out.append(m.group(1)[1:-1])
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
        if d.get("kind") in ("end", "transition", "checks", "run"):  # the task view's records
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
        tail = "\n".join(tail_lines(path, 8000)[-8:])  # end, transition and warn records may follow the close
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


def split_window(rest):
    """`path@t0@t1` (either time may be empty) -> (path, t0, t1); a plain path has no window."""
    parts = rest.rsplit("@", 2)
    if len(parts) == 3:
        try:
            return parts[0], float(parts[1]) if parts[1] else None, float(parts[2]) if parts[2] else None
        except ValueError:
            pass
    return rest, None, None


def run_events(run_id, limit=800):
    kind, rest = run_id.split(":", 1)
    path, t0, t1 = split_window(rest)
    fn = ADAPTERS.get(kind)
    if not fn or not os.path.exists(path):
        return []
    evs = fn(path, t0, t1)
    return evs[-limit:]


# ---- the task view: tasks, a task's runs, one block (timeline.py builds them from the engine logs) -----------------

RUN_NAME = re.compile(r"^[\w.-]+-\d{8}-\d{6}$")
STALE_RUN = 20 * 60  # a run with no close, no engine lock to ask and no log write for this long has stopped


def engine_logs(retain=True):
    """bead -> its engine logs, oldest first."""
    cut = time.time() - RETAIN if retain else 0
    out = {}
    for p in glob.glob(str(config_dir() / "engine" / "*.jsonl")):
        name = timeline.run_name(p)
        bead = timeline.bead_of(name)
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


def traces():
    """run -> its traces.jsonl line, re-read when the file changes."""
    f = config_dir() / "traces.jsonl"
    try:
        m = f.stat().st_mtime
    except OSError:
        return {}
    with _lock:
        hit = _cache.get("traces")
    if hit and hit[2] == m:
        return hit[1]
    out = {}
    for ln in tail_lines(str(f), 20_000_000):
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("run"):
            out[r["run"]] = r
    with _lock:
        _cache["traces"] = (time.time(), out, m)
    return out


def open_ask(bead):
    a = read_json(config_dir() / "asks" / ("%s.json" % bead), {}) or {}
    if not isinstance(a, dict) or a.get("status") != "open":
        return None
    a = upgrade_ask(a)
    return {k: a.get(k) for k in ("id", "kind", "question", "detail", "unblocks", "t", "title", "answer", "repo", "parks_at", "options")}


def ask_file(bead):
    a = read_json(config_dir() / "asks" / ("%s.json" % bead), {}) or {}
    return a if isinstance(a, dict) else {}


def blocker_of(bead, repo_hint=""):
    """The first open bead this one depends on with a `blocks` dependency, as {id, title}; None when there is none.
    Reads the repo's cached `bd list` (beads_of): one bd call per repo per refresh, never one per task."""
    repo = repo_hint if repo_hint in repos() else ""
    if not repo:
        name = re.sub(r"\.git$", "", os.path.basename((repo_hint or "").rstrip("/\\")))
        repo = resolve_repo(name, bead) if name else resolve_repo("", bead)
    if not repo:
        return None
    by_id = {b.get("id"): b for b in beads_of(repo)}
    me = by_id.get(bead) or {}
    if me.get("status") == "closed":
        return None
    for d in me.get("dependencies") or []:
        if d.get("type") != "blocks":
            continue
        dep = by_id.get(d.get("depends_on_id")) or {}
        if dep and dep.get("status") != "closed":
            return {"id": dep["id"], "title": dep.get("title") or ""}
    return None


def run_alive(path, run, span):
    """A run with no close: running while the engine lock in its worktree names a live process for its bead; without
    a lock to read, while its log moved lately."""
    bead = timeline.bead_of(timeline.run_name(path))
    wt = (run or {}).get("worktree") or (span or {}).get("worktree") or ""
    if wt:
        lock = read_json(os.path.join(wt, ".task", "engine.lock"), {}) or {}
        if lock:
            return lock.get("bead") == bead and bool(lock.get("pid")) and pid_alive(lock.get("pid"))
        if run:
            return False
    try:
        m = max(os.path.getmtime(path), os.path.getmtime(path[:-6] + ".stderr") if os.path.exists(
            path[:-6] + ".stderr") else 0)
    except OSError:
        return False
    return time.time() - m < STALE_RUN


def slot_of(run, span, trace):
    for wt in ((run or {}).get("slot"), (span or {}).get("slot")):
        if wt:
            return wt
    wt = (run or {}).get("worktree") or (trace or {}).get("worktree") or (span or {}).get("worktree") or ""
    return os.path.basename(wt.rstrip("/\\")) if wt else ""


def repo_name(span, trace, ask):
    r = (span or {}).get("repo") or (ask or {}).get("repo") or (trace or {}).get("repo") or ""
    r = r.rstrip("/\\")
    return re.sub(r"\.git$", "", os.path.basename(r)) if r else ""


TASK_STATES = {"running": 0, "asks": 1, "paused": 2, "queued": 2, "blocked_by": 2, "waiting": 3, "stopped": 4, "failed": 4, "blocked": 4,
               "landed": 5, "done": 5}


def wait_label(recs):
    """"waiting for Codex until 09:02" while the engine sleeps in its slot for a lane, else "". The engine logs the
    lane_wait transition (lane, until) before it sleeps; the next step's node or transition ends the wait."""
    last = next((r for r in reversed(recs) if r.get("kind") in ("transition", "node")), None)
    if not last or last.get("cause") != "lane_wait" or float(last.get("until") or 0) <= time.time():
        return ""
    who = timeline.lane_name(last.get("lane") or "", "")
    return ("waiting for %s until %s" % (who, timeline.when(last["until"]))) if who else ""


def task_row(bead, paths, spans, tr):
    newest = paths[-1]
    name = timeline.run_name(newest)
    span = (spans.get(bead) or [None])[-1]
    recs = timeline.read(newest)
    run_rec = next((r for r in reversed(recs) if r.get("kind") == "run"), None)
    closed = any(r.get("kind") == "node" and str(r.get("text") or "").startswith("close:") for r in recs[-40:])
    alive = not closed and run_alive(newest, run_rec, span)
    run = timeline.run_timeline(newest, alive=alive)
    end, ask = run["end"], open_ask(bead)
    state, label = end["outcome"], end["text"]
    trace = tr.get(name)
    # the status, in order: running; an open ask; an open `blocks` dependency; the last run's close reason
    blocked = None if alive or ask else blocker_of(bead, (span or {}).get("repo") or ask_file(bead).get("repo") or
                                                    (trace or {}).get("repo") or "")
    if alive:
        state, label = "running", wait_label(recs) or timeline.live_label(timeline.last_node(newest))
    elif ask:
        state, label = "asks", "waiting for your answer"
    elif blocked:
        state, label = "blocked_by", "blocked by %s%s" % (blocked["id"], (" (%s)" % blocked["title"]) if blocked["title"] else "")
    elif state in ("asks", "waiting"):  # no ask is open: never say it waits for one
        if ask_file(bead).get("status") == "answered":
            state, label = "queued", "answered: waits for the next run"
        else:
            why = (end.get("why") or "").split("\n")[0].strip()
            state, label = "stopped", "ask closed" + (": " + why[:120] if why else "")
    elif state == "paused":
        label = "paused: %s%s" % (end.get("reason") or "no lane", (" until " + end["until"]) if end.get("until") else "")
    elif state == "stopped":
        label = "stopped"
    started = run["started"] or 0
    total, spent, nblocks, reds, longest_check, replans, checks_secs = 0, {"in": 0, "cached": 0, "out": 0}, 0, 0, 0, 0, 0
    writes, sendbacks, big_turn = 0, 0, 0
    for p in paths:
        r = run if p == newest else timeline.run_timeline(p)
        total += r["secs"] or 0
        for k in spent:
            spent[k] += (r["tokens"] or {}).get(k) or 0
        nblocks += len(r["blocks"])
        for b in r["blocks"]:
            if b["kind"] == "checks":
                reds += (b.get("result") or {}).get("status") == "fail"
                longest_check = max(longest_check, b.get("secs") or 0)
                checks_secs += b.get("secs") or 0
            replans += b["kind"] == "replan"
            if b["kind"] == "write":
                writes += 1
                big_turn = max(big_turn, ((b.get("tokens") or {}).get("in") or 0) + ((b.get("tokens") or {}).get("out") or 0))
            sendbacks += (b.get("arrow") or {}).get("cause") == "review_sendback"
    last_t = (recs[-1].get("t") if recs else None) or started
    return {"id": bead, "title": (span or {}).get("title") or (ask or {}).get("title") or "", "state": state,
            "label": label, "slot": slot_of(run_rec, span, trace), "repo": repo_name(span, trace, ask),
            "runs": len(paths), "run": name, "started": started, "updated": last_t,
            "since": round(time.time() - started) if alive and started else None, "secs": total,
            "run_secs": run["secs"], "ask": ask, "blocked_by": blocked, "end": end, "tokens": run["tokens"],
            "tokens_all": spent, "blocks": nblocks, "red_checks": reds, "longest_check": longest_check,
            "replans": replans, "checks_secs": checks_secs, "writes": writes, "sendbacks": sendbacks, "big_turn": big_turn,
            "stage": timeline.live_label(timeline.last_node(newest)) if alive else ""}


def api_tasks():
    """The home page: one row per bead the engine ran in the last week, newest state first."""
    _last_seen[0] = time.time()
    spans, tr = task_spans(), traces()
    rows = []
    for bead, paths in engine_logs().items():
        try:
            rows.append(task_row(bead, paths, spans, tr))
        except Exception as e:  # one broken log must not hide the others
            rows.append({"id": bead, "title": "", "state": "failed", "label": "unreadable log: %s" % e, "runs": len(paths),
                         "updated": 0, "slot": "", "repo": "", "ask": None})
    rows.sort(key=lambda r: (TASK_STATES.get(r["state"], 4), -(r.get("updated") or 0)))
    return {"version": VERSION, "now": time.time(), "host": socket.gethostname(), "tasks": rows,
            "lanes": contract_lanes()}


_queue_lock = threading.Lock()


def _engine_dir():
    d = str(HERE.parent)
    if d not in sys.path:
        sys.path.insert(0, d)


def loop_order(repo, beads, cfg):
    """([(id, reason)] in the order the loop takes them, [(id, why skipped)]). The queue rule costs seconds (bd ready,
    one bd show per epic) and beads change all day, so a page view never waits for it: it gets the last answer
    (refreshed in the background every minute), or graph.local_queue() until the first answer is in."""
    key = "queue:" + repo
    with _lock:
        hit = _cache.get(key)
        fresh = hit and time.time() - hit[0] < 60
        if not fresh and key not in _busy:
            _busy.add(key)
            threading.Thread(target=_refresh_queue, args=(key, repo, beads, cfg), daemon=True).start()
    return hit[1] if hit else _local_order(beads, cfg)


def loop_queue(repo, beads, cfg):
    """The ids the loop would take (the Plan states and tests read a set)."""
    return {i for i, _ in loop_order(repo, beads, cfg)[0]}


def _local_order(beads, cfg):
    ids = graph.local_queue(beads, cfg)
    pri = {b["id"]: b.get("priority") if b.get("priority") is not None else 2 for b in beads}
    return [(i, "") for i in sorted(ids, key=lambda i: (pri[i], i))], []


_busy = set()


def _refresh_queue(key, repo, beads, cfg):
    try:
        val = _loop_queue(repo, beads, cfg)
        with _lock:
            _cache[key] = (time.time(), val)
    finally:
        with _lock:
            _busy.discard(key)


def _loop_queue(repo, beads, cfg):
    """loop.queue(), the loop's own rule, with its git fetch switched off (a page view writes nothing):
    ([(id, reason)], [(id, why)]); graph.local_queue() when loop.py cannot be loaded or bd fails."""
    try:
        _engine_dir()
        import loop
        import tl
        with _queue_lock:
            real, tl.fetch = tl.fetch, lambda *a, **k: None
            try:
                ranked, skipped = loop.queue(repo)
            finally:
                tl.fetch = real
        return [(b["id"], r) for b, r in ranked], list(skipped)
    except Exception:
        return _local_order(beads, cfg)
    except SystemExit:  # tl.bd exits when bd is not on PATH
        return _local_order(beads, cfg)


def api_graph(repo=""):
    """The Plan tab: one repo's open beads (plus the last day's closes) as nodes, blocking dependencies as edges."""
    _last_seen[0] = time.time()
    known = repos()
    path = resolve_repo(repo, "") if repo else (known[0] if known else "")
    names = [os.path.basename(p.rstrip("/\\")) for p in known]
    if not path:
        return {"repo": "", "repos": names, "nodes": [], "edges": [], "summary": {}, "error": "no such repo"}
    beads = beads_of(path)

    def build():
        try:
            _engine_dir()
            import engine
            cfg = engine.load_cfg(path)
        except Exception:
            cfg = {"pick_label": "auto", "skip_labels": []}
        run = {t["id"] for t in api_tasks()["tasks"] if t.get("state") == "running"}
        ask_ids = {b["id"] for b in beads if b.get("status") != "closed" and open_ask(b["id"])}
        return graph.build(beads, cfg, loop_queue(path, beads, cfg), run, ask_ids,
                           repo=os.path.basename(path.rstrip("/\\")))

    out = cached("graph:" + path, 5, build)
    return dict(out, repos=names)


def bd_json(repo, *args):
    exe = shutil.which("bd")
    if not exe or not repo:
        return None
    try:
        r = subprocess.run([exe, *args, "--json"], cwd=repo, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=20)
        return json.loads(r.stdout) if r.returncode == 0 else None
    except (subprocess.SubprocessError, ValueError, OSError):
        return None


def bead_runs(bead, alive=False):
    """Every engine run of the bead, oldest first: why it started, its blocks with outcome, arrow, time and tokens. -> (runs,
    the run timelines for timeline.bead_segments). The last run is alive when the bead is running: its open step ends now."""
    runs, prev, tls = [], None, []
    logs = engine_logs(retain=False).get(bead, [])
    for n, p in enumerate(logs):
        r = timeline.run_timeline(p, alive=alive and n == len(logs) - 1)
        tls.append(r)
        r["because"] = timeline.because_text(r, prev)
        prev = r
        runs.append({"run": r["run"], "because": r["because"], "started": r["started"], "secs": r["secs"],
                     "tokens": r["tokens"], "end": r["end"].get("text") or r["end"].get("outcome"), "outcome": r["end"].get("outcome"),
                     "blocks": [{"kind": x["kind"], "label": x["label"], "stage": x.get("stage_index"), "stages": x.get("stage_count"),
                                 "secs": x.get("secs"), "tokens": x.get("tokens"), "status": (x.get("result") or {}).get("status"),
                                 "text": (x.get("result") or {}).get("text"), "arrow": (x.get("arrow") or {}).get("text")}
                                for x in r["blocks"]]})
    return runs, tls


def api_bead(repo, bead):
    """One bead for the Roadmap's panel: what bd says (description, acceptance, comments, dependencies) and every run of
    the engine on it (why it started, each block with its outcome and the arrow into it, tokens)."""
    _last_seen[0] = time.time()
    if not re.match(r"^[A-Za-z0-9][\w.-]*$", bead or ""):  # an id is never a bd option
        return {"id": bead, "found": False, "error": "not a bead id"}
    path = resolve_repo(repo, bead)

    def load():
        shown = bd_json(path, "show", bead)
        b = (shown[0] if isinstance(shown, list) and shown else shown) or {}
        comments = bd_json(path, "comments", bead) or []
        return b, comments
    b, comments = cached("bead:%s:%s" % (path, bead), 15, load)
    try:
        alive = any(t["id"] == bead and t.get("state") == "running" for t in api_tasks()["tasks"])
    except Exception:
        alive = False
    runs, tls = cached("beadruns:%s:%s:%d" % (path, bead, alive), 5 if alive else 15, lambda: bead_runs(bead, alive))
    now = time.time()
    deps = [{"id": d.get("id") or d.get("depends_on_id"), "title": d.get("title"), "status": d.get("status"),
             "type": d.get("dependency_type") or d.get("type")} for d in (b.get("dependencies") or [])]
    return {"id": bead, "title": b.get("title") or "", "status": b.get("status"), "priority": b.get("priority"),
            "labels": b.get("labels") or [], "assignee": b.get("assignee"), "created_at": b.get("created_at"),
            "description": b.get("description") or "", "notes": b.get("notes") or "",
            "acceptance": b.get("acceptance_criteria") or "", "design": b.get("design") or "", "deps": deps,
            "comments": [{"author": c.get("author"), "text": c.get("text"), "at": c.get("created_at")} for c in comments],
            "runs": runs, "found": bool(b), "timeline": timeline.bead_segments(tls, now)}


def loop_version(pid):
    """The task-loop version a loop process runs from its plugin cache path (`ps`); '' when unknown (a dev checkout, Windows)."""
    try:
        out = subprocess.run(["ps", "-o", "command=", "-p", str(pid)], capture_output=True, text=True, timeout=5).stdout
    except (subprocess.SubprocessError, OSError):
        return ""
    m = re.search(r"iorlas-task-loop/(\d+\.\d+\.\d+)/", out)
    return m.group(1) if m else ""


def loop_files(repo):
    """(lanes, rows, waiting loops): one lane per slot (roadmap.lanes_of), the repo's pass log rows oldest first. Read only: a
    dead loop's state file is left (loop.live_loops would delete it)."""
    _engine_dir()
    import loop
    import tl
    d, key = loop.paths(repo)["states"]
    loops = []
    for f in [d / (key + ".json")] + sorted(d.glob(key + ".*.json")):
        st = read_json(str(f), {}) or {}
        if isinstance(st, dict) and st.get("pid") and tl.pid_alive(st["pid"]):
            loops.append({"pid": st["pid"], "slot": st.get("slot") or "", "bead": st.get("bead"), "since": st.get("since"),
                          "started": st.get("started") or 0, "version": loop_version(st["pid"])})
    try:
        slots = [b["title"].split()[-1] for b in tl.slot_beads(repo)]
        running = loop.running(repo)
    except Exception:
        slots, running = [], {}
    try:
        sf = loop.paths(repo)["stop"]
        stop = (sf.stat().st_mtime, sf.read_text().strip() or "after")
    except OSError:
        stop = (0, "")
    lanes, waiting = roadmap.lanes_of(slots, running, loops, stop)
    rows = []
    try:
        for line in Path(loop.paths(repo)["log"]).read_text(encoding="utf-8", errors="replace").splitlines()[-400:]:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("bead"):
                rows.append(row)
    except OSError:
        pass
    return lanes, rows, waiting


def api_roadmap(repo=""):
    """The Roadmap tab: one lane per slot with its bead, stage rail, unlocks and last passes, then the queue in the
    order the loop takes it, each with the beads it unblocks as a tree."""
    _last_seen[0] = time.time()
    g = api_graph(repo)
    if g.get("error"):
        return dict(g, lanes=[], queue=[], held=[], recent=[], summary={})
    path = resolve_repo(g["repo"], "")

    def build():
        beads = beads_of(path)
        try:
            _engine_dir()
            import engine
            cfg = engine.load_cfg(path)
        except Exception:
            cfg = {"pick_label": "auto", "skip_labels": []}
        ranked, skipped = loop_order(path, beads, cfg)
        try:
            lanes, rows, waiting = loop_files(path)
        except Exception:
            lanes, rows, waiting = [], [], []
        api = api_tasks()
        tasks = {t["id"]: t for t in api["tasks"]}
        held = {l["bead"] for l in lanes if l["bead"]}
        for t in tasks.values():  # a bead run by hand (tl run-task) has a slot but no loop
            if t.get("state") == "running" and t["id"] not in held and t.get("repo") == g["repo"]:
                free = next((l for l in lanes if l["slot"] == t.get("slot") and not l["bead"]), None)
                since = time.time() - (t.get("since") or 0)
                if free:
                    free["bead"], free["since"] = t["id"], since
                else:
                    lanes.append({"slot": t.get("slot") or "-", "bead": t["id"], "since": since})
        trails, logs = {}, engine_logs(retain=False)
        for ln in lanes:
            b = ln["bead"]
            if not b or b not in logs:
                continue
            try:
                r = timeline.run_timeline(logs[b][-1], alive=True)
            except Exception:
                continue
            ln["since"] = ln["since"] or (tasks.get(b) or {}).get("started")
            trails[b] = {"run": len(logs[b]), "stage": (tasks.get(b) or {}).get("stage") or "",
                         "blocks": [{"kind": x["kind"], "label": x["label"], "stage": x.get("stage_index"),
                                     "stages": x.get("stage_count"), "secs": x.get("secs"),
                                     "status": (x.get("result") or {}).get("status"), "text": (x.get("result") or {}).get("text")}
                                    for x in r["blocks"]]}
        mine_asks = [a for a in asks()["asks"] if os.path.basename(str(a.get("repo") or "").rstrip("/\\")) == g["repo"]]
        looks = [i for i in look_items(path)[1] if i["status"] == "open"]
        return roadmap.build(g, lanes, ranked, skipped, rows, trails, rows=tasks, lane_records=api["lanes"], asks=mine_asks, waiting=len(waiting),
                             looks=looks)

    out = cached("roadmap:" + path, 5, build)
    return dict(out, repos=g["repos"])


def look_items(repo):
    """Items of the repo's owner-look beads, cached 10 s; the key follows the beads' own marker so an answer shows at once."""
    path = (resolve_repo(repo, "") if repo else (repos() or [""])[0]) or ""
    if not path:
        return "", []
    return path, cached("looks:" + path, 10, lambda: gallery.collect(path, beads_of(path)))


def api_looks(repo=""):
    """The gallery: every look item of the repo, open ones first (newest bead last), with counts."""
    _last_seen[0] = time.time()
    path, items = look_items(repo)
    if not path:
        return {"repo": repo, "items": [], "summary": {"open": 0, "good": 0, "redo": 0}, "repos": [os.path.basename(p) for p in repos()]}
    order = {"open": 0, "redo": 1, "good": 2}
    items = sorted(items, key=lambda i: (order[i["status"]], -(i["answered"] or 0)))
    for i in items:
        for sh in i["shots"]:
            sh["url"] = "/api/look-shot?repo=%s&path=%s" % (quote(os.path.basename(path.rstrip("/\\"))), quote(sh["path"]))
    return {"repo": os.path.basename(path.rstrip("/\\")), "items": items, "summary": gallery.summary(items),
            "repos": [os.path.basename(p) for p in repos()]}


def look_shot(repo, rel):
    path, items = look_items(repo)
    return gallery.picture(path, rel, items) if path else None


def answer_look(body):
    path = resolve_repo(body.get("repo") if isinstance(body, dict) and isinstance(body.get("repo"), str) else "", "")
    if not path:
        return 404, {"code": "repo_missing", "error": "That repo is not registered."}
    code, out = gallery.answer(path, body)
    with _lock:
        _cache.pop("looks:" + path, None)
        _cache.pop("roadmap:" + path, None)
    return code, out


def api_task_timeline(repo, bead):
    """Every run of the bead, oldest first, each with its blocks and arrows."""
    paths = engine_logs(retain=False).get(bead, [])
    spans, tr = task_spans(), traces()
    runs = []
    for p in paths:
        alive = False
        if p == paths[-1]:
            recs = timeline.read(p)
            rr = next((r for r in reversed(recs) if r.get("kind") == "run"), None)
            closed = any(r.get("kind") == "node" and str(r.get("text") or "").startswith("close:") for r in recs[-40:])
            alive = not closed and run_alive(p, rr, (spans.get(bead) or [None])[-1])
        r = timeline.run_timeline(p, alive=alive)
        r["because"] = timeline.because_text(r, runs[-1] if runs else None)
        runs.append(r)
    row = task_row(bead, paths, spans, tr) if paths else {"id": bead, "title": "", "state": "", "label": "no runs",
                                                            "ask": open_ask(bead)}
    return {"task": row, "runs": runs}


def run_path(run):
    if not isinstance(run, str) or not RUN_NAME.match(run):
        return None
    p = config_dir() / "engine" / (run + ".jsonl")
    return str(p) if p.exists() else None


def find_transcript(family, ref):
    if not ref:
        return ""
    if family == "openai":
        hits = glob.glob(str(CODEX_SESSIONS / "*" / "*" / "*" / ("rollout-*%s.jsonl" % ref)))
    else:
        hits = glob.glob(str(PROJECTS / "*" / ("%s.jsonl" % ref)))
    return max(hits, key=os.path.getmtime) if hits else ""


def api_block(run, node, k=0):
    """One block: the transcript to show (an /api/events id, cut to the block's time), its round's checks with their
    logs, the engine lines of its step."""
    path = run_path(run)
    if not path:
        return {"error": "no such run"}
    d = block_detail(path, node, k)
    if d.get("error"):
        return d
    s, b = d.get("session") or {}, d["block"]
    tr = s.get("transcript") if s.get("transcript") and os.path.exists(s["transcript"]) else \
        find_transcript(s.get("family") or b["who"]["family"], s.get("ref"))
    d["events_id"] = ("%s:%s@%s@%s" % ("codex-exec" if (s.get("family") or b["who"]["family"]) == "openai" else
                                       "claude-p", tr, (b["t0"] or 0) - 30, (b["t1"] or 0) + 30)) if tr else ""
    d["transcript"] = tr
    rdir = config_dir() / "runs" / run
    legacy_ids = {}
    if d.get("checks_last"):
        for c in read_json(rdir / "engine-checks.json", []) or []:
            if isinstance(c, dict) and c.get("cmd"):
                legacy_ids[c["cmd"]] = c.get("id") or c["cmd"]
    files = sorted(os.listdir(str(rdir / "checks"))) if (rdir / "checks").is_dir() else []
    for c in d["checks"]:
        rel = c.get("log") or ""
        if not rel and legacy_ids:
            cid = legacy_ids.get(c["cmd"], c["cmd"])
            if c["cmd"] in legacy_ids:
                c["id"] = cid
            safe = re.sub(r"[^\w.-]+", "_", cid)[:40]
            hit = [f for f in files if re.match(r"^\d\d-%s\.log$" % re.escape(safe), f)]
            rel = "checks/" + hit[0] if hit else ""
        c["log_url"] = ("/api/file?run=%s&path=%s" % (run, rel)) if rel and (rdir / rel).is_file() else ""
    return d


def run_file(run, rel):
    """A check log or the plan of a run, never anything else (a symlink out of the folder included)."""
    if not isinstance(run, str) or not RUN_NAME.match(run) or not isinstance(rel, str):
        return None
    parts = rel.replace("\\", "/").split("/")
    if ".." in parts or not (rel == "plan.json" or (len(parts) >= 2 and parts[0] == "checks" and all(parts))):
        return None  # check logs and the plan only: brief and evidence stay off an unauthenticated page
    base = (config_dir() / "runs" / run).resolve()
    try:
        p = (base / rel).resolve()
    except (OSError, ValueError):
        return None
    if base not in p.parents or not p.is_file():
        return None
    with open(str(p), "rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 4_000_000))
        return f.read()


# ---- server ---------------------------------------------------------------------------------------------------------

# ---- asks: the owner's answers (the only writes this server makes) --------------------------------------------------

def token():
    """A secret for answer POSTs from outside loopback and Tailscale, made once (0600). `tl dash url` prints the links with it."""
    f = config_dir() / "dash.token"
    try:
        t = f.read_text().strip()
        if t:
            return t
    except OSError:
        pass
    import secrets
    config_dir().mkdir(parents=True, exist_ok=True)
    t = secrets.token_urlsafe(24)
    f.write_text(t)
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass
    return t


def ask_files():
    for f in glob.glob(str(config_dir() / "asks" / "*.json")):
        a = read_json(f, {}) or {}
        if isinstance(a, dict) and a.get("v") == 1:
            yield f, a


def unblocks_by_bead(repo):
    """bead id -> how many open beads wait on it (directly or through others), from bd list (cached by beads_of)."""
    try:
        beads = beads_of(repo)
    except Exception:
        return None
    if not beads:
        return None
    by_id = {b["id"]: b for b in beads}
    edges = {}
    for t, b in by_id.items():
        if b.get("status") == "closed":
            continue
        for s in graph.blockers(b):
            if s in by_id and s != t and by_id[s].get("status") != "closed":
                edges.setdefault(s, set()).add(t)
    epics = {i for i, b in by_id.items() if b.get("issue_type") == "epic"}
    return {"counts": graph.unblock_counts(edges, epics), "known": set(by_id), "open": {i for i, b in by_id.items() if b.get("status") != "closed"}}


def upgrade_ask(a):
    """An ask written before fmt 2 (kind from the old rules, raw question, no buttons) as the new build would have written it,
    for display only: the file is not touched. Over-budget asks get where the minutes went from the run's engine log."""
    if a.get("fmt") == 3:
        return a
    try:
        _engine_dir()
        import engine
        why = str(a.get("why") or a.get("question") or "")
        kind = engine.ask_kind(why) if a.get("why") and a.get("kind") in ("stuck", "verify") else a.get("kind")
        src = str(a.get("detail") or a.get("question") or why)
        if kind == "budget":
            why = re.sub(r" \(\d+ min wall.*\)$", "", engine.ZERO_COST.sub("", why))
            went = engine.run_breakdown(config_dir() / "engine" / ("%s.jsonl" % a.get("run", ""))) if a.get("run") else ""
            if went and "Where it went" not in why:
                why += ". Where it went: " + went
            src = why
        out = dict(a, kind=kind, detail=src, fmt=3,
                   question=engine.ask_markdown(kind, why, src))
        if not out.get("options") or kind != a.get("kind"):
            out["options"] = engine.ask_options(kind, why)
        elif any(not o.get("then") for o in out["options"]):
            if kind == "decision":
                out["options"] = [dict(o, then=o.get("then") or "The bead runs again with this as its instruction.") for o in out["options"]]
            else:
                out["options"] = engine.ask_options(kind, why) or out["options"]
        return out
    except Exception:
        return a


def inbox():
    """The open asks, most unblocking first. An ask whose bead is gone or closed is stale and never shown."""
    out, now, ub = [], time.time(), {}
    for f, a in ask_files():
        if a.get("status") != "open":
            continue
        repo = a.get("repo") if isinstance(a.get("repo"), str) else ""
        if repo not in ub:
            ub[repo] = unblocks_by_bead(repo) if repo and (Path(repo) / ".beads").exists() else None
        info = ub[repo]
        if info and a.get("bead") not in info["open"] and (a.get("bead") in info["known"] or now - float(a.get("t") or now) > 600):
            continue  # closed, or gone for good (a bead newer than a stale listing is not gone yet)
        a = {k: v for k, v in upgrade_ask(a).items() if k not in ("brief",)}
        a["age_s"] = int(now - float(a.get("t") or now))
        a["parked"] = now > float(a.get("parks_at") or now + 1)
        a["answered_here"] = bool(a.get("answer"))
        a["unblocks"] = (info["counts"].get(a.get("bead"), 0) if info else 0)
        a["quick"] = bool(a.get("options")) and a.get("kind") != "decision"
        out.append(a)
    out.sort(key=lambda a: (a["parked"], a["answered_here"], -a["unblocks"], not a["quick"], -a["age_s"]))
    return out


def asks():
    return {"asks": inbox(), "delegate": delegate_status()}


LOGGED_OUT = re.compile(r"logged[ _]out|not logged in", re.I)


def lane_banners(j):
    """name -> {until, reason, text} for each lane of `route.py status --json` that stops an unattended run. A credit lane
    that is out, a lane only busy (all slots taken), or unknown subscription use, does not: no banner. delegate 0.35.1+
    says why in `reason`; 0.35.0 has none, so a logout there is out with a note."""
    out = {}
    for n, ln in (j.get("lanes") or {}).items():
        if not isinstance(ln, dict) or ln.get("kind") == "credit" or ln.get("reason") == "busy":
            continue
        notes = " ".join(str(x) for x in ln.get("notes") or [])
        gone = ln.get("reason") == "logged_out" or (ln.get("out") and LOGGED_OUT.search(notes))
        if not (ln.get("out") or gone):
            continue
        who = timeline.lane_name(n, ln.get("family") or "") or str(n).lower()
        until = ln.get("out_until")
        if gone:
            text = "%s logged out: run %s" % (who, "codex login" if who == "Codex" else "claude auth login")
        else:
            past = until and until < time.time()  # delegate still says out after its own end: say so, never a bare old time
            text = "%s out%s" % (who, (" (its end, %s, has passed)" % timeline.when(until)) if past
                                 else (" until " + timeline.when(until)) if until else "")
        out[n] = {"until": until, "reason": "logged_out" if gone else ln.get("reason"), "text": text}
    return out


def delegate_status():
    """The banner: what delegate says about its lanes (route.py status --json v1); task-loop never reads vendors."""
    def load():
        routes = glob.glob(os.path.expanduser("~/.claude/plugins/cache/*/iorlas-delegate/*/skills/delegate/route.py"))
        if not routes:
            return {"ok": False, "say": "delegate is not installed"}
        key = lambda p: [int(x) if x.isdigit() else 0 for x in p.split("/iorlas-delegate/")[1].split("/")[0].split(".")]
        try:
            r = subprocess.run([sys.executable, max(routes, key=key), "status", "--json", "--recent", "5"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20)
            out = r.stdout.strip()
            j = json.loads(out[out.index("{"):])  # one object, pretty-printed or not
        except (OSError, ValueError, IndexError, subprocess.SubprocessError) as e:
            return {"ok": False, "say": "delegate status failed: %s" % e}
        det = lane_banners(j)
        out = sorted(det)
        return {"ok": not out, "out": out, "detail": det, "needs_input": j.get("needs_input") or []}
    return cached("delegate", 60, load)


def ask_for(ask_id):
    """(path, ask, problem): the file that holds ask_id, or why it cannot be answered. Ask files are per bead and the
    engine overwrites them with a newer ask (id bead-n), so an id the file no longer carries is `superseded`."""
    ask_id = ask_id if isinstance(ask_id, str) else ""
    for f, a in ask_files():
        if a.get("id") == ask_id:
            if a.get("status") == "withdrawn":
                why = (a.get("withdrawn_why") or "").strip()
                return f, a, (410, {"code": "withdrawn", "error": "The engine withdrew this ask%s. Nothing to answer." %
                                    ((" (" + why + ")") if why else "")})
            if a.get("status") != "open" or a.get("answer"):
                return f, a, (409, {"code": "answered", "error": "This ask is already answered."})
            return f, a, None
    bead = ask_id.rsplit("-", 1)[0]
    f = config_dir() / "asks" / ("%s.json" % bead)
    now = read_json(str(f), {}) if bead and "/" not in bead and "\\" not in bead and ".." not in bead else {}
    now = now if isinstance(now, dict) else {}
    if now.get("id") and now.get("status") == "open":
        return None, None, (409, {"code": "superseded", "new_ask": now["id"],
                                  "error": "The engine asked again for this bead; the new ask replaces this one."})
    return None, None, (404, {"code": "gone", "error": "This ask no longer exists."})


def bd_failed(a, r):
    out = ((r.stderr or "") + (r.stdout or "")).strip()
    if "no issue found" in out or "not found" in out.lower():
        return 404, {"code": "bead_missing", "error": "The bead %s no longer exists in %s. The ask is out of date: dismiss it."
                     % (a.get("bead"), os.path.basename(str(a.get("repo") or "").rstrip("/")) or "its repo")}
    return 502, {"code": "bd", "error": "bd refused the comment: %s" % (out.splitlines()[-1][:200] if out else "no output")}


def answer(body):
    """First answer wins: a comment on the bead (the engine reads it as the bead changing) and the bead opened."""
    if not isinstance(body, dict):
        return 400, {"code": "bad_body", "error": "The request was not understood."}
    f, a, problem = ask_for(body.get("ask"))
    if problem:
        return problem
    text = body.get("text")
    text = text.strip() if isinstance(text, str) else ""
    if not text:
        return 400, {"code": "empty", "error": "Write an answer first."}
    cwd = a.get("repo") or None
    try:
        r = subprocess.run(["bd", "comments", "add", a["bead"], text], cwd=cwd, capture_output=True, text=True)
        if r.returncode:
            return bd_failed(a, r)
        subprocess.run(["bd", "update", a["bead"], "--status", "open"], cwd=cwd, capture_output=True, text=True)
    except OSError as e:
        return 502, {"code": "no_bd", "error": "The dashboard cannot run bd (%s). Nothing was sent." % e.strerror}
    a.update(answer=text, answer_t=time.time())
    try:
        Path(f).write_text(json.dumps(a, indent=1))
    except OSError:
        pass  # the comment is the answer; the engine reads it from the bead
    return 200, {"ok": True, "bead": a["bead"], "next": next_step(a)}


def next_step(a):
    """One sentence on what happens after the answer, for the confirmation."""
    return "The bead %s runs again from your answer on the next pass of the loop for %s." % (
        a.get("bead"), os.path.basename(str(a.get("repo") or "").rstrip("/")) or "its repo")


def withdraw(body):
    """The owner dismisses an ask that no longer applies; the bead is not touched."""
    if not isinstance(body, dict):
        return 400, {"code": "bad_body", "error": "The request was not understood."}
    f, a, problem = ask_for(body.get("ask"))
    if problem:
        return (200, {"ok": True}) if problem[1].get("code") == "withdrawn" else problem
    why = body.get("why") if isinstance(body.get("why"), str) and body.get("why").strip() else "dismissed by the owner"
    a.update(status="withdrawn", withdrawn_why=why[:300], withdrawn=time.time())
    try:
        Path(f).write_text(json.dumps(a, indent=1))
    except OSError as e:
        return 500, {"code": "write", "error": "Could not write the ask file (%s)." % e.strerror}
    return 200, {"ok": True}


CGNAT = ipaddress.ip_network("100.64.0.0/10")  # Tailscale's range


def trusted_source(addr):
    """True for loopback and the Tailscale CGNAT range: the owner's own machines, which answer asks with no token.
    addr is the socket's peer (client_address), never a header: a proxy header is the client's to forge."""
    try:
        ip = ipaddress.ip_address(str(addr).split("%")[0])
    except ValueError:
        return False
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_loopback or ip in CGNAT


def post_allowed(addr, authorization):
    """A POST needs no token from a trusted source; any other source (a container bound to 0.0.0.0, the LAN) needs it."""
    import hmac
    if trusted_source(addr):
        return True
    got = (authorization or "").replace("Bearer ", "", 1).strip()
    return bool(got) and hmac.compare_digest(got, token())


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


def is_dev_checkout(here=None):
    """A git checkout or worktree (tests, dev) rather than the installed plugin cache."""
    here = Path(here or HERE).resolve()
    if "cache" in here.parts and "plugins" in here.parts:
        return False
    return any((d / ".git").exists() for d in [here, *here.parents])


def plan(port, bind, dev):
    """(addresses, port): installed copy = loopback + Tailscale on 7878; a dev checkout = loopback on a random port."""
    if bind:
        addrs = [x.strip() for x in bind.split(",") if x.strip()]
    elif dev and not os.environ.get("TASK_LOOP_DASH_BIND"):
        addrs = ["127.0.0.1"]
    else:
        addrs = bind_addrs()
    return addrs, (port if port is not None else (0 if dev else 7878))


class BindError(Exception):
    pass


def is_installed_copy(here=None, home=None):
    """True only when this file really lives (symlinks resolved) under ~/.claude/plugins/cache/."""
    cache = (Path(home or HOME) / ".claude" / "plugins" / "cache").resolve()
    try:
        Path(here or HERE).resolve().relative_to(cache)
    except ValueError:
        return False
    return True


def is_loopback(addr):
    if addr == "localhost":
        return True
    try:
        return ipaddress.ip_address(addr).is_loopback
    except ValueError:
        return False


def bind_refusal(addrs, port, here=None, home=None, state=None):
    """Why this server must not bind, else None (tl-bxk.12.5): a dev copy once took :7878 on the Tailscale address
    with an empty state dir and blanked the phone dashboard. Only TASK_LOOP_DASH_DEV_PUBLIC=1 overrides."""
    if not is_installed_copy(here, home) and os.environ.get("TASK_LOOP_DASH_DEV_PUBLIC") != "1":
        bad = [a for a in addrs if not is_loopback(a)]
        if bad or port == 7878:
            return ("refusing to bind %s: only the installed plugin copy (under ~/.claude/plugins/cache/) may serve "
                    "a non-loopback address or port 7878; set TASK_LOOP_DASH_DEV_PUBLIC=1 to override"
                    % (", ".join(bad) if bad else "port 7878"))
    if port == 7878 and not ((Path(state) if state else config_dir()) / "repos.json").is_file():
        return "refusing to start on port 7878: no repos.json in the state dir (run `tl register` first)"
    return None


def holder_pid(addr, port):
    try:
        r = subprocess.run(["lsof", "-nP", "-iTCP@%s:%d" % (addr, port), "-sTCP:LISTEN", "-t"],
                           capture_output=True, text=True, timeout=5)
        return (r.stdout.split() or [None])[0]
    except (OSError, subprocess.SubprocessError):
        return None


def open_servers(addrs, port, handler):
    """Bind every address or none: a partial set would silently serve a subset (tl-bxk.12.4)."""
    servers = []
    for addr in addrs:
        try:
            # port 0: every address after the first reuses the port the first was given
            servers.append(ThreadingHTTPServer((addr, servers[0].server_address[1] if servers else port), handler))
        except OSError as e:
            p = servers[0].server_address[1] if servers else port
            for s in servers:
                s.server_close()
            pid = holder_pid(addr, p)
            raise BindError("bind %s:%d failed: %s%s" % (addr, p, e, " (held by pid %s)" % pid if pid else ""))
    return servers


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
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            try:
                if u.path == "/api/version":
                    body = {"version": VERSION, "pid": os.getpid(), "urls": urls(addrs, port), "started": STARTED,
                            "script": str(Path(__file__).resolve()), "binds": list(addrs), "port": port}
                elif u.path == "/api/summary":
                    _last_seen[0] = time.time()
                    body = summary()
                elif u.path == "/api/task":
                    body = task_detail(q.get("repo", ""), q.get("id", ""))
                elif u.path == "/api/runs":
                    body = all_runs(float(q.get("hours", "24")))
                elif u.path == "/api/events":
                    body = run_events(q.get("id", ""))
                elif u.path == "/api/asks":
                    body = asks()
                elif u.path == "/api/tasks":
                    body = api_tasks()
                elif u.path == "/api/graph":
                    body = api_graph(q.get("repo", ""))
                elif u.path == "/api/bead":
                    body = api_bead(q.get("repo", ""), q.get("id", ""))
                elif u.path == "/api/looks":
                    body = api_looks(q.get("repo", ""))
                elif u.path == "/api/look-shot":
                    got = look_shot(q.get("repo", ""), q.get("path", ""))
                    if got is None:
                        return self.send(404, b"not found", "text/plain")
                    return self.send(200, got[0], got[1])
                elif u.path == "/api/roadmap":
                    body = api_roadmap(q.get("repo", ""))
                elif u.path == "/api/task-timeline":
                    body = api_task_timeline(q.get("repo", ""), q.get("id", ""))
                elif u.path == "/api/block":
                    body = api_block(q.get("run", ""), q.get("node", ""), q.get("k", "0"))
                elif u.path == "/api/file":
                    data = run_file(q.get("run", ""), q.get("path", ""))
                    if data is None:
                        return self.send(404, b"not found", "text/plain")
                    return self.send(200, data, "text/plain; charset=utf-8")
                elif u.path == "/classic":
                    return self.send(200, (HERE / "classic.html").read_bytes(), "text/html; charset=utf-8")
                elif u.path in ("/", "/index.html"):
                    return self.send(200, page.read_bytes(), "text/html; charset=utf-8")
                else:
                    return self.send(404, b"not found", "text/plain")
            except Exception as e:  # a broken transcript must not take the page down
                body = {"error": "%s: %s" % (type(e).__name__, e)}
                return self.send(500, json.dumps(body).encode(), "application/json")
            self.send(200, json.dumps(body, default=str).encode(), "application/json")
        def do_POST(self):
            u = urlparse(self.path)
            if not post_allowed(self.client_address[0], self.headers.get("Authorization")):
                return self.send(401, b'{"error": "token"}', "application/json")
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 65536)) or b"{}")
            except ValueError:
                return self.send(400, b'{"error": "json"}', "application/json")
            if u.path not in ("/api/answer", "/api/withdraw", "/api/look"):
                return self.send(404, b"not found", "text/plain")
            code, out = {"/api/answer": answer, "/api/withdraw": withdraw, "/api/look": answer_look}[u.path](body)
            self.send(code, json.dumps(out).encode(), "application/json")
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
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--bind", default=None, help="comma-separated addresses (default: loopback + Tailscale; dev checkout: loopback)")
    a = ap.parse_args()
    dev = is_dev_checkout()
    addrs, port = plan(a.port, a.bind, dev)
    why = bind_refusal(addrs, port)
    if why:
        print(why, file=sys.stderr, flush=True)
        sys.exit(2)
    token()
    try:
        servers = open_servers(addrs, port, None)  # handler set below: it needs the real port
    except BindError as e:
        print(e, file=sys.stderr, flush=True)
        sys.exit(2)
    port = servers[0].server_address[1]
    handler = make_handler(port, addrs)
    for s in servers:
        s.RequestHandlerClass = handler
    if not dev:  # a dev server must not claim the shared pid file
        config_dir().mkdir(parents=True, exist_ok=True)
        (config_dir() / "dash.pid").write_text(str(os.getpid()))
    for s in servers[1:]:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    threading.Thread(target=idle_watch, args=(float(os.environ.get("TASK_LOOP_DASH_IDLE_H", "6")),), daemon=True).start()
    print("task-loop dashboard %s on %s" % (VERSION, ", ".join(urls(addrs, port))), flush=True)
    servers[0].serve_forever()


if __name__ == "__main__":
    main()
