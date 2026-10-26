"""tl report and tl lost: the M2 scorecard over a time window, and the bead-branch commits no run will bring home.

Reads only: traces.jsonl, the loop's log, engine/*.jsonl and *.stderr, the repo's git refs (never fetched), and bd
(show, comments). Writes nothing.

  tl.py report [--repo DIR] [--since T] [--until T] [--json]   beads run, landed, landed with no ask, parked, paused,
                                                                failed, crashes, lost work, minutes, rounds, tokens, M2,
                                                                a planner line
  tl.py report lifecycle [--repo DIR] [--since T] [--until T] [--json]   (default: the last 28 days)
                                                                weekly lifecycle metrics: landed beads/day, slot-min,
                                                                asks, run-1 landings, dead time, fingerprints, gate,
                                                                hung steps, tokens, reverts, quota observations
  tl.py report --planner [--prefix P] [--since T] [--until T]   planner calls and input tokens per bead (delegate's
                                                                history.jsonl + the engine logs); no repo or bd needed
  tl.py lost [--repo DIR] [--since T] [--json]                  every task/* and wip/* commit not on the base, classed

T: ISO (2026-10-21T06:00, 2026-10-21, ...Z), HH:MM (today, local) or a duration back from now (90m, 12h, 2d).
A run is in the window when it overlaps it (started before --until, ended after --since).
"""

import json
import os
import re
import statistics
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import engine
import lifecycle
import loop
import tl
from lanes import route as lroute

M2 = {"beads": 10, "landed_no_ask": 7}  # at least; lost and crashes must be 0 (docs/roadmap.md)
QUIET_MIN = 30  # an engine log with no close and no trace, untouched this long and with no live run-task: a crash
# how the supervising session marks its own answers ("relayed by Claude" carries the owner's words: the owner's)
SUPERVISOR = re.compile(r"\(Claude, supervising|checked by Claude|delegated the call to Claude")
ANSWERED = re.compile(r"\bask (\S+) \(\w+\) is answered|\banswered verify ask (\S+)")
STEM = re.compile(r"^(.+)-(\d{8}-\d{6})$")


# ---- the window -------------------------------------------------------------------------------------------------------

def parse_time(text, now=None, forward=False):
    """Epoch seconds for T: a duration back from now (90m, 12h, 2d), ISO (naive = local time), or HH:MM: its last
    past occurrence (a morning --since 22:00 is last night), with forward its next one (--until)."""
    now = time.time() if now is None else now
    s = (text or "").strip()
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([mhd])$", s)
    if m:
        return now - float(m.group(1)) * {"m": 60, "h": 3600, "d": 86400}[m.group(2)]
    m = re.match(r"^(\d{1,2}):(\d{2})$", s)
    if m:
        t = datetime.fromtimestamp(now).replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0)
        if forward and t.timestamp() < now:
            t += timedelta(days=1)
        elif not forward and t.timestamp() > now:
            t -= timedelta(days=1)
        return t.timestamp()
    try:
        d = datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
    except ValueError:
        raise ValueError("not a time: %r (use ISO, HH:MM or a duration like 12h)" % text)
    return d.timestamp()


def stamp(t):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


# ---- inputs -----------------------------------------------------------------------------------------------------------

