"""Engine logs -> the task timeline the dashboard draws: a run is a chain of blocks (one stage + one session), each
block entered by an arrow that says why the run moved there. Python 3.8+, standard library only.

The engine writes machine-readable records since 0.17 (docs/design/dashboard.md, Timeline records): `node` with id,
step and counters, `end`, `transition`, `checks`, `run`. A node record without an id and a step (an older log) is skipped.
"""

import json
import os
import re
import threading
import time
from collections import OrderedDict

_parsed = OrderedDict()  # path -> ((mtime, size), records), least recently read first
_plock = threading.Lock()
CACHE_MAX = 500

RUN_STEM = re.compile(r"^(?P<bead>.+)-(?P<stamp>\d{8}-\d{6})$")
META = ("stage", "stages", "write", "round", "fix", "fixes", "try", "items")
LINE_KINDS = ("cmd", "note", "warn", "verify")
FAMILY = {"openai": "Codex", "claude": "Claude", "xai": "Grok"}


def read(path):
    """The log's records, re-read only when the file changed."""
    try:
        st = os.stat(path)
    except OSError:
        with _plock:
            _parsed.pop(path, None)
        return []
    key = (st.st_mtime, st.st_size)
    with _plock:
        hit = _parsed.get(path)
        if hit and hit[0] == key:
            _parsed.move_to_end(path)
            return hit[1]
    recs = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for ln in f:
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if isinstance(d, dict):
                recs.append(d)
    with _plock:
        _parsed[path] = (key, recs)
        _parsed.move_to_end(path)
        while len(_parsed) > CACHE_MAX:
            _parsed.popitem(last=False)
    return recs


def run_name(path):
    return os.path.basename(path)[:-len(".jsonl")] if path.endswith(".jsonl") else os.path.basename(path)


def bead_of(run):
    m = RUN_STEM.match(run)
    return m.group("bead") if m else ""


def lane_name(lane="", family=""):
    """Codex, Claude or Grok, from delegate's family or lane name."""
    if family in FAMILY:
        return FAMILY[family]
    up = (lane or "").upper()
    return ("Grok" if "GROK" in up or up.endswith("XAI") or "_XAI" in up else
            "Codex" if "OPENAI" in up or "CODEX" in up else "Claude" if "CLAUDE" in up or "ANTHROPIC" in up else "")


def hhmm(t):
    return time.strftime("%H:%M", time.localtime(t)) if t else ""


def when(t):
    """HH:MM today, else the weekday too."""
    if not t:
        return ""
    same = time.strftime("%Y%m%d", time.localtime(t)) == time.strftime("%Y%m%d")
    return hhmm(t) if same else time.strftime("%a %H:%M", time.localtime(t))


def pause_reason(why):
    """What a pause waits for, in a few words: "Codex out", "Claude logged out", "no network"."""
    if "logged_out" in why:
        return "%s logged out" % ("Codex" if "codex login" in why else "Grok" if "opencode auth login" in why else "Claude")
    if why.startswith("paused: no network") or "(network" in why:
        return "no network"
    if "setup on" in why or "(setup" in why:
        return "delegate needs setup"
    lane = lane_of(why)
    return "%s out" % lane if lane else "no lane"


# ---- records -> nodes ------------------------------------------------------------------------------------------------

def nodes_of(recs):
    """(nodes, run record or None). A node: one engine step with its sessions, lines and moves."""
    out, by_id, cur, run, ends = [], {}, None, None, {}
    for i, r in enumerate(recs):
        k = r.get("kind")
        if k == "node":
            if "id" not in r or "step" not in r:
                continue
            nid, step = r["id"], r["step"]
            meta = {x: r[x] for x in META if r.get(x) is not None}
            if out and out[-1]["t1"] is None:
                out[-1]["t1"] = r.get("t")
            cur = {"id": nid, "step": step, "text": r.get("text") or "", "t0": r.get("t"), "t1": None, "meta": meta,
                   "sessions": [], "msgs": [], "lines": [], "moves": [], "checks": None, "outcome": "", "detail": "",
                   "rec": r, "open": True}
            out.append(cur)
            by_id[nid] = cur
            continue
        if k == "run":
            run = r
            continue
        if k == "end":
            ends[r.get("id")] = r
            continue
        if k == "transition":
            n = by_id.get(r.get("from")) or cur
            if n is not None:
                n["moves"].append(dict(r, _i=i))
            continue
        if cur is None:
            continue
        if k == "session":
            n = by_id.get(r.get("node_id")) or cur
            n["sessions"].append(dict(r, _i=i))
        elif k == "msg":
            (by_id.get(r.get("node_id")) or cur)["msgs"].append(r)
        elif k == "checks":
            (by_id.get(r.get("node_id")) or cur)["checks"] = r
        elif k in LINE_KINDS:
            cur["lines"].append(dict(r, _i=i))
    if out and out[-1]["t1"] is None:
        out[-1]["t1"] = recs[-1].get("t") if recs else None
    for n in out:
        e = ends.get(n["id"])
        if e:
            n["t1"], n["outcome"], n["detail"] = e.get("t") or n["t1"], e.get("outcome") or "", e.get("detail") or ""
            n["open"] = False
    return out, run


