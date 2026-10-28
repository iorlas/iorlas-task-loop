"""The Live view's feed: the engine log plus the worker events delegate appends (DELEGATE_LIVE_FILE), merged by time.

One call returns only what is new since the cursor, which holds a byte offset per file, so a 1 s poll reads a few lines.
Python 3.8+, standard library only."""

import base64
import json
import os
import re
import time

CHUNK = 1 << 20  # bytes read from one file per call; a long backlog arrives over several polls
SKIP = {"_o", "kind", "t", "text", "items", "data", "sessions"}  # engine fields never forwarded (the rest, if scalar, are)
NOTE_MAX = 300


def encode(cur):
    return base64.urlsafe_b64encode(json.dumps(cur, separators=(",", ":")).encode()).decode()


def decode(s):
    try:
        cur = json.loads(base64.urlsafe_b64decode(s.encode() + b"=" * (-len(s) % 4)))
        return cur if isinstance(cur, dict) else {}
    except (ValueError, TypeError, AttributeError):
        return {}


def read_new(path, offset):
    """-> (complete JSON lines after offset as dicts, the new offset). A half-written last line waits for the next call."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return [], offset
    if size < offset:  # the file was replaced
        offset = 0
    if size == offset:
        return [], offset
    with open(path, "rb") as f:
        f.seek(offset)
        data = f.read(CHUNK)
    end = data.rfind(b"\n")
    if end < 0:
        return [], offset
    out, pos = [], offset
    for raw in data[:end + 1].split(b"\n")[:-1]:
        here = pos
        pos += len(raw) + 1
        try:
            d = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            continue
        if isinstance(d, dict):
            d["_o"] = here
            out.append(d)
    return out, offset + end + 1


def engine_event(d, state):
    """One engine record (EngineLog v2) -> a normalised event or None. `state` holds the open calls' step names between calls."""
    k, t = d.get("kind"), d.get("t")
    if t is None or not k:
        return None
    text = str(d.get("text") or "")
    if k == "cmd_start":
        return {"t": t, "k": "cmd", "id": d["id"], "text": text, "src": "engine"}
    if k == "cmd_end":
        return {"t": t, "k": "cmd_end", "id": d["id"], "exit": d.get("exit"), "src": "engine"}
    if k == "note":
        return {"t": t, "k": "note", "text": text[:NOTE_MAX], "src": "engine"}
    if k == "step_start":
        return {"t": t, "k": "step", "step": d.get("step") or "", "text": text, "src": "engine"}
    if k == "step_end":
        return {"t": t, "k": "step_end", "step": d.get("step") or "", "outcome": d.get("outcome"), "secs": d.get("secs"), "src": "engine"}
    if k == "call_start":
        state.setdefault("calls", {})[d["id"]] = d.get("step") or ""
    if k == "call_end":
        return {"t": t, "k": "session", "node": state.get("calls", {}).pop(d["id"], ""), "lane": d.get("lane"), "model": d.get("model"),
                "effort": d.get("effort"), "status": d.get("status"), "secs": d.get("secs"), "src": "engine"}
    # every other kind (call_start, check_start, gate_start, wait_start, wait_end, vendor_error, kill, transition, checks...) passes through:
    # those rows are the evidence of throttling and stalls. Scalar fields ride along; the client shows one dim line.
    e = {x: v for x, v in d.items() if x not in SKIP and isinstance(v, (str, int, float)) and not isinstance(v, bool)}
    e = {x: (v[:200] if isinstance(v, str) else v) for x, v in e.items()}
    e.update({"t": t, "k": k, "text": text[:NOTE_MAX * 4], "src": "engine"})
    return e


def live_event(d, tag):
    t = d.get("t")
    if t is None or not d.get("k"):
        return None
    e = {k: v for k, v in d.items() if not k.startswith("_")}
    e["src"] = tag
    if "id" in e:
        e["id"] = "%s:%s" % (tag, e["id"])
    return e


def live_files(path):
    d = path[:-len(".jsonl")] + ".live"
    try:
        return sorted(os.path.join(d, n) for n in os.listdir(d) if n.endswith(".jsonl"))
    except OSError:
        return []


def feed(path, cursor="", alive=False, now=None):
    """The events of the run at `path` after `cursor`, sorted by time, and the cursor for the next call."""
    now = now or time.time()
    cur = decode(cursor)
    offs, state = dict(cur.get("o") or {}), dict(cur.get("s") or {})
    events, step, meta, started, worktree = [], None, {}, None, ""
    rows, offs["engine"] = read_new(path, int(offs.get("engine") or 0))
    for d in rows:
        e = engine_event(d, state)
        if e:
            events.append(e)
        if d.get("kind") == "run_start" and d.get("t"):
            started, worktree = d["t"], d.get("worktree") or ""
    files = live_files(path)
    for p in files:
        tag = os.path.basename(p)[:-len(".jsonl")]
        rows, offs[tag] = read_new(p, int(offs.get(tag) or 0))
        for d in rows:
            e = live_event(d, tag)
            if e:
                events.append(e)
    events.sort(key=lambda e: e["t"])  # stable: a file's own order holds among equal times
    for e in events:
        if e["k"] == "step":
            step = e["step"]
        elif e["k"] == "start":
            meta = {"lane": e.get("lane"), "model": e.get("model"), "effort": e.get("effort"), "harness": e.get("harness")}
        elif e["k"] == "session" and e.get("lane"):
            meta = meta or {"lane": e.get("lane"), "model": e.get("model"), "effort": e.get("effort")}
    return {"events": events, "cursor": encode({"o": offs, "s": state}), "step": step, "meta": meta,
            "started": started, "worktree": worktree, "worker_detail": bool(files)}
