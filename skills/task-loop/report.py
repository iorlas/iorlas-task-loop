"""tl report and tl lost: the M2 scorecard over a time window, and the bead-branch commits no run will bring home.

Reads only: traces.jsonl, the loop's log, engine/*.jsonl and *.stderr, the repo's git refs (never fetched), and bd
(show, comments). Writes nothing.

  tl.py report [--repo DIR] [--since T] [--until T] [--json]   beads run, landed, landed with no ask, parked, paused,
                                                                failed, crashes, lost work, minutes, rounds, tokens, M2
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
import loop
import tl

M2 = {"beads": 10, "landed_no_ask": 7}  # at least; lost and crashes must be 0 (docs/roadmap.md)
QUIET_MIN = 30  # an engine log with no close and no trace, untouched this long and with no live run-task: a crash
# how the supervising session marks its own answers ("relayed by Claude" carries the owner's words: the owner's)
SUPERVISOR = re.compile(r"\(Claude, supervising|checked by Claude|delegated the call to Claude")
ANSWERED = re.compile(r"\bask (\S+) \(\w+\) is answered|\banswered verify ask (\S+)")
STEM = re.compile(r"^(.+)-(\d{8}-\d{6})$")


# ---- the window -------------------------------------------------------------------------------------------------------

def parse_time(text, now=None):
    """Epoch seconds for T: a duration back from now (90m, 12h, 2d), HH:MM today, or ISO (naive = local time)."""
    now = time.time() if now is None else now
    s = (text or "").strip()
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([mhd])$", s)
    if m:
        return now - float(m.group(1)) * {"m": 60, "h": 3600, "d": 86400}[m.group(2)]
    m = re.match(r"^(\d{1,2}):(\d{2})$", s)
    if m:
        day = datetime.fromtimestamp(now)
        return day.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=0, microsecond=0).timestamp()
    try:
        d = datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
    except ValueError:
        raise ValueError("not a time: %r (use ISO, HH:MM or a duration like 12h)" % text)
    return d.timestamp()


def stamp(t):
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(t))


# ---- inputs -----------------------------------------------------------------------------------------------------------

def git(repo, *args):
    r = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
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

def lost_work(repo, since=None, base=None, status_of=None, traces=None):
    """Every commit on a task/<bead> or wip/* branch that is not on the base, classed:
    landed     its patch is on the base (git cherry), or a land of its bead came after it: a base commit titled
               '... (<bead>)' or the land sha a trace recorded, on the base (squash lands are no ancestors);
    reclaimed  a later run of the bead started after it (the engine continues the branch);
    pending    its bead is still open, blocked or in progress: the next run continues the branch;
    lost       its bead is closed (or unknown) with no land after it, or it is on a wip/* branch of a dead session."""
    base = base or default_base(repo)
    bases = bases_of(repo, base) or [base]
    status_of = status_of or (lambda b: (tl.show(b, cwd=repo) or {}).get("status"))
    traces = repo_traces(repo) if traces is None else traces
    lands = {}  # bead -> times its land reached the base
    for ln in git(repo, "log", "--format=%ct %s", *bases).splitlines():
        t, _, subj = ln.partition(" ")
        m = re.search(r"\(([^()\s]+)\)\s*$", subj)
        if m and t.isdigit():
            lands.setdefault(m.group(1), []).append(int(t))
    for r in traces:
        if r.get("outcome") == "landed" and r.get("sha") and any(
                subprocess.run(["git", "-C", repo, "merge-base", "--is-ancestor", r["sha"], b],
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
                if st == "closed":
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
    """Runs that ended with no outcome: the loop saw run-task exit with none; an engine log in the window with no close
    record and no trace, quiet for QUIET_MIN and with no live run-task; or a Python traceback in a run's stderr."""
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
    for r in traces:
        if not overlaps(r, since, until) or not r.get("stderr"):
            continue
        try:
            err = Path(r["stderr"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "Traceback (most recent call last)" in err:
            out.setdefault(r.get("run"), {"bead": r.get("bead"), "t": r.get("started") or 0, "run": r.get("run"),
                                          "why": "a traceback in its stderr: %s" % err.strip().splitlines()[-1][:120]})
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
                for k in d:
                    d[k] += int(tk.get(k) or 0)
    lost = [x for x in lost_work(repo, since=since, base=base, status_of=status_of, traces=traces)
            if x["class"] in ("lost", "pending")]
    mins = [x["minutes"] for x in rows if x["runs"]]
    c = {"repo": repo, "since": since, "until": until, "beads": len(rows),
         "landed": sum(x["state"] == "landed" for x in rows),
         "landed_no_ask": sum(x["state"] == "landed" and not x["asks"] for x in rows),
         "parked": sum(x["state"] == "parked" for x in rows), "paused": sum(x["state"] == "paused" for x in rows),
         "failed": sum(x["state"] == "failed" for x in rows), "asks": asks,
         "crashes": len(crash), "crash_list": crash,
         "lost": sum(x["class"] == "lost" for x in lost), "lost_list": [x for x in lost if x["class"] == "lost"],
         "pending_list": [x for x in lost if x["class"] == "pending"],
         "minutes": {"median": statistics.median(mins) if mins else 0, "p90": pctl(mins, 90)},
         "rounds": sum(x["rounds"] for x in rows), "replans": sum(x["replans"] for x in rows),
         "tokens": tokens, "runs": len(runs), "per_bead": rows}
    checks = {"beads": {"value": c["beads"], "want": ">=%d" % M2["beads"], "ok": c["beads"] >= M2["beads"]},
              "landed_no_ask": {"value": c["landed_no_ask"], "want": ">=%d" % M2["landed_no_ask"],
                                "ok": c["landed_no_ask"] >= M2["landed_no_ask"]},
              "lost": {"value": c["lost"], "want": "0", "ok": c["lost"] == 0},
              "crashes": {"value": c["crashes"], "want": "0", "ok": c["crashes"] == 0}}
    c["m2"] = {"pass": all(v["ok"] for v in checks.values()), "checks": checks}
    return c


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
    until = parse_time(a.until, now) if getattr(a, "until", None) else now
    return since, until


def cmd_report(a):
    repo = tl.repo_root(a.repo)
    since, until = window(a)
    c = scorecard(repo, since, until, base=default_base(repo), alive=run_alive)
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
        n = {k: sum(x["class"] == k for x in rows) for k in ("landed", "reclaimed", "pending", "lost")}
        print("%d lost, %d pending, %d reclaimed, %d landed (commits on task/* and wip/* not on the base)" % (
            n["lost"], n["pending"], n["reclaimed"], n["landed"]))
    return 1 if any(x["class"] == "lost" for x in rows) else 0