def check_pairs(lines):
    """[(cmd, exit, tail)] from a checks node's cmd records and the `exit N: tail` notes after them."""
    out, last = [], None
    for ln in lines:
        if ln.get("kind") == "cmd":
            last = [ln.get("text") or "", None, "", ln.get("t")]
            out.append(last)
        elif ln.get("kind") == "note" and last is not None and str(ln.get("text") or "").startswith("exit "):
            m = re.match(r"exit (-?\d+)(?::\s*(.*))?$", ln["text"], re.S)
            if m:
                last[1] = ln.get("exit") if ln.get("exit") is not None else int(m.group(1))
                last[2] = (m.group(2) or "").strip()
                last[3] = (ln.get("t") or 0) - (last[3] or ln.get("t") or 0)
            last = None
    return out


def ask_kind(why):
    if why.startswith(("paused:", "waiting:", "failed:")):
        return None
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
    return "stuck"


def close_move(outcome, why):
    if outcome in ("landed", "done"):
        return "close", outcome
    if why.startswith("paused:"):
        return "pause", "paused"
    if why.startswith("waiting:"):
        return "ask", "waiting"
    kind = ask_kind(why) if outcome == "blocked" else None
    if kind:
        return "ask", kind
    return "close", "stopped" if why.startswith("failed: stopped") else "failed"


def same_round(a, b):
    """b writes again for the stage (or fix) a judged: a send-back, not the next stage."""
    ka = (a["meta"].get("stage"), a["meta"].get("fix"))
    kb = (b["meta"].get("stage"), b["meta"].get("fix"))
    return ka == kb and (b["meta"].get("write") or 1) > 1


def infer_move(a, b):
    """The move from node a to node b when no transition record says it."""
    sa, sb = a["step"], b["step"]
    if sb == "close":
        to, cause = close_move(b["rec"].get("outcome") or "", b["rec"].get("why") or "")
        return {"to": to, "cause": cause, "detail": (b["rec"].get("why") or "").split("\n")[0]}
    if sa == "checks":
        if a["outcome"] == "red":
            return {"to": sb, "cause": "checks_red" if sb == "write" else "rounds_used", "detail": a["detail"]}
        return {"to": sb, "cause": "checks_green", "detail": a["detail"]} if sb == "review" else None
    if sa == "review":
        if sb == "write" and same_round(a, b):
            return {"to": "write", "cause": "review_sendback", "detail": a["detail"]}
        if sb in ("write", "verify", "land"):
            return {"to": sb, "cause": "accepted", "detail": ""}
        if sb in ("plan", "replan"):
            return {"to": sb, "cause": "rounds_used", "detail": a["detail"]}
    if sa in ("plan", "replan") and sb == "write":
        return {"to": "write", "cause": "planned", "detail": a["outcome"]}
    if sa == "land" and sb == "land":
        return {"to": "land", "cause": "push_race", "detail": ""}
    if sa == "land" and sb == "write":
        return {"to": "fix", "cause": "gate_red", "detail": ""}
    if sa == "verify":
        return {"to": sb, "cause": "verify_wrong" if sb == "write" else "verified", "detail": a["detail"]}
    return None


def lane_of(why):
    m = re.search(r"\b([A-Z]+)_[A-Z_]+\b", why or "")
    return lane_name(m.group(0)) if m else ""


def until_of(why):
    m = re.search(r"until (\d\d:\d\d)", why or "")
    return m.group(1) if m else ""


