#!/usr/bin/env python3
"""tl.py: the task-loop helper. Python 3.8+, standard library only; macOS, Linux (also in Docker), Windows.

  tl.py actor                                   the --actor name this session uses for every bd call
  tl.py bd ARGS...                              run bd with this session's actor (in the current directory)
  tl.py register [DIR]                          add a repo to the dashboard (default: current directory)
  tl.py claim ID [--worktree DIR]               claim a bead, record it (bd provenance + local event)
  tl.py heartbeat ID                            keep the claim alive (run in a background loop)
  tl.py stage ID TEXT                           record what the task is doing now (shown on the dashboard)
  tl.py worker ID --kind K --ref R [--title T]  record a worker run (codex | claude-p | subagent | other)
  tl.py land ID --sha SHA [--worktree DIR]      record the landing (before close)
  tl.py close ID [--reason R]                   close the bead, record it
  tl.py block ID --why TEXT                     block the bead with a question, record it
  tl.py slot list|take|release|reset|setup ...  slots (see SKILL.md, Slots)
  tl.py slot hold S --why TEXT [--for MIN]      keep the loop and run-task off a slot (a person, screenshots)
  tl.py worktree start|sunset ...               one worktree per loop session when slots are off
  tl.py usage '<plan.windows JSON>'             feed get_usage to delegate (every 20 min while an engine runs)
  tl.py trace [ID] [--last N] [--json]          engine runs and every worker session of each (for reflection)
  tl.py run-task ID [--worktree DIR] [--slot S] [--dry-run] [--fresh]
                                                one bead through the engine (engine.py), no judgement here
  tl.py next [--repo DIR] [--json]              the bead the loop would take next and why (claims nothing)
  tl.py loop [--repo DIR] [--max-beads N] [--until HH:MM] [--wait-slot-min M] [--wait-drained]
                                                run ready beads one after another, each in any free slot
  tl.py loop status [--repo DIR] [--last N]     the running loop and its last beads
  tl.py stop [--repo DIR] [--now]               stop the loop after its current bead, or now (SIGTERM)
  tl.py dash ensure|stop|status|url             the dashboard server (one per machine)
  tl.py hook session-start                      SessionStart hook: index session id -> transcript path

State: ~/.config/task-loop (%APPDATA%\\task-loop on Windows): repos.json, events.jsonl, sessions/, dash.*.
"""

import argparse
import hashlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DASH = HERE / "dash" / "server.py"
PORT = int(os.environ.get("TASK_LOOP_DASH_PORT", "7878"))
SOURCE = "task-loop"
RETAIN_DAYS = 7


# ---- paths and identity -------------------------------------------------------------------------------------------

def config_dir():
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "task-loop"
    d.mkdir(parents=True, exist_ok=True)
    return d


def transcript_of(family, ref):
    """Where a worker session's transcript lives on this machine: Codex rollouts and Claude projects, by session id."""
    if not ref:
        return ""
    home = Path.home()
    pats = ([home / ".codex" / "sessions", "*%s*.jsonl" % ref] if family == "openai" else
            [home / ".claude" / "projects", "*/%s.jsonl" % ref])
    hits = sorted(pats[0].glob("**/" + pats[1])) if pats[0].is_dir() else []
    return str(hits[-1]) if hits else ""


