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

import tl

MIN_RUNS = 2
SIMILAR = 0.35  # token overlap (Jaccard) that makes two went_badly items one cause
TITLE_SIMILAR = 0.5  # ... and an open bead's title the same as a cluster
DAY = 86400
OWNERS = {"engine": "iorlas-task-loop", "prompt": "iorlas-task-loop", "delegate": "iorlas-delegate"}
STOP = set("the and for with that this from was were has had not but are its into then than when after before each have been "
           "run runs session step bead one two still more over only also because while which they their there about".split())
FILE = re.compile(r"[\w./-]+\.(?:py|md|cs|json|ya?ml|toml|html|js|ts|sh|cfg|txt)\b")


def state_path():
    return tl.config_dir() / "reflect-digest.json"


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


def items(since, until, traces=None):
    """The went_badly items of the reflected runs ended in the window, oldest first."""
    path = traces or tl.config_dir() / "traces.jsonl"
    out = []
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
                        "repo": str(r.get("repo") or ""), "t": t, "tokens": tokens(b["what"]), "files": {os.path.basename(f) for f in FILE.findall(text)}})
    return sorted(out, key=lambda i: i["t"])


def cluster(its):
    """Greedy, per cause class: an item joins the cluster of any item it shares a file with or says nearly the same as."""
    cl = []
    for it in its:
        for c in cl:
            if c["cause"] == it["cause"] and any(it["files"] & m["files"] or jaccard(it["tokens"], m["tokens"]) >= SIMILAR
                                                 for m in c["items"]):
                c["items"].append(it)
                break
        else:
            cl.append({"cause": it["cause"], "items": [it]})
    out = []
    for c in cl:
        m = c["items"]
        runs = sorted({i["run"] for i in m if i["run"]})
        counts = Counter(w for i in m for w in i["tokens"])
        out.append({"cause": c["cause"], "title": min((i["what"] for i in m), key=len)[:100], "runs": runs,
                    "beads": sorted({i["bead"] for i in m if i["bead"]}), "repos": Counter(i["repo"] for i in m if i["repo"]),
                    "files": sorted(set().union(*[i["files"] for i in m]))[:8], "items": m,
                    "tokens": {w for w, _ in counts.most_common(12)}, "last": max(i["t"] for i in m)})
    return sorted(out, key=lambda c: (-len(c["runs"]), c["cause"]))


def recurring(clusters):
    return [c for c in clusters if len(c["runs"]) >= MIN_RUNS]