def arrow_text(cause, detail="", ctx=None):
    """What the arrow into a block (or the run's end) says."""
    ctx = ctx or {}
    detail = (detail or "").strip()
    first = detail.split(";")[0]
    m = re.match(r"(\d+) failed", first)
    if cause == "checks_red":
        return "checks red: %s \u2192 write again" % (("%s failed" % m.group(1)) if m else "failed")
    if cause == "checks_green":
        return "checks green"
    if cause == "review_sendback":
        n = re.match(r"(\d+ findings?, \d+ unmet)", detail)
        r = re.search(r"round (\d+)", detail)
        return "review sent back%s \u2192 round %s" % ((": " + n.group(1)) if n else "", r.group(1) if r else "again")
    if cause == "accepted":
        return "accepted"
    if cause == "planned":
        return detail or "planned"
    if cause == "bad_checks":
        return "writer: the checks are wrong \u2192 re-plan"
    if cause == "rounds_used":
        return "rounds used up \u2192 re-plan"
    if cause == "writer_decided":
        return "a requirement already decides it \u2192 write again"
    if cause == "lane_out":
        who = ctx.get("from_name") or "the lane"
        return "%s out \u2192 new thread%s" % (who, (" on " + ctx["to_model"]) if ctx.get("to_model") else "")
    if cause == "lane_wait":
        return "waited for a lane"
    if cause == "invalid_output":
        return "invalid output \u2192 try again"
    if cause == "plan_sent_back":
        return "checks sent back \u2192 plan again"
    if cause == "paused":
        what = ("%s out" % ctx["lane"]) if ctx.get("lane") else pause_reason(detail)
        until = ctx.get("until") or until_of(detail)
        return "%s \u2192 paused%s" % (what, (" until " + until) if until else "")
    if cause in ("decision", "verify", "ticket", "stuck", "waiting", "verify_open", "needs_human", "denied", "budget"):
        return {"decision": "decision needed", "verify": "needs your check", "ticket": "needs a split or criteria",
                "stuck": "stuck", "waiting": "waiting for your answer", "verify_open": "needs your check",
                "needs_human": "needs you", "denied": "needs you", "budget": "over its time limit"}[cause] + " \u2192 asks you"
    if cause == "verify_wrong":
        return "check before land found defects \u2192 fix round"
    if cause == "verified":
        return "verified \u2192 land"
    if cause == "gate_red":
        return "gate red \u2192 fix round"
    if cause == "conflict":
        return "merge conflict \u2192 fix round"
    if cause == "push_race":
        return "main moved \u2192 push again"
    if cause in ("landed", "done"):
        return cause
    if cause == "stopped":
        return "stopped"
    if cause == "failed":
        return "failed: " + detail[:120] if detail else "failed"
    return cause.replace("_", " ")


def label_of(n, k=0):
    step, m = n["step"], n["meta"]
    if step == "write":
        base = "Fix %d \u00b7 write %d" % (m["fix"], m.get("write") or 1) if m.get("fix") else "Write %d" % (m.get("write") or 1)
        return base
    if step == "land":
        return "Land" if (m.get("try") or 1) == 1 else "Land (try %d)" % m["try"]
    return {"plan": "Plan", "replan": "Re-plan", "checks": "Checks", "review": "Review", "verify": "Verify"}.get(
        step, step.capitalize())


RESULT = {  # (step, outcome) -> status colour
    "green": "ok", "clean": "ok", "landed": "ok", "done": "ok", "settled": "ok", "accepted": "ok",
    "red": "fail", "gate red": "fail", "conflict": "fail", "wrong": "fail", "failed": "fail", "stopped": "fail",
    "sent back": "warn", "reviewed": "warn", "rejected": "warn", "open": "ask", "asks": "ask",
    "paused": "wait", "lane_out": "wait", "waiting": "wait",
}


def who_of(n, s):
    if n["step"] in ("checks", "land", "reset", "close"):
        return {"family": "engine", "name": "Engine", "model": "", "effort": "", "lane": "", "resumed": False,
                "fallback": "", "flag": ""}
    s = s or {}
    fam = s.get("family") or ""
    name = lane_name(s.get("lane") or "", fam)
    fam = fam or {"Codex": "openai", "Claude": "claude"}.get(name, "")
    if not name and n["step"] == "write":
        name = ""  # not started yet: delegate had not picked a lane
    resumed = s.get("resume") if "resume" in s else bool(n["rec"].get("resume")) and s is (n["sessions"] or [None])[0]
    flag = s.get("flag") or ""
    return {"family": fam, "name": name or ("" if n["step"] == "write" else "?"), "model": s.get("model") or "", "effort": s.get("effort") or "",
            "lane": s.get("lane") or "", "resumed": bool(resumed), "flag": flag,
            "fallback": {"same_family": "same family as the writer", "degraded": "not the usual lane"}.get(flag, "")}