def cmd_trace(a):
    path = config_dir() / "traces.jsonl"
    runs = []
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not a.id or r.get("bead") == a.id:
                runs.append(r)
    if a.last:
        runs = runs[-a.last:]
    for r in runs:
        for s in r.get("sessions", []):
            s["transcript"] = s.get("transcript") or transcript_of(s.get("family"), s.get("ref"))
    if a.json:
        print(json.dumps(runs, indent=1, ensure_ascii=False))
        return 0
    if not runs:
        print("no traces%s yet (%s)" % (" for " + a.id if a.id else "", path))
        return 0
    for r in runs:
        mins = (r.get("ended", 0) - r.get("started", 0)) / 60
        st = r.get("stats") or {}
        tok = ("  tokens in %.2fM (%.2fM cached) out %dk" % (st["tokens_in"] / 1e6, st.get("tokens_cached", 0) / 1e6,
                                                            st.get("tokens_out", 0) // 1000)) if st.get("tokens_in") else ""
        print("%s  %s  %s  %d min  $%.2f%s  coordinator=%s" % (r.get("run"), r.get("bead"), r.get("outcome"), mins,
                                                               r.get("cost") or 0, tok, r.get("coordinator_session") or "-"))
        for s in r.get("sessions", []):
            print("  %-7s %-8s %-6s %-9s %s  %s" % (s.get("node"), s.get("role"), s.get("family") or "?", s.get("status"),
                                                   s.get("ref") or "-", s.get("transcript") or ""))
    return 0


def session_id():
    """The session this process acts for: a Claude session, or the engine's own id when nobody drives it."""
    return (os.environ.get("TASK_LOOP_SESSION") or os.environ.get("CLAUDE_CODE_SESSION_ID")
            or os.environ.get("CLAUDE_SESSION_ID") or "")


def git(*args, cwd=None):
    r = subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout.strip() if r.returncode == 0 else ""


def repo_root(cwd=None):
    """The main checkout of the repo (shared by all its worktrees), so every worktree maps to one repo."""
    common = git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=cwd)
    if common:
        p = Path(common)
        return str(p.parent if p.name == ".git" else p)
    return git("rev-parse", "--show-toplevel", cwd=cwd) or str(Path(cwd or os.getcwd()).resolve())


def actor():
    """One name per session: two sessions with one actor both 'win' a claim (bd lets the same actor re-claim)."""
    if os.environ.get("TASK_LOOP_ACTOR"):
        return os.environ["TASK_LOOP_ACTOR"]
    sid = session_id()
    if sid:
        return "tl-" + sid[:8]
    if os.environ.get("CLAUDE_PID"):  # older Claude Code: one name per session process, never per folder
        return "tl-%s-%s" % (socket.gethostname().split(".")[0].lower(), os.environ["CLAUDE_PID"])
    top = git("rev-parse", "--show-toplevel")
    return "tl-" + (Path(top).name if top else socket.gethostname())


def bd(*args, cwd=None, check=False):
    exe = shutil.which("bd")
    if not exe:
        sys.exit("tl: bd is not on PATH")
    r = subprocess.run([exe, "--actor", actor()] + list(args), cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        sys.stderr.write(r.stderr)
        sys.exit(r.returncode)
    return r


# ---- records ------------------------------------------------------------------------------------------------------

def now():
    return time.time()


def event(kind, bead="", **fields):
    """One line per event in events.jsonl: the dashboard's fast local index (transcripts are local too)."""
    rec = {"t": now(), "kind": kind, "bead": bead, "session": session_id(), "actor": actor(),
           "repo": fields.pop("repo", None) or repo_root(), "host": socket.gethostname()}
    rec.update({k: v for k, v in fields.items() if v is not None})
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    with open(config_dir() / "events.jsonl", "a", encoding="utf-8") as f:
        f.write(line)
    register_repo(rec["repo"])
    return rec


def provenance(bead, kind, ref, ref_kind, payload=None, cwd=None):
    """The shared record in bd (append-only, idempotent); a bd without provenance is not fatal."""
    args = ["provenance", "record", "--issue", bead, "--kind", kind, "--source", SOURCE]
    if ref:
        args += ["--ref", ref, "--ref-kind", ref_kind]
    else:
        args += ["--at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())]
    if payload:
        args += ["--payload", json.dumps(payload)]
    r = bd(*args, cwd=cwd)
    if r.returncode != 0:
        sys.stderr.write("tl: provenance not recorded: " + (r.stderr.strip().splitlines() or ["?"])[-1] + "\n")


def register_repo(path):
    f = config_dir() / "repos.json"
    try:
        repos = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        repos = {}
    if path and path not in repos:
        repos[path] = {"added": now()}
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(repos, indent=1), encoding="utf-8")
        os.replace(tmp, f)


def cmd_register(a):
    try:
        valid = git("rev-parse", "--is-inside-work-tree", cwd=a.directory) == "true"
        path = repo_root(a.directory) if valid else None
    except (OSError, ValueError):
        path = None
    if path is None:
        print("tl: not a Git working directory: " + repr(a.directory), file=sys.stderr)
        return 1
    register_repo(path)
    print("REGISTERED " + path)
    return 0


def prune_events():
    f = config_dir() / "events.jsonl"
    if not f.exists() or f.stat().st_size < 2_000_000:
        return
    cut = now() - RETAIN_DAYS * 86400
    keep = []
    for ln in f.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            if json.loads(ln).get("t", 0) >= cut:
                keep.append(ln)
        except ValueError:
            pass
    tmp = f.with_suffix(".tmp")
    tmp.write_text("\n".join(keep) + ("\n" if keep else ""), encoding="utf-8")
    os.replace(tmp, f)


# ---- bead lifecycle -----------------------------------------------------------------------------------------------

def show(bead, cwd=None):
    r = bd("show", bead, "--json", cwd=cwd)
    try:
        d = json.loads(r.stdout)
        return d[0] if isinstance(d, list) else d
    except ValueError:
        return {}


def comments(bead, cwd=None):
    """A bead's comments, oldest first: [{author, text, created_at}]."""
    r = bd("comments", bead, "--json", cwd=cwd)
    try:
        d = json.loads(r.stdout)
        return d if isinstance(d, list) else []
    except ValueError:
        return []


def cmd_claim(a):
    r = bd("update", a.id, "--claim")
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        print("TAKEN")
        return 1
    b = show(a.id)
    if b.get("assignee") not in (None, "", actor()):
        print("TAKEN by " + str(b.get("assignee")))
        return 1
    wt = str(Path(a.worktree).resolve()) if a.worktree else git("rev-parse", "--show-toplevel")
    branch = (b.get("metadata") or {}).get("branch") or "task/" + a.id
    bd("update", a.id, "--set-metadata", "branch=" + branch)
    if a.slot:
        bd("update", a.id, "--set-metadata", "slot=" + a.slot)
    event("claim", a.id, worktree=wt, branch=branch, title=b.get("title"), slot=a.slot)
    provenance(a.id, "claim", session_id() or actor(), "transcript" if session_id() else "work-id",
               {"worktree": wt, "actor": actor(), "slot": a.slot})
    print("CLAIMED " + a.id + " branch=" + branch)
    return 0


def session_alive():
    pid = os.environ.get("CLAUDE_PID")
    if not pid or os.name == "nt":  # on Windows os.kill(pid, 0) terminates the process instead of probing it
        return True
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except (OSError, ValueError):
        return False


def cmd_heartbeat(a):
    """Keep claims alive. --loop: every 60 s until a heartbeat fails, the session's process is gone, or 12 h pass,
    so a dead session's leases lapse and `bd reclaim` frees them."""
    end = now() + 12 * 3600
    while True:
        for i in a.ids:
            r = bd("heartbeat", i)
            if r.returncode != 0:
                sys.stderr.write(r.stderr)
                return r.returncode
        if not a.loop or now() > end or not session_alive():
            return 0
        time.sleep(60)


def cmd_stage(a):
    event("stage", a.id, text=a.text)
    return 0


def cmd_worker(a):
    event("worker", a.id, worker_kind=a.kind, ref=a.ref, title=a.title, cwd=a.cwd or os.getcwd())
    provenance(a.id, "handoff", a.ref, "work-id", {"kind": a.kind, "title": a.title})
    return 0


def cmd_land(a):
    sha = git("rev-parse", "--verify", "-q", a.sha + "^{commit}", cwd=a.worktree) or a.sha
    event("land", a.id, sha=sha)
    provenance(a.id, "land", sha, "git-sha")
    return 0


def cmd_close(a):
    r = bd("close", a.id, "--reason", a.reason or "done")
    sys.stderr.write(r.stderr)
    if r.returncode == 0:
        event("close", a.id, reason=a.reason)
        prune_events()
    return r.returncode


def cmd_block(a):
    r = bd("update", a.id, "--status", "blocked")
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        return r.returncode
    bd("comments", "add", a.id, "Blocked: " + a.why)
    event("block", a.id, why=a.why)
    provenance(a.id, "suspend", session_id() or actor(), "transcript", {"why": a.why})
    return 0


# ---- slots --------------------------------------------------------------------------------------------------------
# A slot is a persistent worktree, set up once and reused task after task. Each slot is a bead labelled `slot`
# (never picked as work); holding a slot = claiming its bead, so the lease, heartbeat and reclaim come from bd.

def profile_slots(repo):
    """The `slots` block of the repo's loop profile, as JSON in .task-loop.json (generic, read by tl.py)."""
    f = Path(repo) / ".task-loop.json"
    try:
        return json.loads(f.read_text(encoding="utf-8")).get("slots") or {}
    except (OSError, ValueError):
        return {}


def slot_dir(repo, name, cfg):
    root = cfg.get("dir") or os.path.join(repo, ".slots")
    return str(Path(root if os.path.isabs(root) else os.path.join(repo, root)) / name)


HOST = socket.gethostname().split(".")[0].lower()


def slot_beads(repo):
    """This machine's slot beads (title `slot <host> <name>`): a lease is local to one machine's bd."""
    r = bd("list", "--json", "--all", "-n", "0", "--label", "slot", cwd=repo)
    try:
        beads = json.loads(r.stdout)
    except ValueError:
        return []
    mine = [b for b in beads if b.get("status") != "closed" and b.get("title", "").split()[1:2] == [HOST]]
    return sorted(mine, key=lambda b: b["title"])


def cmd_slot(a):
    repo = repo_root()
    cfg = profile_slots(repo)
    if a.op == "list":  # NAME BEAD STATUS HOLDER WHY ENGINE DIR
        free_expired(repo)
        for b in slot_beads(repo):
            name = b["title"].split()[-1]
            m, hold, d = b.get("metadata") or {}, slot_hold(b), slot_dir(repo, name, cfg)
            held = b.get("status") == "in_progress" or hold
            holder = (m.get("held_by") or b.get("assignee") or "?") if held else "-"
            why = ("%s (hold until %s)" % (hold["why"], hold["until"]) if hold else
                   "%s since %s" % (m.get("held_why") or "?", m.get("held_since") or "?") if held else "-")
            print("\t".join([name, b["id"], b.get("status", ""), holder, why, engine_busy(d) or "-", d]))
        return 0
    if a.op == "hold":  # a slot for something that is no bead (screenshots, a person): the loop and run-task keep off
        if not a.name or not a.why:
            sys.exit("tl: tl slot hold NAME --why TEXT [--for MIN]")
        free_expired(repo)
        b = slot_bead(repo, a.name)
        if not b:
            sys.exit("tl: no slot " + a.name)
        hold = slot_hold(b)
        busy = (engine_busy(slot_dir(repo, a.name, cfg)) or
                ("held by %s until %s: %s" % (hold["by"], hold["until"], hold["why"]) if hold and hold["by"] != actor()
                 else "" if hold or b.get("status") == "open" else "held by %s" % held_by(b)))
        if not busy and b.get("status") == "open" and not claim_slot(repo, b["id"]):
            busy = "claimed by another session just now"
        if busy:  # renewing one's own hold is fine; anything else in use is never held
            print("BUSY: slot %s %s" % (a.name, busy))
            return 1
        until = now() + float(a.for_min if a.for_min is not None else 60) * 60
        mark_held(repo, b["id"], a.why, until)
        event("slot-hold", "", slot=a.name, slot_bead=b["id"], why=a.why, until=until, repo=repo)
        print("HELD %s until %s: %s" % (a.name, stamp(until), a.why))
        return 0
    if a.op == "init":  # once per repo: the slot beads and their worktrees
        n = int(a.n or cfg.get("count") or 0)
        if n < 1:
            sys.exit("tl: slots.count is not set in .task-loop.json")
        have = {b["title"].split()[-1] for b in slot_beads(repo)}
        for i in range(1, n + 1):
            name = "s%d" % i
            if name not in have:
                bd("create", "slot %s %s" % (HOST, name), "--type", "chore", "--labels", "slot", "--priority", "4",
                   "--description", "Slot worktree " + name + " for task-loop. Claimed while a session uses it; never work.",
                   cwd=repo, check=True)
            d = slot_dir(repo, name, cfg)
            exclude_local(repo, ".slots/", ".task/")
            if not os.path.isdir(d):
                git("fetch", "origin", cwd=repo)
                r = subprocess.run(["git", "-C", repo, "worktree", "add", "--detach", d, "origin/main"],
                                   capture_output=True, text=True, encoding="utf-8", errors="replace")
                if r.returncode != 0:
                    sys.exit(r.stderr)
            print(name + "\t" + d)
        return 0
    if a.op == "take":  # claim the first free slot; prints NAME DIR BEAD
        got = take_slot(repo, cfg, "tl slot take")
        print("\t".join(got) if got else "NONE")
        return 0 if got else 1
    if a.op == "release":
        d = slot_dir(repo, a.name, cfg) if a.name else ""
        busy = engine_busy(d) if d else ""
        if busy and not a.force:
            print("BUSY: slot %s: %s; it frees itself when that run ends (--force: release and drop the lock)"
                  % (a.name, busy))
            return 1
        if busy:
            drop_engine_lock(d)
        if not release_slot(repo, a.name):
            sys.exit("tl: no slot " + str(a.name))
        return 0
    if a.op == "reset":  # per task: a clean tree on a fresh task branch; ignored setup output stays
        d = slot_dir(repo, a.name, cfg)
        busy = engine_busy(d)  # never commit or switch branches under a running engine (2026-10-21, lifesim-5ar.7)
        hold = slot_hold(slot_bead(repo, a.name) or {})
        if not busy and hold:
            busy = "held by %s until %s: %s" % (hold["by"], hold["until"], hold["why"])
        if busy and not a.force:
            print("BUSY: slot %s: %s; not reset (--force: reset anyway and drop the lock)" % (a.name, busy))
            return 4
        if busy:
            drop_engine_lock(d)
            print("FORCED: slot %s reset over: %s" % (a.name, busy))
        gd = git("rev-parse", "--git-dir", cwd=d)
        if gd and any(os.path.isdir(os.path.join(d, gd, x)) for x in ("rebase-merge", "rebase-apply")):
            git("rebase", "--abort", cwd=d)
        if git("status", "--porcelain", cwd=d):  # a dead session's work: commit it where it was, never wipe it
            br = git("symbolic-ref", "--short", "-q", "HEAD", cwd=d)
            if not br:
                br = "wip/%s/%d" % (a.name, int(now()))
                git("checkout", "-b", br, cwd=d)
            git("add", "-A", cwd=d)
            r = subprocess.run(["git", "-C", d, "commit", "-qm", "wip: left in slot %s" % a.name],
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            if r.returncode != 0:
                print("DIRTY: could not commit the leftover work on %s\n%s" % (br, r.stderr))
                return 3
            print("WIP committed on " + br)
        git("fetch", "origin", cwd=d)
        base = cfg.get("base") or "origin/main"
        if a.bead and git("rev-parse", "--verify", "-q", "refs/heads/task/" + a.bead, cwd=d):
            # the bead's branch holds its earlier runs' work: check it out as it is, never reset it to base (a forced
            # reset here wiped lifesim-r32's reviewed work on 2026-10-19; the engine rebases at land)
            r = subprocess.run(["git", "-C", d, "checkout", "task/" + a.bead], capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
        elif a.bead:
            r = subprocess.run(["git", "-C", d, "checkout", "-b", "task/" + a.bead, base], capture_output=True, text=True, encoding="utf-8", errors="replace")
        else:
            r = subprocess.run(["git", "-C", d, "checkout", "--detach", base], capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            sys.stderr.write(r.stderr)
            return r.returncode
        subprocess.run(["git", "-C", d, "clean", "-fdq"] + sum((["-e", k] for k in cfg.get("keep", [])), []))
        return cmd_slot_setup(repo, a.name, cfg, d)
    if a.op == "setup":
        return cmd_slot_setup(repo, a.name, cfg, slot_dir(repo, a.name, cfg), force=True)
    return 2


def take_slot(repo, cfg, why="tl loop"):
    """(name, dir, slot bead) of the first free slot this session could claim, or None. Free: its bead open, no hold,
    and no live engine or worker in its worktree (a run started without the slot bead, an older engine)."""
    free_expired(repo)
    for b in slot_beads(repo):
        name = b["title"].split()[-1]
        d = slot_dir(repo, name, cfg)
        if b.get("status") != "open" or slot_hold(b) or engine_busy(d) or not claim_slot(repo, b["id"]):
            continue
        mark_held(repo, b["id"], why)
        event("slot-take", "", slot=name, slot_bead=b["id"], worktree=d, repo=repo)
        return name, d, b["id"]
    return None


def take_named_slot(repo, name, cfg, why):
    """(slot bead, "") when this session now holds slot `name`, or (None, why not): `slot S held by X since T`. A held
    slot bead is refused even when this session's actor holds it (a hand run from the session that started the loop
    shares its actor, and bd lets an actor re-claim its own bead); a hold too, its holder's own included."""
    free_expired(repo)
    b = slot_bead(repo, name)
    if not b:
        return None, "no slot %s on %s (tl slot list)" % (name, HOST)
    hold = slot_hold(b)
    if hold:
        return None, "slot %s held by %s since %s until %s: %s (tl slot release %s ends it)" % (
            name, hold["by"], hold["since"], hold["until"], hold["why"], name)
    if b.get("status") != "open":
        return None, "slot %s held by %s" % (name, held_by(b))
    busy = engine_busy(slot_dir(repo, name, cfg))
    if busy:
        return None, "slot %s busy: %s" % (name, busy)
    if not claim_slot(repo, b["id"]):
        return None, "slot %s held by %s" % (name, held_by(show(b["id"], cwd=repo) or b))
    mark_held(repo, b["id"], why)
    event("slot-take", "", slot=name, slot_bead=b["id"], worktree=slot_dir(repo, name, cfg), repo=repo)
    return b["id"], ""


def slot_of(repo, wt):
    """The slot whose worktree `wt` is, or ""."""
    cfg, here = profile_slots(repo), Path(wt).resolve()
    for b in slot_beads(repo):
        name = b["title"].split()[-1]
        if Path(slot_dir(repo, name, cfg)).resolve() == here:
            return name
    return ""


def claim_slot(repo, bead_id):
    """True when this session won the slot bead's claim."""
    return (bd("update", bead_id, "--claim", cwd=repo).returncode == 0
            and (show(bead_id, cwd=repo).get("assignee") or actor()) == actor())


def held_by(b):
    m = b.get("metadata") or {}
    return "%s since %s (%s)" % (m.get("held_by") or b.get("assignee") or "?", m.get("held_since") or "?",
                                 m.get("held_why") or "no reason")


def release_slot(repo, name):
    b = slot_bead(repo, name)
    if not b:
        return False
    bd("unclaim", b["id"], cwd=repo)
    bd("update", b["id"], *sum((["--unset-metadata", k] for k in HELD_KEYS), []), cwd=repo)
    event("slot-release", "", slot=name, slot_bead=b["id"], repo=repo)
    return True


def free_expired(repo):
    """An expired hold gives its slot bead back (the holder's claim with it), so the slot is free at once."""
    for b in slot_beads(repo):
        m = b.get("metadata") or {}
        if hold_until(b) and not slot_hold(b):
            if b.get("status") == "in_progress" and (b.get("assignee") or "") in ("", m.get("held_by")):
                bd("unclaim", b["id"], cwd=repo)
            bd("update", b["id"], *sum((["--unset-metadata", k] for k in HELD_KEYS), []), cwd=repo)
            event("slot-hold-expired", "", slot=b["title"].split()[-1], slot_bead=b["id"], repo=repo)


def slot_bead(repo, name):
    return next((x for x in slot_beads(repo) if x["title"].split()[-1] == name), None)


HELD_KEYS = ("held_by", "held_since", "held_why", "hold_until")


def stamp(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))


def mark_held(repo, bead_id, why, until=0):
    """Who holds a slot, since when and why, on its bead: tl slot list and a refused run-task read them. `until`: a hold
    (tl slot hold), which outlives the bead's lease."""
    sets = ["held_by=" + actor(), "held_since=" + stamp(now()), "held_why=" + why]
    args = sum((["--set-metadata", x] for x in sets), [])
    args += ["--set-metadata", "hold_until=%d" % until] if until else ["--unset-metadata", "hold_until"]
    bd("update", bead_id, *args, cwd=repo)


def hold_until(b):
    try:
        return float(((b or {}).get("metadata") or {}).get("hold_until") or 0)
    except (TypeError, ValueError):
        return 0.0


def slot_hold(b):
    """{by, since, why, until} of a slot's hold that has not expired, else None."""
    until, m = hold_until(b), (b or {}).get("metadata") or {}
    if until <= now():
        return None
    return {"by": m.get("held_by") or "?", "since": m.get("held_since") or "?", "why": m.get("held_why") or "",
            "until": stamp(until)}


# ---- the engine lock: a running engine in a worktree ------------------------------------------------------------------
# run-task writes <worktree>/.task/engine.lock {pid, start, bead, slot, slot_bead, by, route: [pid, start],
# workers: [[pid, start]]}; the loop writes one (by "loop") from its slot take until its run-task replaces it. The loop,
# tl slot reset/release and another run-task keep off a worktree whose lock names a live process, whatever the slot
# bead says. A process is the one in the lock only while its start time matches (pid reuse) and it is no zombie.

def engine_lock_path(wt):
    return Path(wt) / ".task" / "engine.lock"


def read_engine_lock(wt):
    try:
        lock = json.loads(engine_lock_path(wt).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return lock if isinstance(lock, dict) else {}


def write_engine_lock(wt, data):
    f = engine_lock_path(wt)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".%d.tmp" % os.getpid())
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, f)


def drop_engine_lock(wt, pid=None):
    """Remove the lock; with `pid`, only when that process wrote it."""
    if pid is not None and read_engine_lock(wt).get("pid") != pid:
        return
    try:
        engine_lock_path(wt).unlink()
    except OSError:
        pass


def loop_lock(wt, slot, slot_bead):
    """The loop's lock from its slot take to its run-task's own: no hand run gets in during the slot reset."""
    write_engine_lock(wt, {"pid": os.getpid(), "start": proc_start(os.getpid()), "bead": "", "slot": slot or "",
                           "slot_bead": slot_bead or "", "by": "loop", "started": now()})


def engine_busy(wt, handoff=False):
    """What runs in this worktree, with the lock's path ("engine pid N runs BEAD since T; lock P"), or "". handoff: a
    run-task the loop started takes over its parent loop's lock for the same slot bead."""
    lock = read_engine_lock(wt)
    if not lock:
        return ""
    mine = {os.getpid()}
    if handoff and lock.get("by") == "loop" and lock.get("slot_bead", "") == os.environ.get("TASK_LOOP_SLOT_BEAD", ""):
        mine.add(os.getppid())
    where = "; lock %s" % engine_lock_path(wt)
    pid = lock.get("pid")
    if pid and int(pid) not in mine and proc_alive(pid, lock.get("start") or ""):
        return "%s pid %s runs %s since %s%s" % ("loop" if lock.get("by") == "loop" else "engine", pid,
                                                 lock.get("bead") or "a slot reset", stamp(float(lock.get("started") or 0)),
                                                 where)
    procs = [lock.get("route")] + list(lock.get("workers") or [])
    left = []
    for w in procs:
        p, st = (w[0], w[1]) if isinstance(w, (list, tuple)) else (w, "")
        if p and int(p) not in mine and proc_alive(p, st):
            left.append(str(p))
    if left:
        return "worker pid %s of %s outlived its engine%s" % (",".join(left), lock.get("bead") or "?", where)
    return ""


# ---- processes: alive, start time, zombies (POSIX via ps, LC_ALL=C so the start time reads the same everywhere) ------

def ps(*args):
    try:
        r = subprocess.run(["ps"] + list(args), capture_output=True, text=True, timeout=10,
                           env=dict(os.environ, LC_ALL="C", LANG="C"))
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout


def proc_start(pid):
    """The process's start time as text, "" when unknown (Windows: not read; pid reuse there is not detected)."""
    if os.name == "nt" or not pid:
        return ""
    out = ps("-o", "lstart=", "-p", str(int(pid)))
    if out is None:  # no ps (a slim container): Linux's /proc has it
        try:
            return Path("/proc/%d/stat" % int(pid)).read_text().rsplit(")", 1)[1].split()[19]
        except (OSError, IndexError, ValueError):
            return ""
    return " ".join(out.split())


def zombie(pid):
    if os.name == "nt":
        return False
    out = ps("-o", "stat=", "-p", str(int(pid)))
    if out is None:
        try:
            return Path("/proc/%d/stat" % int(pid)).read_text().rsplit(")", 1)[1].split()[0] == "Z"
        except (OSError, IndexError, ValueError):
            return False
    return out.strip().startswith("Z")


def proc_alive(pid, start=""):
    """The process `pid` lives, is no zombie, and (when `start` is known) is the one that started then."""
    if not pid_alive(pid) or zombie(pid):
        return False
    if start:
        now_start = proc_start(pid)
        if now_start and now_start != start:
            return False
    return True


def proc_table():
    """{pid: (ppid, pgid, start)} of every process (POSIX), {} when ps is missing."""
    out = ps("-A", "-o", "pid=,ppid=,pgid=,lstart=")
    table = {}
    for ln in (out or "").splitlines():
        f = ln.split()
        if len(f) > 3 and all(x.isdigit() for x in f[:3]):
            table[int(f[0])] = (int(f[1]), int(f[2]), " ".join(f[3:]))
    return table


def pid_alive(pid):
    if not pid:
        return False
    if os.name == "nt":  # os.kill(pid, 0) terminates a process on Windows instead of probing it
        r = subprocess.run(["tasklist", "/FI", "PID eq %d" % int(pid), "/NH", "/FO", "CSV"], capture_output=True,
                           text=True)
        for ln in (r.stdout or "").splitlines():  # "image","PID",...: the PID column, never a substring (12 in 1234)
            cols = [c.strip().strip('"') for c in ln.split('","')]
            if len(cols) > 1 and cols[1] == str(int(pid)):
                return True
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except (OSError, ValueError):
        return False


def inputs_hash(d, patterns):
    h = hashlib.sha256()
    for pat in patterns:
        for p in sorted(Path(d).glob(pat)):
            if p.is_file():
                h.update(str(p.relative_to(d)).encode())
                h.update(p.read_bytes())
    return h.hexdigest()


def cmd_slot_setup(repo, name, cfg, d, force=False):
    """Run the profile's setup only when its inputs changed since the last setup in this slot."""
    cmd = cfg.get("setup")
    if not cmd:
        print("READY " + d)
        return 0
    digest = inputs_hash(d, cfg.get("setup_inputs", []))
    mark = config_dir() / "slots" / (hashlib.sha1(d.encode()).hexdigest()[:12] + ".setup")
    mark.parent.mkdir(exist_ok=True)
    if not force and cfg.get("setup_inputs") and mark.exists() and mark.read_text() == digest:
        print("READY " + d + " (setup unchanged)")
        return 0
    t = now()
    r = subprocess.run(cmd, shell=True, cwd=d)
    event("slot-setup", "", slot=name, worktree=d, exit=r.returncode, secs=round(now() - t), repo=repo)
    if r.returncode == 0:
        mark.write_text(digest)
        print("READY " + d)
    return r.returncode


# ---- one worktree per loop session (slots off) --------------------------------------------------------------------

def exclude_local(repo, *patterns):
    """Keep the loop's own folders out of `git add -A` in every repo, without touching its tracked .gitignore."""
    common = git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=repo)
    if not common:
        return
    f = Path(common) / "info" / "exclude"
    f.parent.mkdir(parents=True, exist_ok=True)
    have = f.read_text(encoding="utf-8") if f.exists() else ""
    add = [p for p in patterns if p not in have.split()]
    if add:
        with open(f, "a", encoding="utf-8") as fh:
            fh.write(("\n" if have and not have.endswith("\n") else "") + "\n".join(add) + "\n")


def cmd_worktree(a):
    repo = repo_root()
    root = Path(repo) / ".worktrees"
    if a.op == "start":
        print(start_worktree(repo))
        return 0
    if a.op == "sunset":  # remove loop worktrees whose session is gone; never a dirty one
        live = live_actors(repo)
        for d in sorted(root.glob("loop-*")):
            owner = "tl-" + d.name[5:]
            if owner == actor() and not a.self_too:
                continue
            if owner in live and owner != actor():
                continue
            if git("status", "--porcelain", cwd=str(d)):
                print("KEEP dirty " + str(d))
                continue
            subprocess.run(["git", "-C", repo, "worktree", "remove", str(d)], capture_output=True)
            event("worktree-sunset", "", worktree=str(d), repo=repo)
            print("REMOVED " + str(d))
        git("worktree", "prune", cwd=repo)
        return 0
    return 2


def start_worktree(repo):
    """This session's loop worktree, made once and reused for every task."""
    exclude_local(repo, ".worktrees/", ".task/")
    d = Path(repo) / ".worktrees" / ("loop-" + actor()[3:])
    if not d.exists():
        git("fetch", "origin", cwd=repo)
        r = subprocess.run(["git", "-C", repo, "worktree", "add", "--detach", str(d), "origin/main"],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            sys.exit(r.stderr)
    event("worktree-start", "", worktree=str(d), repo=repo)
    return str(d)


def live_actors(repo):
    """Actors holding a live lease on any bead: a session that heartbeats is alive."""
    r = bd("list", "--json", "--status", "in_progress", "-n", "0", cwd=repo)
    try:
        beads = json.loads(r.stdout)
    except ValueError:
        return set()
    t = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    return {b.get("assignee") for b in beads if (b.get("lease_expires_at") or "") >= t}


# ---- dashboard server ---------------------------------------------------------------------------------------------

def code_version():
    h = hashlib.sha256()
    for p in sorted((HERE / "dash").glob("*")):
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


def ping():
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/version" % PORT, timeout=1.5) as r:
            return json.loads(r.read())
    except Exception:
        return None


def stop_server():
    """Stop the server that answers on the port (its own pid, never a stale pidfile's)."""
    v = ping()
    if not v or not v.get("pid"):
        return
    try:
        os.kill(int(v["pid"]), signal.SIGTERM)
    except (OSError, ValueError):
        pass
    for _ in range(20):
        if not ping():
            return
        time.sleep(0.2)


def cmd_dash(a):
    if a.op == "stop":
        stop_server()
        return 0
    v = ping()
    if a.op == "status":
        print(json.dumps(v) if v else "DOWN")
        return 0 if v else 1
    if a.op == "url":
        print_urls(v)
        try:  # the links that may answer asks: open one on the phone once, the page keeps the token
            t = (config_dir() / "dash.token").read_text().strip()
        except OSError:
            t = ""
        for u in (v or {}).get("urls", []) if t else []:
            print("ANSWER LINK %s/?token=%s" % (u, t))
        return 0
    # ensure: running and current, else (re)start detached
    if v and v.get("version") == code_version():
        print_urls(v)
        return 0
    if v:
        stop_server()
    log = open(config_dir() / "dash.log", "ab")
    env = {k: val for k, val in os.environ.items()
           if not k.startswith(("CLAUDE_CODE_SESSION", "DELEGATE_", "CODEX_COMPANION"))}
    kw = {"stdin": subprocess.DEVNULL, "stdout": log, "stderr": log, "env": env, "cwd": str(config_dir()), "close_fds": True}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    subprocess.Popen([sys.executable, str(DASH), "--port", str(PORT)], **kw)
    for _ in range(40):
        v = ping()
        if v:
            print_urls(v)
            return 0
        time.sleep(0.25)
    print("tl: dashboard did not start; see " + str(config_dir() / "dash.log"))
    return 1


def print_urls(v):
    for u in (v or {}).get("urls", ["http://127.0.0.1:%d" % PORT]):
        print("DASHBOARD " + u)


# ---- hook ---------------------------------------------------------------------------------------------------------

def cmd_hook(a):
    """SessionStart hook: session id -> transcript path. Must never fail the session."""
    try:
        d = json.loads(sys.stdin.read() or "{}")
        sid = d.get("session_id")
        if sid:
            f = config_dir() / "sessions" / (sid + ".json")
            f.parent.mkdir(exist_ok=True)
            f.write_text(json.dumps({"session": sid, "transcript": d.get("transcript_path"), "cwd": d.get("cwd"),
                                     "source": d.get("source"), "t": now()}), encoding="utf-8")
    except Exception:
        pass
    try:  # a dashboard left running by an older plugin version restarts on this code (it ran 0.5.3 for days)
        v = ping()
        if v and v.get("version") != code_version():
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "dash", "ensure"], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=(os.name != "nt"))
    except Exception:
        pass
    return 0


# ---- main ---------------------------------------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(prog="tl.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("actor")
    p = sp.add_parser("register", help="add a repository to the dashboard")
    p.add_argument("directory", nargs="?", default=".", metavar="DIR",
                   help="Git working directory (default: current directory)")
    p = sp.add_parser("bd")
    p.add_argument("rest", nargs=argparse.REMAINDER)
    p = sp.add_parser("claim")
    p.add_argument("id")
    p.add_argument("--worktree")
    p.add_argument("--slot")
    p = sp.add_parser("heartbeat")
    p.add_argument("ids", nargs="+")
    p.add_argument("--loop", action="store_true")
    p = sp.add_parser("stage")
    p.add_argument("id")
    p.add_argument("text")
    p = sp.add_parser("worker")
    p.add_argument("id")
    p.add_argument("--kind", required=True, choices=["codex", "claude-p", "subagent", "other"])
    p.add_argument("--ref", required=True)
    p.add_argument("--title")
    p.add_argument("--cwd")
    p = sp.add_parser("land")
    p.add_argument("id")
    p.add_argument("--sha", required=True)
    p.add_argument("--worktree")
    p = sp.add_parser("close")
    p.add_argument("id")
    p.add_argument("--reason")
    p = sp.add_parser("block")
    p.add_argument("id")
    p.add_argument("--why", required=True)
    p = sp.add_parser("slot")
    p.add_argument("op", choices=["list", "init", "take", "release", "reset", "setup", "hold"])
    p.add_argument("name", nargs="?")
    p.add_argument("--bead")
    p.add_argument("--n")
    p.add_argument("--force", action="store_true")
    p.add_argument("--why", help="hold: what the slot is held for (shown by tl slot list)")
    p.add_argument("--for", dest="for_min", type=float, help="hold: minutes until it expires (default 60); hold again to renew")
    p = sp.add_parser("worktree")
    p.add_argument("op", choices=["start", "sunset"])
    p.add_argument("--self-too", action="store_true")
    p = sp.add_parser("dash")
    p.add_argument("op", choices=["ensure", "stop", "status", "url"])
    p = sp.add_parser("run-task")
    p.add_argument("id")
    p.add_argument("--worktree")
    p.add_argument("--slot")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--fresh", action="store_true", help="drop the bead's checkpoint: plan again from the start")
    p.add_argument("--quiet", action="store_true", help="only steps and ⚠ lines (default: verbose, for a watching coordinator)")
    p.add_argument("--outcome-file", help="also write the outcome (the last stdout line, JSON) to this file")
    p = sp.add_parser("usage", help="pass get_usage's plan.windows (JSON) to delegate, so headless Claude steps may run")
    p.add_argument("windows")
    p = sp.add_parser("trace", help="engine runs of a bead (or all) with every worker session and its transcript")
    p.add_argument("id", nargs="?", default="")
    p.add_argument("--last", type=int, default=0)
    p.add_argument("--json", action="store_true")
    p = sp.add_parser("next", help="the bead the loop would take next and why (claims nothing)")
    p.add_argument("--repo")
    p.add_argument("--json", action="store_true")
    p = sp.add_parser("loop", help="run ready beads one after another, each in any free slot (see SKILL.md, Loop)")
    p.add_argument("op", nargs="?", choices=["run", "status"], default="run")
    p.add_argument("--repo")
    p.add_argument("--max-beads", type=int, default=0)
    p.add_argument("--until", metavar="HH:MM", help="start no bead after this local time")
    p.add_argument("--wait-slot-min", type=float, default=30, help="say so this often while no slot is free")
    p.add_argument("--wait-drained", action="store_true", help="no ready bead: poll every 5 min instead of ending")
    p.add_argument("--last", type=int, default=10, help="status: how many finished beads to show")
    p = sp.add_parser("stop", help="stop the repo's loop after its current bead (--now: SIGTERM the bead's run)")
    p.add_argument("--repo")
    p.add_argument("--now", action="store_true")
    p = sp.add_parser("hook")
    p.add_argument("op", choices=["session-start"])
    a = ap.parse_args(argv)

    if a.cmd == "actor":
        print(actor())
        return 0
    if a.cmd == "run-task":
        import engine
        return engine.main(a)
    if a.cmd == "usage":
        import engine
        route = engine.find_route()
        if not route:
            print("no delegate installed: nothing to feed")
            return 0
        r = subprocess.run([sys.executable, route, "status", "--claude-usage", a.windows, "--json"], capture_output=True,
                           text=True, encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
        try:
            lane = json.loads(r.stdout)["lanes"]["CLAUDE_SUBSCRIPTION"]
            print("fed %s: Claude subscription 5h %s%%, week %s%%%s" % (route, lane.get("five"), lane.get("week"),
                                                                      ", OUT" if lane.get("out") else ""))
        except (ValueError, KeyError, TypeError):
            print("delegate did not take the reading (exit %d): %s" % (r.returncode, (r.stderr or r.stdout)[-400:]))
            return 1
        return 0
    if a.cmd in ("next", "loop", "stop"):
        import loop
        return {"next": loop.cmd_next, "loop": loop.cmd_loop, "stop": loop.cmd_stop}[a.cmd](a)
    if a.cmd == "trace":
        return cmd_trace(a)
    if a.cmd == "bd":
        r = subprocess.run([shutil.which("bd") or "bd", "--actor", actor()] + a.rest)
        return r.returncode
    return {"register": cmd_register, "claim": cmd_claim, "heartbeat": cmd_heartbeat, "stage": cmd_stage, "worker": cmd_worker,
            "land": cmd_land, "close": cmd_close, "block": cmd_block, "slot": cmd_slot, "worktree": cmd_worktree,
            "dash": cmd_dash, "hook": cmd_hook}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