def registered():
    try:
        d = json.loads((tl.config_dir() / "repos.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [p for p in (d if isinstance(d, list) else list(d)) if isinstance(p, str) and (Path(p) / ".beads").is_dir()]


def owner_repo(c, repos=None):
    """The repo whose bead list takes this cause: task-loop, delegate, or the project most of its runs ran in."""
    repos = registered() if repos is None else repos
    want = OWNERS.get(c["cause"])
    if want:
        for p in repos:
            if Path(p).name == want:
                return p
    mine = [r for r, _ in c["repos"].most_common() if r in repos]
    return mine[0] if mine else (c["repos"].most_common(1)[0][0] if c["repos"] else "")


def bd_json(args, repo):
    r = tl.bd(*args, cwd=repo)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout or "null")
    except ValueError:
        return None


def known_bead(c, repo, state):
    """-> (bead id, why) of the bead that already carries this cause: the state file's, else an open bead of the repo with a like
    title; ('', '') when none."""
    for e in state.get("filed", []):
        if e.get("cause") == c["cause"] and e.get("repo") == repo and (set(e.get("files") or []) & set(c["files"])
                                                                         or jaccard(set(e.get("tokens") or []), c["tokens"]) >= SIMILAR):
            return e["bead"], "filed"
    rows = bd_json(["list", "--status=open", "--json", "--limit", "0"], repo) or []
    ct = tokens(c["title"])
    for b in rows if isinstance(rows, list) else []:
        if jaccard(tokens(b.get("title") or ""), ct) >= TITLE_SIMILAR:
            return b.get("id") or "", "open"
    return "", ""


def is_closed(bead, repo):
    d = bd_json(["show", bead, "--json"], repo)
    row = d[0] if isinstance(d, list) and d else d
    return isinstance(row, dict) and row.get("status") == "closed"


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


def file_cluster(c, state, dry=False, repos=None):
    """File or update the bead for one recurring cause. -> {action: filed|commented|skipped|none, bead, repo, cause, runs}."""
    repo = owner_repo(c, repos)
    res = {"cause": c["cause"], "title": c["title"], "repo": repo, "runs": c["runs"], "bead": "", "action": "none"}
    if not repo:
        return res
    bead, why = known_bead(c, repo, state)
    if bead and why == "filed" and is_closed(bead, repo):
        old, bead = bead, ""
    else:
        old = ""
    entry = next((e for e in state.get("filed", []) if e.get("bead") == bead and e.get("repo") == repo), None)
    if bead:
        new = [r for r in c["runs"] if r not in (entry or {}).get("runs", [])]
        res.update(bead=bead, action="skipped")
        if new and not dry:
            tl.bd("comments", "add", bead, "Reflect digest: the cause recurred in %d more run(s): %s\n%s" % (
                len(new), ", ".join(new), "\n".join(evidence_lines(dict(c, items=[i for i in c["items"] if i["run"] in new])))), cwd=repo)
            res["action"] = "commented"
        elif new:
            res["action"] = "commented"
        if entry is not None and new and not dry:
            entry["runs"] = sorted(set(entry["runs"]) | set(new))
        return res
    title = "Reflect: %s: %s" % (c["cause"], c["title"])[:140]
    res["action"] = "filed"
    if dry:
        return res
    r = tl.bd("create", "--title", title, "--type", "task", "--priority", "3", "--labels", "reflect,cause-%s" % c["cause"],
              "--description", description(c, old), "--acceptance", acceptance(c), "--silent", cwd=repo)
    new_id = (r.stdout or "").strip().splitlines()[-1].strip() if r.returncode == 0 and (r.stdout or "").strip() else ""
    if not new_id:
        res["action"] = "failed"
        return res
    res["bead"] = new_id
    state.setdefault("filed", []).append({"cause": c["cause"], "repo": repo, "bead": new_id, "tokens": sorted(c["tokens"]),
                                          "files": c["files"], "runs": c["runs"], "at": time.time()})
    return res


def digest(since, until, dry=False, traces=None, repos=None):
    """-> {window, clusters: [...], actions: [...]}. Files and updates beads unless dry."""
    cs = cluster(items(since, until, traces))
    out = {"since": since, "until": until, "items": sum(len(c["items"]) for c in cs), "clusters": [], "actions": []}
    state = read_state()
    for c in cs:
        row = {"cause": c["cause"], "title": c["title"], "runs": len(c["runs"]), "run_ids": c["runs"], "beads": c["beads"],
               "files": c["files"], "recurring": len(c["runs"]) >= MIN_RUNS}
        out["clusters"].append(row)
        if row["recurring"]:
            a = file_cluster(c, state, dry, repos)
            out["actions"].append(a)
            row["bead"], row["repo"] = a["bead"], a["repo"]
    if not dry and out["actions"]:
        write_state(state)
    return out


def view(hours=24, now=None):
    """For the dashboard: the clusters of the last `hours`, each with the bead filed for it (state file), nothing written."""
    now = now or time.time()
    cs = cluster(items(now - hours * 3600, now))
    st = read_state()
    out = []
    for c in cs:
        e = next((e for e in st.get("filed", []) if e.get("cause") == c["cause"] and (set(e.get("files") or []) & set(c["files"])
                                                                                       or jaccard(set(e.get("tokens") or []), c["tokens"]) >= SIMILAR)), None)
        out.append({"cause": c["cause"], "title": c["title"], "runs": len(c["runs"]), "run_ids": c["runs"][:12], "beads": c["beads"][:8],
                    "files": c["files"], "recurring": len(c["runs"]) >= MIN_RUNS, "bead": (e or {}).get("bead", ""),
                    "repo": (e or {}).get("repo", ""), "last": c["last"]})
    return {"hours": hours, "clusters": out}


def due(now=None):
    return (now or time.time()) - float(read_state().get("tried") or 0) >= DAY


def maybe_run(now=None):
    """The loop's call: once a day a detached `tl reflect digest` (it asks bd about every open bead of the target repos: a loop
    pass never waits for it). -> 'started' or ''."""
    if not due(now):
        return ""
    try:
        with tl.os_lock(tl.config_dir() / "locks" / "reflect-digest.lock", "pid %d" % os.getpid()):
            if not due(now):
                return ""
            st = read_state()
            st["tried"] = now or time.time()
            write_state(st)
        subprocess.Popen([sys.executable, str(Path(__file__).resolve().with_name("tl.py")), "reflect", "digest"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=(os.name != "nt"))
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
    d = digest(at(a.since, now - DAY), at(a.until, now), dry=a.dry_run)
    if a.json:
        print(json.dumps(d, indent=1, default=str))
        return 0
    print("%d bad items in %d causes, %d recurring%s" % (d["items"], len(d["clusters"]), len(d["actions"]), " (dry run)" if a.dry_run else ""))
    for x in d["actions"]:
        print("  %-9s [%s] %s -> %s %s (%d runs)" % (x["action"], x["cause"], x["title"][:60], Path(x["repo"]).name or "?",
                                                      x["bead"] or "-", len(x["runs"])))
    return 0