def session_result(s):
    st = (s or {}).get("status") or ""
    if not s or st == "done":
        return None
    if (s.get("reason") or st) == "lane_out":
        return {"status": "wait", "text": "%s out" % (lane_name(s.get("lane"), s.get("family")) or "lane")}
    return {"status": "fail", "text": s.get("reason") or st}


def stage_title(goal, cap=80):
    """A stage's title from its plan goal: the first sentence, before a leading `Name:`, cut at a word."""
    t = str(goal or "").strip().split("\n")[0].strip()
    t = re.split(r"(?<=[^.\s])\.(?:\s|$)", t)[0].strip()
    m = re.match(r"^([^:`]{3,40}):\s", t)
    if m:
        t = m.group(1).strip()
    if len(t) > cap:
        t = t[:cap].rsplit(" ", 1)[0].rstrip(",;:- ") + "\u2026"
    return t


_plans = {}  # plan.json path -> ((mtime, size), titles)


def plan_file_titles(path):
    """Stage titles from runs/<run>/plan.json next to the engine log, [] when there is none."""
    pj = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(path))), "runs", run_name(path), "plan.json")
    try:
        st = os.stat(pj)
    except OSError:
        _plans.pop(pj, None)
        return []
    key = (st.st_mtime, st.st_size)
    hit = _plans.get(pj)
    if hit and hit[0] == key:
        return hit[1]
    try:
        with open(pj, encoding="utf-8") as f:
            stages = (json.load(f) or {}).get("stages") or []
        titles = [stage_title(x.get("goal") if isinstance(x, dict) else x) for x in stages]
    except (OSError, ValueError, AttributeError):
        titles = []
    if len(_plans) > CACHE_MAX:
        _plans.clear()
    _plans[pj] = (key, titles)
    return titles


def plan_titles_in_log(n):
    """Stage titles from a plan node's answer in the log, None when it kept none."""
    for m in reversed(n["msgs"]):
        d = m.get("data")
        if isinstance(d, dict) and isinstance(d.get("stages"), list):
            return [stage_title(x.get("goal") if isinstance(x, dict) else x) for x in d["stages"]]
    return None


STAGED = ("write", "checks", "review")


