"""tl reflect digest: turn the engine's per-run reflections into fixes (tl-bl5).

  tl.py reflect digest [--since T] [--until T] [--dry-run] [--json]   default window: the last 24 h
  The loop calls maybe_run() on every pass: once a day, a detached `tl reflect digest`.

Reads the `reflection` of every run in traces.jsonl (all repos), clusters the went_badly items by cause class and by what they say
(or the files they name), and for each cause that recurs in MIN_RUNS or more runs files one bead in the repo that owns the cause
(engine and prompt: task-loop; delegate: delegate; the rest: the project the runs ran in), with the run ids as evidence and
acceptance criteria. A cause already filed (the state file, or an open bead of that repo with a like title) gets a comment with its
new runs instead; one whose bead is closed and that happens again gets a new bead that names the old one.
State: ~/.config/task-loop/reflect-digest.json. Python 3.8+, standard library only."""

import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

from taskloop.adapters import beadtools, ident, landlock
from taskloop.adapters import procs as sproc
from taskloop.contracts.ports import BdFailure, BeadQuery, NewBead

MIN_RUNS = 2
SIMILAR = 0.35  # token overlap (Jaccard) that makes two went_badly items one cause
FILE_SIMILAR = 0.1  # ... or this much when they also name the same file (a bare tl.py or README.md must not merge unrelated items)
TITLE_SIMILAR = 0.5  # ... and an open bead's title the same as a cluster
DAY = 86400
OWNERS = {"engine": "iorlas-task-loop", "prompt": "iorlas-task-loop", "delegate": "iorlas-delegate"}
STOP = set("the and for with that this from was were has had not but are its into then than when after before each have been "
           "run runs session step bead one two still more over only also because while which they their there about".split())
FILE = re.compile(r"[\w./-]+\.(?:py|md|cs|json|ya?ml|toml|html|js|ts|sh|cfg|txt)\b")


def state_path():
    return ident.config_dir() / "reflect-digest.json"