def git(repo, *args):
    r = tl.run_git(repo, *args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout.strip() if r.returncode == 0 else ""


def default_base(repo):
    return engine.load_cfg(repo)["base"]


def bases_of(repo, base):
    """The base and its local or remote twin, those that exist: a stale local main must not hide a land on origin."""
    names = [base]
    if base.startswith("origin/"):
        names.append(base[len("origin/"):])
    else:
        names.append("origin/" + base)
    return [n for n in names if git(repo, "rev-parse", "--verify", "-q", n + "^{commit}")]


def read_jsonl(path):
    out = []
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def repo_traces(repo):
    """Every engine run of this repo: its worktree is inside the repo, or its origin is the repo's origin."""
    root = str(Path(repo).resolve())
    url = git(repo, "remote", "get-url", "origin")
    out = []
    for r in read_jsonl(tl.config_dir() / "traces.jsonl"):
        wt = r.get("worktree") or ""
        inside = bool(wt) and (str(Path(wt).resolve()) + os.sep).startswith(root + os.sep)
        if inside or (url and r.get("repo") == url):
            out.append(r)
    return out


def run_alive(bead):
    """A run-task of this bead is a live process (POSIX ps); None when that cannot be told."""
    out = tl.ps("-A", "-o", "command=")
    if out is None:
        return None
    return any("run-task" in ln and bead in ln.split() for ln in out.splitlines())


def prefix(bead):
    return (bead or "").split("-")[0]


# ---- 10.2: lost work --------------------------------------------------------------------------------------------------

def bead_status(bead, repo):
    """The bead's status, None when the tracker has no such bead, "?" when bd itself failed (no false lost work)."""
    r = tl.bd("show", bead, "--json", cwd=repo)
    try:
        d = json.loads(r.stdout)
    except ValueError:
        return None if r.returncode == 0 or "not found" in (r.stderr or "").lower() else "?"
    d = d[0] if isinstance(d, list) and d else d
    return d.get("status") if isinstance(d, dict) else None


def lost_work(repo, since=None, base=None, status_of=None, traces=None):
    """Every commit on a task/<bead> or wip/* branch that is not on the base, classed:
    landed     its patch is on the base (git cherry), or a land of its bead came after it: a base commit titled
               '... (<bead>)' or the land sha a trace recorded, on the base (squash lands are no ancestors);
    reclaimed  a later run of the bead started after it (the engine continues the branch);
    pending    its bead is still open, blocked or in progress: the next run continues the branch;
    unknown    bd failed, so the bead's state cannot be told (listed, never counted as lost);
    lost       its bead is closed (or unknown) with no land after it, or it is on a wip/* branch of a dead session."""
    base = base or default_base(repo)
    bases = bases_of(repo, base) or [base]
    status_of = status_of or (lambda b: bead_status(b, repo))
    traces = repo_traces(repo) if traces is None else traces
    lands = {}  # bead -> times its land reached the base
    for ln in git(repo, "log", "--format=%ct %s", *bases).splitlines():
        t, _, subj = ln.partition(" ")
        m = re.search(r"\(([^()\s]+)\)\s*$", subj)
        if m and t.isdigit():
            lands.setdefault(m.group(1), []).append(int(t))
    for r in traces:
        if r.get("outcome") == "landed" and r.get("sha") and any(
                tl.run_git(repo, "merge-base", "--is-ancestor", r["sha"], b,
                           capture_output=True).returncode == 0 for b in bases):
            lands.setdefault(r.get("bead"), []).append(r.get("ended") or 0)
    rows, statuses = [], {}
    refs = git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/task/", "refs/heads/wip/").splitlines()
    for ref in refs:
        bead = ref[len("task/"):] if ref.startswith("task/") else None
        log = git(repo, "log", "--format=%H %ct %s", ref, "--not", *bases)
        if not log:
            continue
        upstream = {ln[2:] for ln in git(repo, "cherry", bases[0], ref).splitlines() if ln.startswith("- ")}
        for ln in log.splitlines():
            sha, ct, subj = (ln.split(" ", 2) + ["", ""])[:3]
            ct = int(ct)
            if since is not None and ct < since:
                continue
            row = {"branch": ref, "bead": bead, "sha": sha, "time": ct, "subject": subj}
            if sha in upstream:
                row.update({"class": "landed", "why": "its patch is on %s" % bases[0]})
            elif bead and any(t >= ct for t in lands.get(bead, [])):
                row.update({"class": "landed", "why": "%s landed on %s after it" % (bead, bases[0])})
            elif not bead:
                row.update({"class": "lost", "why": "a dead session's work on %s: no bead, no run takes it" % ref})
            else:
                if bead not in statuses:
                    statuses[bead] = status_of(bead)
                st = statuses[bead]
                later = [r for r in traces if r.get("bead") == bead and (r.get("started") or 0) >= ct]
                if st == "?":
                    row.update({"class": "unknown", "why": "bd could not show %s: the tracker is unreachable" % bead})
                elif st == "closed":
                    row.update({"class": "lost", "why": "%s is closed and never landed this commit" % bead})
                elif not st:
                    row.update({"class": "lost", "why": "no bead %s in the tracker" % bead})
                elif later:
                    row.update({"class": "reclaimed", "why": "run %s took it up" % later[0].get("run")})
                else:
                    row.update({"class": "pending", "why": "%s is %s: its next run continues the branch" % (bead, st)})
            rows.append(row)
    return rows


# ---- 10.1: the scorecard ----------------------------------------------------------------------------------------------

def crashes(repo, since, until, traces, alive=None, now=None):
    """Engine crashes: the loop saw run-task exit with no outcome; an engine log in the window with no close record and
    no trace, quiet for QUIET_MIN and with no live run-task; or a trace closed as 'failed: engine error' (an exception
    the engine caught). A run's .stderr is route.py's, where a worker's test tracebacks land too: never read."""
    alive = alive or run_alive
    now = time.time() if now is None else now
    out = {}
    for r in read_jsonl(loop.paths(repo)["log"]):
        try:
            t = time.mktime(time.strptime(r.get("ts") or "", "%Y-%m-%dT%H:%M:%S"))
        except ValueError:
            continue
        if since <= t < until and r.get("outcome") == "failed" and not r.get("trace") and \
                (r.get("why") or "").startswith("failed: no outcome from run-task"):
            key = "loop:%s:%s" % (r.get("bead"), r.get("ts"))
            out[key] = {"bead": r.get("bead"), "t": t, "run": None, "why": (r.get("why") or "")[:200]}
    traced = {r.get("run") for r in traces} | {Path(r["log"]).stem for r in traces if r.get("log")}
    prefixes = {prefix(r.get("bead")) for r in traces} | {prefix(r.get("bead")) for r in
                                                         read_jsonl(loop.paths(repo)["log"])}
    for f in sorted((tl.config_dir() / "engine").glob("*.jsonl")):
        m = STEM.match(f.stem)
        if not m or f.stem in traced or prefix(m.group(1)) not in prefixes:
            continue
        t = time.mktime(time.strptime(m.group(2), "%Y%m%d-%H%M%S"))
        if not since <= t < until:
            continue
        recs = read_jsonl(f)
        if any(x.get("kind") == "node" and (x.get("text") or "").startswith("close:") for x in recs):
            continue
        try:
            quiet = (now - f.stat().st_mtime) / 60
        except OSError:
            continue
        live = alive(m.group(1))
        if live or (live is None and quiet < QUIET_MIN):
            continue
        last = (recs[-1].get("text") or "") if recs else ""
        out[f.stem] = {"bead": m.group(1), "t": t, "run": f.stem,
                       "why": "the engine log ends with no close: %s" % last[:120]}
    for r in traces:  # the engine caught it and closed (engine.py: Engine.run): an engine bug all the same
        if overlaps(r, since, until) and (r.get("why") or "").startswith("failed: engine error"):
            out[r.get("run")] = {"bead": r.get("bead"), "t": r.get("started") or 0, "run": r.get("run"),
                                 "why": (r.get("why") or "")[:200]}
    return sorted(out.values(), key=lambda c: c["t"])


def overlaps(r, since, until):
    return (r.get("started") or 0) < until and (r.get("ended") or r.get("started") or 0) >= since


def answered_asks(run):
    """Asks a run went on from (its log's 'ask X is answered' notes): the ask came before, maybe before the window."""
    ids = set()
    for x in read_jsonl(run.get("log") or ""):
        m = ANSWERED.search(x.get("text") or "") if x.get("kind") == "note" else None
        if m:
            ids.add(m.group(1) or m.group(2))
    return ids


def who_answered(comments, n):
    """For the bead's last n asks: 'supervisor', 'owner' or 'open', from the first person's comment after each."""
    out = []
    asks = [i for i, c in enumerate(comments) if (c.get("text") or "").startswith("Ask (engine) ")]
    for i in asks[-n:] if n else []:
        reply = next((c for c in comments[i + 1:] if not (c.get("text") or "").startswith(engine.ENGINE_NOTES)), None)
        out.append("open" if reply is None else "supervisor" if SUPERVISOR.search(reply.get("text") or "") else "owner")
    return out + ["unknown"] * (n - len(out))


def pctl(xs, p):
    xs = sorted(xs)
    if not xs:
        return 0
    k = max(0, -(-len(xs) * p // 100) - 1)
    return xs[int(k)]


def scorecard(repo, since, until, base=None, comments_of=None, status_of=None, alive=None, now=None):
    repo = tl.repo_root(repo)  # the loop keys its log by this path
    comments_of = comments_of or (lambda b: tl.comments(b, cwd=repo))
    traces = repo_traces(repo)
    runs = sorted([r for r in traces if overlaps(r, since, until)], key=lambda r: r.get("started") or 0)
    crash = crashes(repo, since, until, traces, alive=alive, now=now)
    beads = {}
    for r in runs:
        beads.setdefault(r["bead"], {"runs": [], "crashes": []})["runs"].append(r)
    for c in crash:
        beads.setdefault(c["bead"], {"runs": [], "crashes": []})["crashes"].append(c)
    rows, asks = [], {"count": 0, "beads": 0, "supervisor": 0, "owner": 0, "open": 0, "unknown": 0}
    for bead, b in beads.items():
        rs = b["runs"]
        n_ask = sum(1 for r in rs if r.get("outcome") == "blocked" and engine.ask_kind(r.get("why") or ""))
        if not n_ask and any(answered_asks(r) for r in rs):
            n_ask = 1  # it went on from an ask raised before the window
        landed = any(r.get("outcome") in ("landed", "done") for r in rs)
        events = [(r.get("ended") or 0, r) for r in rs] + [(c["t"], {"outcome": "failed", "why": c["why"]})
                                                            for c in b["crashes"]]
        last = max(events, key=lambda e: e[0])[1]
        why = last.get("why") or ""
        if landed:
            state = "landed"
        elif last.get("outcome") == "blocked" and engine.ask_kind(why):
            state = "parked"
        elif last.get("outcome") == "blocked" and why.startswith(("paused:", "waiting:")):
            state = "paused"
        else:
            state = "failed"
        answers = who_answered(comments_of(bead), n_ask) if n_ask else []
        if n_ask:
            asks["count"] += n_ask
            asks["beads"] += 1
            for a in answers:
                asks[a] += 1
        rows.append({"bead": bead, "state": state, "asks": n_ask, "answers": answers, "runs": len(rs),
                     "crashes": len(b["crashes"]),
                     "minutes": round(sum(((r.get("ended") or 0) - (r.get("started") or 0)) / 60 for r in rs), 1),
                     "rounds": sum((r.get("stats") or {}).get("rounds") or 0 for r in rs),
                     "replans": sum((r.get("stats") or {}).get("replans") or 0 for r in rs),
                     "why": why[:160] if state != "landed" else ""})
    rows.sort(key=lambda x: x["bead"])
    tokens = {"lane": {}, "role": {}}
    for r in runs:
        for s in r.get("sessions") or []:
            tk = s.get("tokens") or {}
            if not any(tk.values()):
                continue
            fam = s.get("family") or (s.get("lane") or "?").split("_")[0].lower()
            for key, name in (("lane", "codex" if fam == "openai" else fam), ("role", s.get("role") or "?")):
                d = tokens[key].setdefault(name, {"in": 0, "cached": 0, "out": 0})
                d["in"] += input_tokens(tk)
                d["cached"] += int(tk.get("cached") or 0)
                d["out"] += int(tk.get("out") or 0)
    lost = [x for x in lost_work(repo, since=since, base=base, status_of=status_of, traces=traces)
            if x["class"] in ("lost", "pending", "unknown")]
    mins = [x["minutes"] for x in rows if x["runs"]]
    c = {"repo": repo, "since": since, "until": until, "beads": len(rows),
         "landed": sum(x["state"] == "landed" for x in rows),
         "landed_no_ask": sum(x["state"] == "landed" and not x["asks"] for x in rows),
         "parked": sum(x["state"] == "parked" for x in rows), "paused": sum(x["state"] == "paused" for x in rows),
         "failed": sum(x["state"] == "failed" for x in rows), "asks": asks,
         "crashes": len(crash), "crash_list": crash,
         "lost": sum(x["class"] == "lost" for x in lost), "lost_list": [x for x in lost if x["class"] == "lost"],
         "pending_list": [x for x in lost if x["class"] in ("pending", "unknown")],
         "minutes": {"median": round(statistics.median(mins), 1) if mins else 0, "p90": pctl(mins, 90)},
         "rounds": sum(x["rounds"] for x in rows), "replans": sum(x["replans"] for x in rows),
         "tokens": tokens, "runs": len(runs), "per_bead": rows}
    checks = {"beads": {"value": c["beads"], "want": ">=%d" % M2["beads"], "ok": c["beads"] >= M2["beads"]},
              "landed_no_ask": {"value": c["landed_no_ask"], "want": ">=%d" % M2["landed_no_ask"],
                                "ok": c["landed_no_ask"] >= M2["landed_no_ask"]},
              "lost": {"value": c["lost"], "want": "0", "ok": c["lost"] == 0},
              "crashes": {"value": c["crashes"], "want": "0", "ok": c["crashes"] == 0}}
    c["m2"] = {"pass": all(v["ok"] for v in checks.values()), "checks": checks}
    return c


# ---- tl-bxk.10.13: what the planner costs ----------------------------------------------------------------------------

HISTORY = "~/.claude/plugins/data/iorlas-delegate-iorlas-marketplace/history.jsonl"


def plan_class(rec):
    """full | amend | back for an engine log's plan node record (older logs: by the node's text)."""
    mode = rec.get("mode")
    if mode in ("amend", "back", "full"):
        return mode
    if mode == "checks_back":
        return "back"
    if mode == "plan":
        return "full"
    t = rec.get("text") or ""
    return "back" if t in ("plan: rewrite checks", "plan: plan to meet it") else "full"  # 'plan: plan', 'plan: re-plan'


def input_tokens(tk):
    """All input tokens of one delegate row. delegate 0.22.0+ writes `in` with cache reads and writes already in it (Codex
    always did); older rows had uncached-only `in`, so cached rides on top: in >= cached means it is already counted."""
    i, c = int((tk or {}).get("in") or 0), int((tk or {}).get("cached") or 0)
    return i if i >= c else i + c


def planner_stats(since, until, prefixes=(), history=None, engine_dir=None):
    """Planner calls per bead from delegate's history (input: `in`, plus cached on rows from before delegate 0.22), split by the engine logs' plan nodes:
    first plan, full plans again (a new thread from scratch), amends, check send-backs. Reads only."""
    history = Path(history or os.path.expanduser(HISTORY))
    engine_dir = Path(engine_dir or tl.config_dir() / "engine")
    calls = {}
    for r in read_jsonl(history):
        t = r.get("ts") or 0
        task = r.get("task") or ""
        if r.get("role") != "planner" or not (since <= t <= until) or not task:
            continue
        if prefixes and prefix(task) not in prefixes:
            continue
        tk = r.get("tokens") or {}
        calls.setdefault(task, []).append(input_tokens(tk))
    rows = []
    for bead, ins in sorted(calls.items()):
        kinds = {"full": 0, "amend": 0, "back": 0}
        for log in engine_dir.glob("%s-*.jsonl" % bead):
            if not STEM.match(log.stem) or STEM.match(log.stem).group(1) != bead:
                continue
            for rec in read_jsonl(log):
                if rec.get("kind") == "node" and rec.get("node") == "plan" and since <= (rec.get("t") or 0) <= until:
                    kinds[plan_class(rec)] += 1
        n = len(ins)
        first = min(1, kinds["full"] or n)
        again = max(kinds["full"] - first, 0)
        other = max(n - first - again - kinds["amend"] - kinds["back"], 0)  # retries of an invalid answer, missing logs
        rows.append({"bead": bead, "calls": n, "first": first, "again": again, "amend": kinds["amend"],
                     "back": kinds["back"], "other": other, "input": sum(ins)})
    allin = [x for ins in calls.values() for x in ins]
    return {"calls": len(allin), "beads": len(rows), "input": sum(allin),
            "median_input": int(statistics.median(allin)) if allin else 0,
            **{k: sum(x[k] for x in rows) for k in ("first", "again", "amend", "back", "other")}, "per_bead": rows}


def planner_line(p):
    return ("planner: %d calls on %d beads: %d first plans, %d full plans again, %d amends, %d check send-backs, %d other; "
            "input %.1fM, median %dk per call" % (
                p["calls"], p["beads"], p["first"], p["again"], p["amend"], p["back"], p["other"],
                p["input"] / 1e6, p["median_input"] // 1000))


def print_planner(p):
    print(planner_line(p))
    print("  %-26s %5s %5s %5s %5s %5s %5s %9s" % ("bead", "calls", "first", "again", "amend", "back", "other", "input M"))
    for x in sorted(p["per_bead"], key=lambda x: -x["input"]):
        print("  %-26s %5d %5d %5d %5d %5d %5d %9.2f" % (x["bead"], x["calls"], x["first"], x["again"], x["amend"],
                                                        x["back"], x["other"], x["input"] / 1e6))


# ---- tl-7y6.1.1: the weekly lifecycle report --------------------------------------------------------------------------

def lifecycle_asks(traces):
    """The ask files are the ask ledger. Only when there is no ledger at all, reconstruct asks from blocked traces.

    Trace rows are not a second ledger: a blocked run can be an engine failure or a pause, and older asks may share a
    bead with a newer file. Counting both inflated the weekly ask count. No authorship is used.
    """
    rows, seen = [], set()
    for f in sorted((tl.config_dir() / "asks").glob("*.json")):
        try:
            a = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(a, dict):
            continue
        key = a.get("id") or (a.get("bead"), lifecycle.fingerprint(a.get("why") or a.get("question") or ""))
        if key in seen:
            continue
        seen.add(key)
        rows.append(a)
    if rows:
        return rows
    for r in traces:
        kind = engine.ask_kind(r.get("why") or "") if r.get("outcome") == "blocked" else ""
        if not kind:
            continue
        aid = r.get("ask") or ""
        key = aid or (r.get("bead"), lifecycle.fingerprint(r.get("why") or ""))
        if key in seen:
            continue
        seen.add(key)
        rows.append({"id": aid, "bead": r.get("bead"), "kind": kind, "why": r.get("why") or "",
                     "t": r.get("ended") or r.get("started"), "run": r.get("run")})
    return rows


def history_rows(path=None):
    """(delegate history rows, available). A missing file is unavailable; an empty one is an empty history."""
    p = Path(path or os.path.expanduser(HISTORY))
    if not p.exists():
        return None, False
    return read_jsonl(p), True


def lane_observations():
    """Timestamped quota readings from agent-runs lane records; one snapshot is not a history."""
    out = []
    for f in sorted((tl.config_dir() / "agent-runs" / "lanes").glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        at = d.get("at") if isinstance(d, dict) else None
        lanes = d.get("lanes") if isinstance(d, dict) else None
        if not isinstance(at, (int, float)) or not isinstance(lanes, list):
            continue
        for ln in lanes:
            if not isinstance(ln, dict):
                continue
            for u in ln.get("usage") or []:
                if isinstance(u, dict) and isinstance(u.get("used_pct"), (int, float)):
                    out.append({"t": at, "lane": ln.get("name") or "?", "window": u.get("window") or "?",
                                "used_pct": u["used_pct"]})
    return out


def quota_snapshot(route=None, lanes=None, now=None):
    """What delegate says now: a snapshot, never a measurement of what the window consumed."""
    now = time.time() if now is None else now
    if lanes is None:
        route = lroute.find_route() if route is None else route
        lanes = lroute.lane_status(route) if route else {}
    if isinstance(lanes, list):
        lanes = {str(x.get("name") or "?"): x for x in lanes if isinstance(x, dict)}
    rows = []
    for name, ln in (lanes or {}).items():
        if not isinstance(ln, dict):
            continue
        usage = list(ln.get("usage") or [])
        for key, window in (("five", "5h"), ("week", "week")):  # delegate status --json today: five/week percentages
            if isinstance(ln.get(key), (int, float)) and not isinstance(ln.get(key), bool):
                usage.append({"window": window, "used_pct": ln[key]})
        for u in usage:
            if not isinstance(u, dict) or not isinstance(u.get("used_pct"), (int, float)):
                continue
            rows.append({"lane": name, "window": u.get("window") or "?", "used_pct": u["used_pct"],
                         "resets_at": u.get("resets_at"), "out": bool(ln.get("out")),
                         "out_until": ln.get("out_until"), "why": ln.get("why")})
    return {"available": bool(rows), "at": now, "at_iso": lifecycle.utc_iso(now), "lanes": rows}


def reverts_of(repo, traces, until, base=None):
    """Landing run -> reverted/fixed_forward/clean/censored/unknown, from git's messages only.

    A revert names the landed sha (or its exact subject); a fixed-forward explicitly says so and names the sha or bead.
    A later commit that merely touches the same files is never linked. A landing whose seven-day follow-up runs past
    `until` is censored: it is listed, but not put in the rate's denominator.
    """
    base = base or default_base(repo)
    bases = bases_of(repo, base)
    if not bases:
        return {(r.get("run") or r.get("bead")): {"status": "unknown"} for r in traces if r.get("bead")}
    r = tl.run_git(repo, "log", "--format=%H%x1f%ct%x1f%B%x1e", *bases, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
    if r.returncode != 0:
        return {(x.get("run") or x.get("bead")): {"status": "unknown"} for x in traces if x.get("bead")}
    commits = []
    for chunk in (r.stdout or "").split("\x1e"):
        parts = chunk.strip().split("\x1f")
        if len(parts) < 3 or not parts[0]:
            continue
        try:
            commits.append((parts[0], int(parts[1]), parts[2]))
        except ValueError:
            continue
    commits.sort(key=lambda x: x[1])
    out = {}
    for x in lifecycle._landings(traces):
        r = x["run"]
        key = r.get("run") or x["bead"]
        sha = str(r.get("sha") or "").lower()
        if not sha:
            out[key] = {"status": "unknown"}
            continue
        short = sha[:12]
        subj = ""
        landed_at = None
        # The landed commit's own subject and time, when the sha is in this repository.
        for csha, ct, body in commits:
            if csha == sha or csha.startswith(short):
                subj = (body.strip().splitlines() or [""])[0]
                landed_at = ct
                break
        if landed_at is None:
            out[key] = {"status": "unknown"}
            continue
        t = (lifecycle.span(r) or (None, None))[1]
        if t is None:
            t = landed_at
        if t + 7 * lifecycle.DAY > until:
            out[key] = {"status": "censored"}
            continue
        status = "clean"
        for csha, ct, body in commits:
            if not (t < ct <= t + 7 * lifecycle.DAY):
                continue
            low = body.lower()
            names = sha in low or (short and short in low) or (subj and subj.lower() in low)
            if "revert" in low and names:
                status = "reverted"
                break
            if re.search(r"\bfix(?:ed)?[- ]forward\b", low) and (names or (x["bead"] and x["bead"] in body)):
                status = "fixed_forward"
                break
        out[key] = {"status": status, "at": t}
    return out


def lifecycle_stats(repo, since, until, traces=None, history=None, quota=None, reverts=None, now=None,
                    quota_observations=None, whole=False):
    repo = tl.repo_root(repo)
    traces = repo_traces(repo) if traces is None else traces
    records = {r.get("run"): read_jsonl(r.get("log") or "") for r in traces if r.get("run")}
    if history is None:
        history, available = history_rows()
        if not available:
            history = None
    if quota is None:
        quota = quota_snapshot(now=now)
    if reverts is None:
        reverts = reverts_of(repo, traces, until, base=default_base(repo))
    asks = lifecycle_asks(traces)
    observations = lane_observations() if quota_observations is None else quota_observations
    return lifecycle.lifecycle_report(traces, records_by_run=records, asks=asks, history=history, quota=quota,
                                      since=since, until=until, reverts=reverts,
                                      quota_observations=observations, whole=whole)


def fmt(v, suffix="", pct=False, nd=1):
    if v is None:
        return "unavailable"
    if pct:
        return "%.1f%%" % (v * 100)
    return ("%." + str(nd) + "f") % v + suffix


def kpi(id):
    """The registry id a sidecar's `metric` may use, printed in brackets after the line's own numbers (tl-7y6.1.2)."""
    return "  [%s]" % id


def print_lifecycle(r):
    print("tl report lifecycle  %s -> %s  (UTC weeks)" % (r["since_iso"], r["until_iso"]))
    for w in r["weeks"]:
        print("week %s .. %s (%.1f d)" % (w["start_iso"], w["end_iso"], w["days"]))
        print("  landed beads/day: %s (%d in %.1f d)%s" % (
            fmt(w["landed_beads_per_day"], nd=2), w["landed_beads"], w["days"], kpi("landed_beads_per_day")))
        print("  slot-min per landed bead: %s (%.1f slot-min / %d landed)%s" % (
            fmt(w["slot_min_per_landed"]), w["slot_min"], w["landed_beads"], kpi("slot_min_per_landed")))
        print("  non-landing slot-min share: %s (%.1f of %.1f slot-min)%s" % (
            fmt(w["non_landing_share"], pct=True), w["non_landing_slot_min"], w["slot_min"],
            kpi("non_landing_slot_min_share")))
        print("  avoidable asks/week: %d (of %d asks)%s" % (
            w["avoidable_asks"], w["asks"], kpi("avoidable_asks_per_week")))
        print("  beads landed on run 1: %d (%s of %d landed; %s of %d touched)%s" % (
            w["landed_run1"], fmt(w["landed_run1_share"], pct=True), w["landed_beads"],
            fmt(w.get("landed_run1_share_touched"), pct=True), w.get("touched", 0), kpi("landed_run1_share")))
        print("  runs per landed bead: %s (%d runs / %d landed)%s" % (
            fmt(w["runs_per_landed"], nd=2), w["runs"], w["landed_beads"], kpi("runs_per_landed")))
        print("  median dead time per started_because (min): " + ", ".join(
            "%s %s" % (k, fmt(w["dead_time_min"].get(k))) for k in lifecycle.STARTED_BECAUSE))
        fps = w["fingerprints"]
        print("  fingerprint top-5 (beads/day): " + ("; ".join(
            "%s %.2f (%d)" % (x["fingerprint"][:48], x["per_day"], x["beads"]) for x in fps) or "none"))
        streaks = w["fingerprint_streaks"]
        print("  max consecutive same-fingerprint non-done runs per (lane,model): " + (
            "unavailable" if streaks is None else ("; ".join(
                "%s/%s %d" % (x["lane"], x["model"], x["max"]) for x in streaks[:5]) or "none")))
        print("  slot-min in runs >180 min: %.1f%s" % (w["slot_min_over_180"], kpi("slot_min_over_180")))
        print("  verify-stage slot-min: %s%s" % (fmt(w["verify_slot_min"]), kpi("verify_stage_slot_min")))
        print("  hung-step slot-min: %s (%d kills)%s" % (fmt(w["hung_slot_min"]), w["hung_kills"],
                                                          kpi("hung_step_slot_min")))
        print("  median release-gate minutes: %s (%d gates)%s" % (
            fmt(w["release_gate_median_min"]), w["release_gates"], kpi("median_release_gate_minutes")))
        print("  uncached input tokens per landed bead: %s (%d uncached)%s" % (
            fmt(w["uncached_input_per_landed"]), w["uncached_input"], kpi("uncached_input_tokens_per_landed_bead")))
        print("  reverts per 100 landings: %s (reverted %d, fixed-forward %d, censored %d, eligible %d)%s" % (
            fmt(w["reverts_per_100"], nd=2), w["reverts"], w["fixed_forward"], w["revert_censored"],
            w["revert_eligible"], kpi("reverts_per_100_landings")))
        print("  quota %% consumed per landed bead: %s (a single current snapshot cannot measure a week)%s" % (
            fmt(w["quota_pct_per_landed"], nd=2), kpi("quota_percent_per_landed_bead")))
        if w["unavailable"]:
            print("  unavailable: " + ", ".join(w["unavailable"]))
    q = r.get("quota") or {}
    if q.get("available"):
        print("quota snapshot %s:" % q.get("at_iso"))
        for x in q.get("lanes") or []:
            print("  %s %s: %.1f%%%s" % (x["lane"], x["window"], x["used_pct"], " (out)" if x.get("out") else ""))
    else:
        print("quota snapshot: unavailable")


# ---- CLI --------------------------------------------------------------------------------------------------------------

def mtok(d):
    return "%.1fM in (%.1fM cached), %dk out" % (d["in"] / 1e6, d["cached"] / 1e6, d["out"] // 1000)


def print_card(c):
    a = c["asks"]
    print("tl report %s  %s -> %s  (runs overlapping the window: %d)" % (
        Path(c["repo"]).name, stamp(c["since"]), stamp(c["until"]), c["runs"]))
    print("  beads %d   landed %d   landed with no ask %d   parked %d   paused %d   failed %d" % (
        c["beads"], c["landed"], c["landed_no_ask"], c["parked"], c["paused"], c["failed"]))
    print("  asks %d on %d beads: owner %d, supervisor %d, open %d%s" % (
        a["count"], a["beads"], a["owner"], a["supervisor"], a["open"],
        ", unknown %d" % a["unknown"] if a["unknown"] else ""))
    print("  crashes %d   lost %d   pending branches %d" % (c["crashes"], c["lost"], len(c["pending_list"])))
    print("  minutes per bead: median %s, p90 %s   fix rounds %d   replans %d" % (
        c["minutes"]["median"], c["minutes"]["p90"], c["rounds"], c["replans"]))
    for key in ("lane", "role"):
        for name, d in sorted(c["tokens"][key].items()):
            print("  tokens %-5s %-9s %s" % (key, name, mtok(d)))
    if c.get("planner") and c["planner"]["calls"]:
        print("  " + planner_line(c["planner"]))
    for x in c["crash_list"]:
        print("  crash   %s %s  %s" % (stamp(x["t"])[11:], x["bead"], x["why"]))
    for x in c["lost_list"]:
        print("  lost    %s %s %s  %s" % (x["branch"], x["sha"][:8], x["subject"][:50], x["why"]))
    for x in c["per_bead"]:
        if x["state"] != "landed" or x["asks"]:
            print("  %-7s %s%s%s" % (x["state"], x["bead"], "  asks: " + ",".join(x["answers"]) if x["asks"] else "",
                                     "  " + x["why"][:100] if x["why"] else ""))
    bad = ["%s %s (want %s)" % (k, v["value"], v["want"]) for k, v in c["m2"]["checks"].items() if not v["ok"]]
    print("M2 %s%s" % ("PASS" if c["m2"]["pass"] else "FAIL", ": " + "; ".join(bad) if bad else ""))


def window(a):
    now = time.time()
    since = parse_time(a.since, now) if getattr(a, "since", None) else now - 86400
    until = parse_time(a.until, now, forward=True) if getattr(a, "until", None) else now
    return since, until


def cmd_lifecycle(a):
    now = time.time()
    since = parse_time(getattr(a, "since", None), now) if getattr(a, "since", None) else now - 28 * 86400
    until = parse_time(getattr(a, "until", None), now, forward=True) if getattr(a, "until", None) else now
    r = lifecycle_stats(tl.repo_root(getattr(a, "repo", None)), since, until, now=now)
    if getattr(a, "json", False):
        print(json.dumps(r, indent=1, ensure_ascii=False))
    else:
        print_lifecycle(r)
    return 0


def cmd_report(a):
    if getattr(a, "kind", None) == "lifecycle":
        return cmd_lifecycle(a)
    since, until = window(a)
    if getattr(a, "planner", False):
        pre = {x.strip() for x in (getattr(a, "prefix", "") or "").split(",") if x.strip()}
        p = planner_stats(since, until, pre)
        if a.json:
            print(json.dumps(p, indent=1, ensure_ascii=False))
        else:
            print_planner(p)
        return 0
    repo = tl.repo_root(a.repo)
    c = scorecard(repo, since, until, base=default_base(repo), alive=run_alive)
    c["planner"] = planner_stats(since, until, {prefix(x["bead"]) for x in c["per_bead"]})
    if a.json:
        print(json.dumps(c, indent=1, ensure_ascii=False))
    else:
        print_card(c)
    return 0 if c["m2"]["pass"] else 1


def cmd_lost(a):
    repo = tl.repo_root(a.repo)
    since = parse_time(a.since) if a.since else None
    rows = lost_work(repo, since=since, base=default_base(repo))
    if a.json:
        print(json.dumps(rows, indent=1, ensure_ascii=False))
    else:
        for x in rows:
            if x["class"] != "landed":
                print("%-9s %-28s %s %s  %s" % (x["class"], x["branch"], x["sha"][:8], stamp(x["time"]), x["why"]))
        n = {k: sum(x["class"] == k for x in rows) for k in ("landed", "reclaimed", "pending", "unknown", "lost")}
        print("%d lost, %d pending, %d unknown, %d reclaimed, %d landed (commits on task/* and wip/* not on the base)" % (
            n["lost"], n["pending"], n["unknown"], n["reclaimed"], n["landed"]))
    return 1 if any(x["class"] == "lost" for x in rows) else 0