def blocks_of(nodes, plan_titles=()):
    """Blocks in order, each with the arrow into it; and the move out of the last one. A write, checks or review
    block names its stage (index, count, title: the plan in force, else plan.json); a review or verify block by the
    family that wrote the last write is marked same_family."""
    blocks, pending = [], None
    titles, writer = list(plan_titles or []), ""
    work = [n for n in nodes if n["step"] not in ("reset", "close")]
    for idx, n in enumerate(nodes):
        if n["step"] in ("reset", "close"):
            continue
        if n["step"] in ("plan", "replan"):
            titles = plan_titles_in_log(n) or titles
        m = n["meta"]
        si = m.get("stage") if n["step"] in STAGED and m.get("stages") else None
        sn = m.get("stages") if si else None
        st = (titles[si - 1] if si and len(titles) >= si else "") if si else None
        sessions = n["sessions"] or [None]
        for k, s in enumerate(sessions):
            if k == 0:
                arrow = pending
            else:
                prev_i = sessions[k - 1].get("_i", -1) if sessions[k - 1] else -1
                inside = [m for m in n["moves"] if prev_i < m["_i"] < (s or {}).get("_i", 1 << 60)
                          and m.get("to") in (n["step"], "") and m.get("cause") not in ("paused",)]
                mv = inside[-1] if inside else {"cause": "retry", "detail": "another try"}
                prev = sessions[k - 1] or {}
                arrow = {"cause": mv["cause"], "detail": mv.get("detail") or "", "text": arrow_text(
                    mv["cause"], mv.get("detail"), {"from_name": lane_name(prev.get("lane"), prev.get("family")),
                                                    "to_model": nice_model((s or {}).get("model"))})}
            last = k == len(sessions) - 1
            res = session_result(s) if not last else None
            if res is None:
                out = n["outcome"]
                if last and s and s.get("status") not in (None, "done") and n["step"] != "checks":
                    res = session_result(s)
                else:
                    res = {"status": RESULT.get(out, "ok" if out else "info"), "text": n["detail"] if n["step"] in (
                        "review", "checks") and n["detail"] else out}
                    if n["step"] in ("plan", "replan"):
                        res["text"] = out
            t1 = (s or {}).get("t") if s and not last else n["t1"]
            t0 = n["t0"] if k == 0 else (sessions[k - 1] or {}).get("t") or n["t0"]
            secs = (s or {}).get("secs")
            who = who_of(n, s)
            if arrow and arrow.get("cause") == "lane_out" and k > 0:
                who["fallback"] = "new thread: %s was out" % (arrow["text"].split(" out")[0])
            fam = (s or {}).get("family") or who.get("family") or ""
            same = n["step"] in ("review", "verify") and bool(
                (s or {}).get("flag") == "same_family" or (fam and writer and fam == writer))
            if n["step"] == "write" and fam in FAMILY:
                writer = fam
            blocks.append({
                "node": n["id"], "k": k, "kind": n["step"], "label": label_of(n, k),
                "stage": ("%d/%d" % (n["meta"]["stage"], n["meta"]["stages"])) if n["meta"].get("stages") else None,
                "stage_index": si, "stage_count": sn, "stage_title": st, "same_family": same,
                "fix": n["meta"].get("fix"), "fixes": n["meta"].get("fixes"), "write": n["meta"].get("write"), "round": n["meta"].get("round"),
                "t0": t0, "t1": t1, "secs": secs if secs is not None else (round(t1 - t0) if t0 and t1 else None),
                "who": who, "tokens": (s or {}).get("tokens"), "result": res, "arrow": arrow,
                "session": {"ref": (s or {}).get("ref") or None, "family": (s or {}).get("family") or "",
                            "status": (s or {}).get("status") or "", "reason": (s or {}).get("reason") or "",
                            "transcript": (s or {}).get("transcript") or ""} if n["step"] not in ("checks", "land") else None,
            })
        pending = exit_move(n, nodes[idx + 1] if idx + 1 < len(nodes) else None)
    return blocks, pending, work


def exit_move(n, nxt):
    """The arrow out of node n: the last transition logged after its last session, else what the next node shows."""
    last_s = max([s.get("_i", -1) for s in n["sessions"]] or [-1])
    out = [m for m in n["moves"] if m["_i"] > last_s and not m.get("_inside")]
    mv = out[-1] if out else (infer_move(n, nxt) if nxt else None)
    if not mv:
        return None
    ctx = {"lane": lane_name(mv.get("lane") or "") or None,
           "until": hhmm(mv["until"]) if isinstance(mv.get("until"), (int, float)) and mv.get("until") else None}
    return {"cause": mv["cause"], "detail": mv.get("detail") or "", "to": mv.get("to") or "",
            "text": arrow_text(mv["cause"], mv.get("detail"), ctx)}


def nice_model(m):
    if not m:
        return ""
    m = str(m)
    for name in ("opus", "sonnet", "haiku", "fable"):
        if m.lower().startswith(name):
            rest = m[len(name):].strip("-_ ")
            return name.capitalize() + ((" " + rest.replace("-", ".")) if rest else "")
    return m


# ---- why a run started -----------------------------------------------------------------------------------------------

def because_text(run, prev=None):
    b = run.get("started_because")
    pe = (prev or {}).get("end") or {}
    if b == "first":
        return "first run"
    if b == "answer":
        return "you answered" + (" ask %s" % run["ask"].rsplit("-", 1)[-1] if run.get("ask") else "")
    if b == "fresh":
        return "fresh start"
    after = {"paused": "after pause" + ((": %s was out" % pe["lane"]) if pe.get("lane") else ""),
             "stopped": "after a stop", "failed": "after a failure", "asks": "after the bead changed"}.get(
        pe.get("outcome"), "")
    if b == "resume":
        return "resumed " + (after or "from the checkpoint")
    return "retry" + ((" " + after) if after else "")


# ---- a run, a block ----------------------------------------------------------------------------------------------------