def read_state():
    try:
        d = json.loads(state_path().read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(st):
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
    os.replace(str(tmp), str(p))


def tokens(text):
    return {w for w in re.findall(r"[^\W\d_]{4,}", str(text).lower()) if w not in STOP}


def jaccard(a, b):
    return len(a & b) / float(len(a | b)) if a and b else 0.0


def items(since, until, traces=None) -> list[dict[str, Any]]:
    """The went_badly items of the reflected runs ended in the window, oldest first."""
    path = traces or ident.config_dir() / "traces.jsonl"
    out: list[dict[str, Any]] = []
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for ln in lines:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        refl = r.get("reflection") if isinstance(r, dict) else None
        if not isinstance(refl, dict):
            continue
        t = r.get("ended") or r.get("started") or 0
        try:
            t = float(t)
        except (TypeError, ValueError):
            continue
        if not since <= t <= until:
            continue
        for b in refl.get("went_badly") or []:
            if not isinstance(b, dict) or not b.get("what"):
                continue
            text = "%s %s" % (b.get("what"), b.get("evidence") or "")
            out.append({"cause": str(b.get("cause") or "other"), "what": str(b["what"]), "evidence": str(b.get("evidence") or ""),
                        "session": str(b.get("session") or ""), "run": str(r.get("run") or ""), "bead": str(r.get("bead") or ""),
                        "repo": str(r.get("repo_url") or ""), "t": t, "tokens": tokens(b["what"]), "files": {os.path.basename(f) for f in FILE.findall(text)}})
    return sorted(out, key=lambda i: i["t"])


def cluster(its: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Greedy, per cause class: an item joins the cluster of any item it shares a file with or says nearly the same as."""
    cl: list[dict[str, Any]] = []
    for it in its:
        for c in cl:
            if c["cause"] == it["cause"] and any(jaccard(it["tokens"], m["tokens"]) >= SIMILAR or
                                                 (it["files"] & m["files"] and jaccard(it["tokens"], m["tokens"]) >= FILE_SIMILAR)
                                                 for m in c["items"]):
                c["items"].append(it)
                break
        else:
            cl.append({"cause": it["cause"], "items": [it]})
    out: list[dict[str, Any]] = []
    for c in cl:
        m = c["items"]
        runs = sorted({i["run"] for i in m if i["run"]})
        counts = Counter(w for i in m for w in i["tokens"])
        out.append({"cause": c["cause"], "title": min((str(i["what"]) for i in m), key=len)[:100], "runs": runs,
                    "beads": sorted({i["bead"] for i in m if i["bead"]}), "repos": Counter(i["repo"] for i in m if i["repo"]),
                    "files": sorted(set().union(*[i["files"] for i in m]))[:8], "items": m,
                    "tokens": {w for w, _ in counts.most_common(12)}, "last": max(i["t"] for i in m)})
    return sorted(out, key=lambda c: (-len(c["runs"]), c["cause"]))


def is_recurring(c):
    """Two beads show it, or one bead's run did it three times: one retried bead with one complaint is a bead's problem."""
    runs = c["runs"] if isinstance(c.get("runs"), list) else c["run_ids"]
    return len(runs) >= 3 or (len(runs) >= MIN_RUNS and len(c["beads"]) >= 2)


def recurring(clusters):
    return [c for c in clusters if is_recurring(c)]


def registered():
    try:
        d = json.loads((ident.config_dir() / "repos.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [p for p in (d if isinstance(d, list) else list(d)) if isinstance(p, str) and (Path(p) / ".beads").is_dir()]


def resolve_repo(value, repos):
    """A trace's `repo` is the origin's URL (or the worktree path when there is no origin): -> the registered repo folder it is."""
    v = str(value or "")
    if not v:
        return ""
    if v in repos:
        return v
    if os.path.isdir(v):
        real = os.path.realpath(v)
        hits = [p for p in repos if real == os.path.realpath(p) or real.startswith(os.path.realpath(p) + os.sep)]
        return max(hits, key=len) if hits else ""
    name = re.sub(r"\.git$", "", v.rstrip("/").replace(":", "/").split("/")[-1])
    for p in repos:
        if Path(p).name == name:
            return p
    return ""


def owner_repo(c, repos=None):
    """The repo whose bead list takes this cause: task-loop, delegate, or the project most of its runs ran in."""
    repos = registered() if repos is None else repos
    want = OWNERS.get(c["cause"])
    if want:
        for p in repos:
            if Path(p).name == want:
                return p
    mine = Counter()
    for r_, n in c["repos"].items():
        hit = resolve_repo(r_, repos)
        if hit:
            mine[hit] += n
    return mine.most_common(1)[0][0] if mine else ""


def same_cause(e, c):
    t = jaccard(set(e.get("tokens") or []), c["tokens"])
    return t >= SIMILAR or bool(set(e.get("files") or []) & set(c["files"]) and t >= FILE_SIMILAR)


def known_bead(c, repo, state):
    """-> (bead id, why) of the bead that already carries this cause: the state file's, else an open bead of the repo with a like
    title; ('', '') when none."""
    for e in reversed(state.get("filed", [])):  # the newest first: a closed one's successor wins
        if e.get("cause") == c["cause"] and e.get("repo") == repo and same_cause(e, c):
            return e["bead"], "filed"
    try:
        rows = beadtools.bd_store(repo).find(BeadQuery())  # the default filter leaves out closed beads only
    except BdFailure:
        rows = []
    ct = tokens(c["title"])
    for b in rows:
        if jaccard(tokens(b.title), ct) >= TITLE_SIMILAR:
            return b.id, "open"
    return "", ""


def is_closed(bead, repo):
    row = beadtools.peek(beadtools.bd_store(repo), bead)
    return row is not None and row.status == "closed"


def evidence_lines(c):
    out = []
    for i in c["items"][:8]:
        out.append("- run %s (bead %s, session %s): %s%s" % (i["run"] or "?", i["bead"] or "?", i["session"] or "run", i["what"][:200],
                                                           " | evidence: " + i["evidence"][:200] if i["evidence"] else ""))
    return out


def description(c, old=""):
    where = (" Files named: %s." % ", ".join(c["files"])) if c["files"] else ""
    return ("Recurring cause (%s) in %d runs, from the engine's run reflections (tl reflect digest).%s%s\n\nEvidence:\n%s\n\n"
            "Runs: %s\nTrace: `tl trace <bead>` lists each run's worker sessions." % (
                c["cause"], len(c["runs"]), where, (" Recurred after %s was closed." % old) if old else "",
                "\n".join(evidence_lines(c)), ", ".join(c["runs"])))


def acceptance(c):
    return ("The cause no longer shows in new reflections: after the fix, the next 3 runs of comparable beads (e.g. %s) end with no "
            "went_badly item of cause '%s' saying: %s" % (c["beads"][0] if c["beads"] else "the beads above", c["cause"], c["title"]))


def file_cluster(c: dict[str, Any], state: dict[str, Any], dry=False, repos=None):
    """File or update the bead for one recurring cause. -> {action: filed|commented|skipped|none, bead, repo, cause, runs}."""
    repo = owner_repo(c, repos)
    res = {"cause": c["cause"], "title": c["title"], "repo": repo, "runs": c["runs"], "bead": "", "action": "none"}
    if not repo:
        return res
    bead, why = known_bead(c, repo, state)
    old = ""
    if bead and why == "filed" and is_closed(bead, repo):
        for e in state.get("filed", []):
            if e.get("bead") == bead and e.get("repo") == repo:
                e["closed"] = True  # its successor takes the cause from here
        old, bead = bead, ""
    if bead:
        entry: dict[str, Any] | None = next((e for e in state.get("filed", []) if e.get("bead") == bead and e.get("repo") == repo), None)
        if entry is None:  # an open bead found by title: remember it, so its runs are commented once
            entry = {"cause": c["cause"], "repo": repo, "bead": bead, "tokens": sorted(c["tokens"]), "files": c["files"], "runs": [],
                     "at": time.time()}
            if not dry:
                state.setdefault("filed", []).append(entry)
        new = [r_ for r_ in c["runs"] if r_ not in entry["runs"]]
        res.update(bead=bead, action="skipped")
        if new:
            res["action"] = "commented"
            if not dry:
                beadtools.attempt(beadtools.bd_store(repo).add_comment, bead, "Reflect digest: the cause recurred in %d more run(s): %s\n%s" % (
                    len(new), ", ".join(new), "\n".join(evidence_lines(dict(c, items=[i for i in c["items"] if i["run"] in new])))))
                entry["runs"] = sorted(set(entry["runs"]) | set(new))
        return res
    title = "Reflect: %s: %s" % (c["cause"], c["title"])[:140]
    res["action"] = "filed"
    if dry:
        return res
    try:
        new_id = beadtools.bd_store(repo).create(NewBead(title=title, priority=3, labels=["reflect", "cause-%s" % c["cause"]],
                                                  description=description(c, old), acceptance_criteria=acceptance(c)))
    except BdFailure:
        new_id = ""
    if not new_id:
        res["action"] = "failed"
        return res
    res["bead"] = new_id
    state.setdefault("filed", []).append({"cause": c["cause"], "repo": repo, "bead": new_id, "tokens": sorted(c["tokens"]),
                                          "files": c["files"], "runs": c["runs"], "at": time.time()})
    return res


def digest(since, until, dry=False, traces=None, repos=None):
    """-> {window, clusters: [...], actions: [...]}. Files and updates beads unless dry; one digest at a time (a manual run and
    the daily one never both file the cause), the state saved after every bead so a crash loses none."""
    if dry:
        return _digest(since, until, True, traces, repos)
    try:
        with landlock.os_lock(ident.config_dir() / "locks" / "reflect-digest-run.lock", "pid %d" % os.getpid(), timeout=120):
            return _digest(since, until, False, traces, repos)
    except TimeoutError:
        return {"since": since, "until": until, "items": 0, "clusters": [], "actions": [], "busy": True}


def _digest(since, until, dry, traces, repos):
    cs = cluster(items(since, until, traces))
    out = {"since": since, "until": until, "items": sum(len(c["items"]) for c in cs), "clusters": [], "actions": []}
    state = read_state()
    for c in cs:
        row = {"cause": c["cause"], "title": c["title"], "runs": len(c["runs"]), "run_ids": c["runs"], "beads": c["beads"],
               "files": c["files"], "recurring": is_recurring(c)}
        out["clusters"].append(row)
        if row["recurring"]:
            a = file_cluster(c, state, dry, repos)
            out["actions"].append(a)
            row["bead"], row["repo"] = a["bead"], a["repo"]
            if not dry and a["action"] in ("filed", "commented"):
                write_state(state)
    return out


def view(hours=24, now=None):
    """For the dashboard: the clusters of the last `hours`, each with the bead filed for it (state file), nothing written."""
    now = now or time.time()
    cs = cluster(items(now - hours * 3600, now))
    st = read_state()
    out = []
    for c in cs:
        e = next((e for e in st.get("filed", []) if e.get("cause") == c["cause"] and not e.get("closed") and same_cause(e, c)), None)
        out.append({"cause": c["cause"], "title": c["title"], "runs": len(c["runs"]), "run_ids": c["runs"][:12], "beads": c["beads"][:8],
                    "files": c["files"], "recurring": is_recurring(c), "bead": (e or {}).get("bead", ""),
                    "repo": (e or {}).get("repo", ""), "last": c["last"]})
    return {"hours": hours, "clusters": out}


def due(now=None):
    return (now or time.time()) - float(read_state().get("tried") or 0) >= DAY


def maybe_run(now=None):
    """The loop's call: once a day a detached `tl reflect digest` (it asks bd about every open bead of the target repos: a loop
    pass never waits for it). -> 'started' or ''."""
    if not due(now) or not (ident.config_dir() / "traces.jsonl").is_file() or not registered():
        return ""  # nothing to read or nowhere to file
    try:
        with landlock.os_lock(ident.config_dir() / "locks" / "reflect-digest.lock", "pid %d" % os.getpid()):
            if not due(now):
                return ""
            pass
        sproc.spawn([sys.executable, str(Path(__file__).resolve().with_name("tl.py")), "reflect", "digest"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        st = read_state()
        st["tried"] = now or time.time()
        write_state(st)
    except OSError:
        return ""
    return "started"


def cmd_reflect(a):
    now = time.time()

    def at(text, default):
        if not text:
            return default
        m = re.fullmatch(r"(\d+)h", text.strip())
        if m:
            return now - int(m.group(1)) * 3600
        import report
        return float(text) if re.match(r"^\d{9,}(\.\d+)?$", text.strip()) else report.parse_time(text, now)
    st = read_state()
    since = at(a.since, max(now - 3 * DAY, float(st.get("until") or 0) or now - DAY))  # since the last digest ended, 3 days at most
    d = digest(since, at(a.until, now), dry=a.dry_run)
    if not a.dry_run and not a.since and not d.get("busy"):
        st = read_state()
        st["until"] = now
        write_state(st)
    if a.json:
        print(json.dumps(d, indent=1, default=str))
        return 0
    print("%d bad items in %d causes, %d recurring%s" % (d["items"], len(d["clusters"]), len(d["actions"]), " (dry run)" if a.dry_run else ""))
    for x in d["actions"]:
        print("  %-9s [%s] %s -> %s %s (%d runs)" % (x["action"], x["cause"], x["title"][:60], Path(x["repo"]).name or "?",
                                                      x["bead"] or "-", len(x["runs"])))
    return 0