def run_end(nodes, pending, alive):
    close = next((n for n in reversed(nodes) if n["step"] == "close"), None)
    if not close:
        t = nodes[-1]["t1"] if nodes else None
        if alive:
            return {"outcome": "running", "status": "run", "cause": "running", "text": "running", "t": t}
        return {"outcome": "stopped", "status": "fail", "cause": "stopped", "t": t,
                "text": "stopped: the run ended without a close record"}
    outcome, why = close["rec"].get("outcome") or "", close["rec"].get("why") or ""
    mv = pending or {}
    to, cause = close_move(outcome, why)
    cause = mv.get("cause") if mv.get("to") in ("ask", "pause", "close") else cause
    end = {"t": close["t0"], "why": why[:600], "cause": cause}
    if outcome in ("landed", "done"):
        end.update(outcome=outcome, status="ok", text="%s %s" % (outcome, when(close["t0"])))
    elif why.startswith("paused:"):
        lane, until = lane_of(why), until_of(why)
        end.update(outcome="paused", status="wait", lane=lane, until=until, reason=pause_reason(why),
                   text=arrow_text("paused", why))
    elif why.startswith("waiting:"):
        end.update(outcome="waiting", status="ask", text=arrow_text("waiting"))
    elif outcome == "blocked" and ask_kind(why):
        end.update(outcome="asks", status="ask", text=arrow_text(cause if cause in (
            "decision", "verify", "ticket", "stuck", "verify_open", "needs_human", "denied", "budget") else ask_kind(why)))
    elif why.startswith("failed: stopped"):
        end.update(outcome="stopped", status="fail", text="stopped")
    else:
        end.update(outcome="failed" if outcome == "failed" else "blocked", status="fail",
                   text=arrow_text("failed", why.split("\n")[0]))
    return end


def run_timeline(path, alive=False, trace=None, now=None):
    """One run of a bead: why it started, its blocks with the arrows between them, how it ended. A run that is alive has its
    open step and its end at `now` (the last record only says when something last happened, not how long it has been going)."""
    recs = read(path)
    nodes, run = nodes_of(recs)
    now = now or time.time()
    if alive and nodes and nodes[-1].get("open"):
        nodes[-1]["t1"] = now
    blocks, pending, _ = blocks_of(nodes, plan_file_titles(path))
    origin = {k: (run or {}).get(k) or "" for k in ("started_because", "prev_run", "ask")}
    t0 = recs[0].get("t") if recs else None
    t1 = now if alive and recs else recs[-1].get("t") if recs else None
    tokens = {"in": 0, "cached": 0, "out": 0}
    for b in blocks:
        for k in tokens:
            tokens[k] += int((b.get("tokens") or {}).get(k) or 0)
    end = run_end(nodes, pending, alive)
    if blocks and end["outcome"] in ("running", "stopped"):  # the step it was in when it stopped, or is in now
        b = blocks[-1]
        if not (b["session"] or {}).get("ref") or b["kind"] in ("checks", "land"):
            b["result"] = {"status": end["status"], "text": end["outcome"]}
    name = run_name(path)
    return dict(origin, run=name, bead=bead_of(name), started=t0, ended=t1,
                secs=round(t1 - t0) if t0 and t1 else None, blocks=blocks, end=end,
                tokens=tokens, slot=(run or {}).get("slot") or "", worktree=(run or {}).get("worktree") or "",
                waits=waits_of(recs, now if alive else (t1 or 0)), alive=bool(alive))


def waits_of(recs, until=0):
    """The engine's `wait` records: [{what, label, t0, secs, holder, in_budget}], oldest first (tl-9h2). A `wait_start`
    with no `wait` after it is a wait still going (or cut off when the process died): it lasts until `until`."""
    out, done = [], set()
    for r in recs:
        if r.get("kind") == "wait" and isinstance(r.get("t0"), (int, float)) and isinstance(r.get("secs"), (int, float)):
            done.add((str(r.get("what")), r["t0"]))
            out.append({"what": str(r.get("what") or "other"), "label": str(r.get("text") or ""), "t0": r["t0"], "secs": r["secs"],
                        "holder": str(r.get("holder") or ""), "in_budget": bool(r.get("in_budget"))})
    for r in recs:
        if r.get("kind") == "wait_start" and isinstance(r.get("t0"), (int, float)) and (str(r.get("what")), r["t0"]) not in done \
                and until > r["t0"]:
            out.append({"what": str(r.get("what") or "other"), "label": str(r.get("text") or ""), "t0": r["t0"], "secs": until - r["t0"],
                        "holder": str(r.get("holder") or ""), "in_budget": True, "open": True})
    return sorted(out, key=lambda w: w["t0"])


def last_node(path):
    nodes, _ = nodes_of(read(path))
    return nodes[-1] if nodes else None


def live_label(n):
    """What a running task is doing, from its last node."""
    if not n:
        return "starting"
    step, m = n["step"], n["meta"]
    stage = (" stage %d/%d" % (m["stage"], m["stages"])) if m.get("stages") and m["stages"] > 1 else ""
    fix = "fix round %d \u00b7 " % m["fix"] if m.get("fix") else ""
    if step == "write":
        return fix + "writing" + stage + ((" (write %d)" % m["write"]) if (m.get("write") or 1) > 1 else "")
    if step == "checks":
        return fix + "checks" + stage
    if step == "review":
        return fix + "review" + stage
    return {"reset": "starting", "plan": "planning", "replan": "re-planning", "verify": "checking before land",
            "land": "landing", "close": "closing"}.get(step, step)


def block_detail(path, node_id, k=0):
    """One block: its session, the checks of its round, the engine lines of its step, the step's answer."""
    recs = read(path)
    nodes, _ = nodes_of(recs)
    blocks, _, _ = blocks_of(nodes, plan_file_titles(path))
    try:
        node_id, k = int(node_id), int(k or 0)
    except (TypeError, ValueError):
        return {"error": "no such block"}
    blk = next((b for b in blocks if b["node"] == node_id and b["k"] == k), None)
    idx = next((i for i, n in enumerate(nodes) if n["id"] == node_id), None)
    if blk is None or idx is None:
        return {"error": "no such block"}
    n = nodes[idx]
    judge = n if n["step"] == "checks" else None
    if n["step"] == "write":  # a write shows the checks that judged it
        for m in nodes[idx + 1:]:
            if m["step"] == "checks":
                judge = m
                break
            if m["step"] in ("write", "plan", "replan", "close"):
                break
    checks = checks_of(judge) if judge else []
    last_checks = max([m["id"] for m in nodes if m["step"] == "checks"] or [0])
    lines = [{"t": ln.get("t"), "kind": ln.get("kind"), "text": str(ln.get("text") or "")[:2000], "exit": ln.get("exit")}
             for ln in n["lines"]][:400]
    answer = next((m.get("data") for m in reversed(n["msgs"]) if m.get("data") is not None), None)
    sess = next((s for i, s in enumerate(n["sessions"]) if i == k), None) or {}
    return {"block": blk, "session": {key: sess.get(key) for key in (
        "ref", "family", "model", "effort", "lane", "status", "reason", "transcript", "tokens", "secs", "resume",
        "flag", "attempt")} if sess else None, "checks": checks, "checks_node": judge["id"] if judge else None,
        "checks_last": bool(judge and judge["id"] == last_checks), "lines": lines, "answer": answer,
        "node_text": n["text"]}


def checks_of(n):
    pairs = check_pairs(n["lines"])
    rec = n.get("checks")
    if not rec:
        return [{"id": cmd, "cmd": cmd, "exit": ex, "status": "ran" if ex == 0 else "failed" if ex else "?",
                 "secs": round(secs) if isinstance(secs, (int, float)) else None, "tries": 1, "tail": tail, "log": ""}
                for cmd, ex, tail, secs in pairs]
    out, used = [], set()
    for it in rec.get("items") or []:
        tail = ""
        for j, p in enumerate(pairs):
            if j not in used and it.get("exit") is not None and p[1] == it.get("exit") and (
                    p[0] == it.get("cmd") or p[0].endswith(str(it.get("cmd"))[-40:])):
                used.add(j)
                tail = p[2]
                break
        out.append(dict(it, tail=tail))
    return out


# ---- one bead's whole time: every step, check and wait as a bar (tl-9h2) ----------------------------------------------

WAIT_NAMES = {"land_lock": "land lock", "review_lock": "review lock", "lane": "lane", "unity_slot": "Unity slot",
              "editor_lock": "editor lock", "delegate_crash": "delegate crash", "network": "network", "owner_ask": "owner ask",
              "paused": "paused", "between_runs": "between runs", "between_steps": "between steps", "other": "other wait"}
LOCKS = ("land_lock", "review_lock")  # waited for after the step before them ended: a bar of their own, never cut out of a step
MIN_GAP = 10  # seconds of unexplained time worth a bar of its own


def _seg(kind, what, label, t0, t1, run, **kw):
    return dict({"kind": kind, "what": what, "label": label, "t0": t0, "t1": t1, "secs": max(0, round(t1 - t0)), "run": run}, **kw)


def run_segments(r, end):
    """The segments of one run: its steps (work, or checks), the waits the engine recorded (cut out of the step they
    happened in, or a bar of their own between steps), and the unexplained gaps between them."""
    name, out = r["run"], []
    waits = [w for w in r.get("waits") or [] if w["secs"] > 0]
    used = set()
    for b in r["blocks"]:
        if not (b.get("t0") and b.get("t1")) or b["t1"] < b["t0"]:
            continue
        kind = "checks" if b["kind"] == "checks" else "work"
        label = b.get("label") or b["kind"]
        cuts = []
        for i, w in enumerate(waits):
            if i not in used and w["what"] not in LOCKS and b["t0"] - 1 <= w["t0"] < b["t1"]:  # a wait that starts in a step belongs to it
                cuts.append((max(b["t0"], w["t0"]), min(b["t1"], w["t0"] + w["secs"]), w))
                used.add(i)
        at = b["t0"]
        for c0, c1, w in sorted(cuts, key=lambda c: c[0]):
            c0 = max(c0, at)
            if c1 <= c0:
                continue
            if c0 > at:
                out.append(_seg(kind, b["kind"], label, at, c0, name, node=b["node"]))
            out.append(_seg("wait", w["what"], WAIT_NAMES.get(w["what"], w["what"]), c0, c1, name, node=b["node"], holder=w["holder"]))
            at = max(at, c1)
        if b["t1"] > at:
            out.append(_seg(kind, b["kind"], label, at, b["t1"], name, node=b["node"]))
    for i, w in enumerate(waits):
        t0 = max(w["t0"], r.get("started") or 0)  # never before the run: the time before it is the gap between runs
        if i not in used and w["t0"] + w["secs"] > t0:
            out.append(_seg("wait", w["what"], WAIT_NAMES.get(w["what"], w["what"]), t0, w["t0"] + w["secs"], name, holder=w["holder"]))
    out.sort(key=lambda x: (x["t0"], x["t1"]))
    filled, at = [], r.get("started")
    for s in out:
        if at and s["t0"] - at >= MIN_GAP:
            filled.append(_seg("idle", "between_steps", WAIT_NAMES["between_steps"], at, s["t0"], name))
        filled.append(s)
        at = max(at or 0, s["t1"])
    if at and end and end - at >= MIN_GAP:
        filled.append(_seg("idle", "between_steps", WAIT_NAMES["between_steps"], at, end, name))
    return filled


def bead_segments(runs, now=None):
    """runs: run_timeline() results of one bead, oldest first, the last one `alive` when the bead is running. -> {t0, t1,
    segments, totals: {work, checks, wait, idle (seconds), by_what: {what: seconds}}}. Time between two runs is an owner ask
    (the earlier one ended asking), a pause (it ended paused) or idle (anything else)."""
    now = now or time.time()
    segs, prev = [], None
    for r in runs:
        start = r.get("started")
        if not start:
            continue
        end = now if r.get("alive") else r.get("ended") or start
        if prev and prev["end"] and start - prev["end"] >= MIN_GAP:
            out = ((prev["r"].get("end") or {}).get("outcome") or "")
            what = "owner_ask" if out in ("asks", "waiting") else "paused" if out == "paused" else "between_runs"
            segs.append(_seg("idle" if what == "between_runs" else "wait", what, WAIT_NAMES[what], prev["end"], start, r["run"]))
        segs += run_segments(r, end)
        prev = {"r": r, "end": end}
    totals = {"work": 0, "checks": 0, "wait": 0, "idle": 0, "by_what": {}}
    for s in segs:
        totals[s["kind"]] += s["secs"]
        if s["kind"] in ("wait", "idle", "checks"):
            totals["by_what"][s["what"]] = totals["by_what"].get(s["what"], 0) + s["secs"]
    return {"t0": segs[0]["t0"] if segs else None, "t1": segs[-1]["t1"] if segs else None, "segments": segs, "totals": totals,
            "now": now}
