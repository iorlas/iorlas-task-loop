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
  tl.py land-lock [--repo DIR] [--wait-min N] -- CMD...
                                                run CMD under the repo's land lock (the engine's); exits with CMD's code, 75 on timeout
  tl.py close ID [--reason R]                   close the bead, record it
  tl.py block ID --why TEXT                     block the bead with a question, record it
  tl.py slot list|take|release|reset|setup ...  slots (see SKILL.md, Slots)
  tl.py slot hold S --why TEXT [--for MIN]      keep the loop and run-task off a slot (a person, screenshots)
  tl.py worktree start|sunset ...               one worktree per loop session when slots are off
  tl.py usage '<plan.windows JSON>'             feed get_usage to delegate (every 20 min while an engine runs)
  tl.py trace [ID] [--last N] [--json]          engine runs and every worker session of each (for reflection)
  tl.py run-task ID [--worktree DIR] [--slot S|any [--wait]] [--exclusive-area] [--dry-run] [--fresh]
                                                one bead through the engine (engine.py), no judgement here
  tl.py next [--repo DIR] [--json]              the bead the loop would take next and why (claims nothing)
  tl.py loop [--repo DIR] [--max-beads N] [--until HH:MM] [--wait-slot-min M] [--wait-drained] [--pin]
                                                run ready beads one after another, each in any free slot
  tl.py loop status [--repo DIR] [--last N]     the running loop and its last beads
  tl.py stop [--repo DIR] [--now]               stop the loop after its current bead, or now (SIGTERM)
  tl.py report [--repo DIR] [--since T] [--until T] [--json]
                                                the M2 scorecard of a window (see SKILL.md, Report)
  tl.py lost [--repo DIR] [--since T] [--json]  bead-branch commits that are not landed, reclaimed or pending
  tl.py dash ensure|stop|status|url             the dashboard server (one per machine)
  tl.py hook session-start                      SessionStart hook: index session id -> transcript path

State: ~/.config/task-loop (%APPDATA%\\task-loop on Windows): repos.json, events.jsonl, sessions/, dash.*.
"""

import argparse
import contextlib
import glob
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None

HERE = Path(__file__).resolve().parent
DASH = HERE / "dash" / "server.py"
PORT = int(os.environ.get("TASK_LOOP_DASH_PORT", "7878"))
SOURCE = "task-loop"
RETAIN_DAYS = 7


# ---- paths and identity -------------------------------------------------------------------------------------------

@contextlib.contextmanager
def os_lock(path, holder, waiting=None, timeout=None):
    """One holder at a time, across processes: an flock the OS drops when the process dies; a second taker waits in
    line. The file names the holder; `waiting(text)` is called with it once, before blocking. With `timeout` (seconds) a
    wait that long raises TimeoutError (the holder's name in it). No-op without fcntl."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "a+")
    try:
        if fcntl:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                if waiting:
                    who = ""
                    for _ in range(20):  # the holder may be between its truncate and its write
                        who = Path(path).read_text().strip()
                        if who:
                            break
                        time.sleep(0.01)
                    waiting(who or "?")
                if timeout is None:
                    fcntl.flock(f, fcntl.LOCK_EX)
                else:
                    end = time.monotonic() + timeout
                    while True:
                        try:
                            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                            break
                        except OSError:
                            if time.monotonic() >= end:
                                raise TimeoutError(Path(path).read_text().strip() or "?")
                            time.sleep(0.05)
        f.seek(0)
        f.truncate()
        f.write(holder)
        f.flush()
        yield path
    finally:
        if fcntl:
            fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def land_lock_path(url):
    """The repo's land lock (one per origin URL): every land, and a release's push, take it (os_lock)."""
    return config_dir() / "locks" / ("land-%s.lock" % hashlib.sha1(url.encode()).hexdigest()[:12])


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


def pinned_env(path):
    """GIT_DIR and GIT_WORK_TREE of the checkout at `path` (its nearest parent with a .git), read from its own `.git`
    (a slot's `.git` file says `gitdir: <its dir under the repo's .git/worktrees>`). With both set git ignores the
    repo's shared config: a core.worktree written into .git/config (lifesim-1mm) pointed every slot at another folder.
    {} when `path` is no checkout."""
    p = Path(path).resolve()
    for d in (p, *p.parents):
        g = d / ".git"
        if g.is_dir():
            return {"GIT_DIR": str(g), "GIT_WORK_TREE": str(d)}
        if g.is_file():
            try:
                m = re.match(r"gitdir:\s*(.+)", g.read_text(encoding="utf-8", errors="replace").strip())
            except OSError:
                return {}
            return {"GIT_DIR": str((d / m.group(1)).resolve()), "GIT_WORK_TREE": str(d)} if m else {}
    return {}


def git_env(path):
    """The environment for a git command on the checkout at `path`: the process's, pinned to that checkout."""
    return dict(os.environ, **pinned_env(path))


def run_git(path, *args, **kw):
    """`git -C path args`, pinned to the checkout at `path` (the one helper for subprocess git calls on a checkout)."""
    return subprocess.run(["git", "-C", str(path)] + list(args), env=git_env(path), **kw)


def git(*args, cwd=None):
    r = subprocess.run(["git"] + list(args), cwd=cwd, env=git_env(cwd) if cwd else None, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return r.stdout.strip() if r.returncode == 0 else ""


# another process fetching into the same repo (worktrees share refs/remotes) at the same moment: the ref is then where
# it should be, the fetch only lost the lock (race test, tl-bxk.11.1: 150 of 180 fetches at once failed so)
REF_RACE = re.compile(r"incorrect old value|cannot lock ref|unable to update local ref|Unable to create '[^']*\.lock'")


def fetch(cwd=None, tries=5):
    """`git fetch -q origin`, tried again while it loses a ref lock to a concurrent fetch; the last CompletedProcess."""
    for i in range(tries):
        r = subprocess.run(["git", "fetch", "-q", "origin"], cwd=cwd, env=git_env(cwd) if cwd else None,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode == 0 or not REF_RACE.search(r.stderr or ""):
            break
        time.sleep(0.1 * (i + 1))
    return r


def repo_root(cwd=None):
    """The main checkout of the repo (shared by all its worktrees), so every worktree maps to one repo."""
    common = git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=cwd)
    if common:
        p = Path(common)
        return str(p.parent if p.name == ".git" else p)
    return git("rev-parse", "--show-toplevel", cwd=cwd) or str(Path(cwd or os.getcwd()).resolve())


def cmd_land_lock(a):
    """Run a command while holding the repo's land lock (what the engine takes around fetch, rebase, gate, push)."""
    cmd = list(a.cmd_args)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("land-lock: no command (usage: tl.py land-lock [--repo DIR] -- CMD...)", file=sys.stderr)
        return 2
    repo = str(Path(a.repo).resolve())
    path = land_lock_path(git("remote", "get-url", "origin", cwd=repo) or repo)
    holder = "land-lock pid %d (%s)" % (os.getpid(), " ".join(cmd)[:80])
    secs = a.wait_min * 60 if a.wait_min is not None else None
    child = []
    got = []

    def stop(sig, _frame):
        got.append(sig)
        for c in child:
            if c.poll() is None:
                c.send_signal(sig)
        if not child:
            raise SystemExit(128 + sig)

    old = {s: signal.signal(s, stop) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        with os_lock(path, holder, lambda who: print("waiting for the land lock (held by %s)" % who, flush=True), secs):
            try:
                child.append(subprocess.Popen(cmd))
            except OSError as e:
                print("land-lock: cannot run %s: %s" % (cmd[0], e), file=sys.stderr)
                return 127
            rc = child[0].wait()
            return 128 + got[0] if got and rc < 0 else rc
    except TimeoutError as e:
        print("land-lock: gave up after %s min waiting for the land lock (held by %s)" % (a.wait_min, e), file=sys.stderr)
        return 75
    finally:
        for s, h in old.items():
            signal.signal(s, h)


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
    """Add a repo to repos.json. Every process registers (each event does): the read and write go under a lock, each
    through its own tmp file, so two at once neither crash nor drop a repo."""
    f = config_dir() / "repos.json"

    def read():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    if not path or path in read():
        return
    with os_lock(config_dir() / "locks" / "repos.lock", "pid %d" % os.getpid()):
        repos = read()
        if path not in repos:
            repos[path] = {"added": now()}
            tmp = f.with_name("repos.%d.tmp" % os.getpid())
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
    tmp = f.with_name("events.%d.tmp" % os.getpid())
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
    # tl-159: a parked bead lets go of its claim; the actor that held it stays live (a loop holds other beads), and a claim
    # nobody works on refused --fresh as 'taken: live claim'. A person's pre-existing claim is released too: parking ends the work.
    held = (show(a.id) or {}).get("assignee") or ""
    # a claim by an engine's actor ends with the run; a person's own claim stays theirs (tl-159)
    r = bd("update", a.id, "--status", "blocked", *(["--assignee", ""] if held.startswith("tl-") else []))
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

def profile(repo, base=None):
    """The repo's loop profile (.task-loop.json, parsed). With `base` (a ref such as origin/main), the copy committed
    there, so a pushed rule counts after a fetch even when nobody pulled the checkout; the working tree only when
    `base` does not resolve here (no remote). A file missing on the base is {}: committed wins."""
    if base and git("rev-parse", "--verify", "-q", base + "^{commit}", cwd=repo):
        try:
            return json.loads(git("show", "%s:.task-loop.json" % base, cwd=repo) or "{}")
        except ValueError:
            return {}
    try:
        return json.loads((Path(repo) / ".task-loop.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


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
        with slot_lock(repo):
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
        with slot_lock(repo):
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
                fetch(repo)
                r = run_git(repo, "worktree", "add", "--detach", d, "origin/main",
                                   capture_output=True, text=True, encoding="utf-8", errors="replace")
                if r.returncode != 0:
                    sys.exit(r.stderr)
            print(name + "\t" + d)
        return 0
    if a.op == "take":  # claim the first free slot, never ahead of a waiter in line; prints NAME DIR BEAD
        got = wait_slot(repo, cfg, "tl slot take", stop=lambda: True)
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
            r = run_git(d, "commit", "-qm", "wip: left in slot %s" % a.name,
                               capture_output=True, text=True, encoding="utf-8", errors="replace")
            if r.returncode != 0:
                print("DIRTY: could not commit the leftover work on %s\n%s" % (br, r.stderr))
                a.error = "could not commit the leftover work on %s: %s" % (br, error_line(r.stderr))
                return 3
            print("WIP committed on " + br)
        fetch(d)
        base = cfg.get("base") or "origin/main"
        if a.bead and git("rev-parse", "--verify", "-q", "refs/heads/task/" + a.bead, cwd=d):
            # the bead's branch holds its earlier runs' work: check it out as it is, never reset it to base (a forced
            # reset here wiped lifesim-r32's reviewed work on 2026-10-19; the engine rebases at land)
            held = free_branch(repo, d, "task/" + a.bead)
            if held:  # a live run has it: this bead is not for this slot now (never a failure)
                print("TAKEN: " + held)
                a.error = held
                return 5
            r = run_git(d, "checkout", "task/" + a.bead, capture_output=True, text=True,
                               encoding="utf-8", errors="replace")
        elif a.bead:
            r = run_git(d, "checkout", "-b", "task/" + a.bead, base, capture_output=True, text=True, encoding="utf-8", errors="replace")
        else:
            r = run_git(d, "checkout", "--detach", base, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            sys.stderr.write(r.stderr)
            a.error = error_line(r.stderr)
            return r.returncode
        run_git(d, "clean", "-fdq", *sum((["-e", k] for k in cfg.get("keep", [])), []))
        rc = cmd_slot_setup(repo, a.name, cfg, d)
        if rc != 0:
            a.error = "setup exited %d" % rc
        return rc
    if a.op == "setup":
        return cmd_slot_setup(repo, a.name, cfg, slot_dir(repo, a.name, cfg), force=True)
    return 2


def take_slot(repo, cfg, why="tl loop", bead="", ticket=None):
    """(name, dir, slot bead) of the first free slot this session could claim, or None. Free: its bead open, no hold,
    and no live engine or worker in its worktree (a run started without the slot bead, an older engine). A waiter
    calls wait_slot, which takes its turn in the line first; `ticket` is its number, kept on the take's event."""
    with slot_lock(repo):
        free_expired(repo)
        for b in slot_beads(repo):
            name = b["title"].split()[-1]
            d = slot_dir(repo, name, cfg)
            if b.get("status") != "open" or slot_hold(b) or engine_busy(d) or not claim_slot(repo, b["id"]):
                continue
            mark_held(repo, b["id"], why, bead=bead)
            event("slot-take", "", slot=name, slot_bead=b["id"], worktree=d, repo=repo,
                  **({"ticket": ticket} if ticket is not None else {}))
            return name, d, b["id"]
    return None


def slot_lock(repo):
    """Every slot claim (take, named take, hold) of the repo, one at a time, the look at the slot bead inside: bd lets
    an actor re-claim its own bead, and hand runs of one session share its actor, so a claim alone never tells two of
    them apart (race test: a --slot any won s1 a hand --slot s1 had just taken, then released it under that run)."""
    return os_lock(config_dir() / "locks" / ("slot-take-%s.lock" % repo_key(repo)), "pid %d" % os.getpid())


# ---- the slot line: waiters get free slots in arrival order (tl-bxk.11.5) ---------------------------------------------
# A waiter (a loop, run-task --slot any) takes a ticket, a file <seq>.json {seq, pid, start, why, since} under the
# repo's slot state; only the first live ticket may take a slot; a ticket whose process is gone (pid and start time) is
# dropped by whoever reads the line.

TICKET_POLL = (1, 5)  # run-task --slot any --wait: seconds between looks, first and at most


def repo_key(repo):
    return "%s-%s" % (Path(repo).name, hashlib.sha1(str(repo).encode()).hexdigest()[:8])


def ticket_dir(repo):
    d = config_dir() / "slots" / repo_key(repo)
    d.mkdir(parents=True, exist_ok=True)
    return d


def take_ticket(repo, why):
    """This process's place at the end of the line: numbers only grow (a counter file), and a ticket appears whole
    (written aside, then linked in: a link never replaces a file another waiter made)."""
    d = ticket_dir(repo)
    me = {"pid": os.getpid(), "start": proc_start(os.getpid()), "why": why, "since": now()}
    with os_lock(d / "line.lock", "pid %d" % os.getpid()):
        try:
            last = int((d / "seq").read_text().strip() or 0)
        except (OSError, ValueError):
            last = 0
        seqs = [int(f.stem) for f in d.glob("*.json") if f.stem.isdigit()]
        seq = max([last] + seqs) + 1
        tmp = d / (".%d.%d.tmp" % (os.getpid(), seq))
        while True:
            t = dict(me, seq=seq, path=str(d / ("%012d.json" % seq)))
            tmp.write_text(json.dumps(t), encoding="utf-8")
            try:
                os.link(str(tmp), t["path"])
                break
            except FileExistsError:  # without fcntl (Windows) the lock is a no-op: the link still decides
                seq += 1
            finally:
                with contextlib.suppress(OSError):
                    tmp.unlink()
        (d / "seq").write_text(str(seq))
    return t


def drop_ticket(t):
    with contextlib.suppress(OSError, TypeError):
        os.unlink(t["path"])


def waiting_line(repo):
    """The live tickets, first in line first; a dead waiter's ticket is removed."""
    out = []
    for f in ticket_dir(repo).glob(".*.tmp"):  # a waiter that died between writing and linking its ticket
        with contextlib.suppress(OSError):
            if time.time() - f.stat().st_mtime > 600:
                f.unlink()
    for f in sorted(ticket_dir(repo).glob("*.json")):
        try:
            t = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue  # gone meanwhile
        if not isinstance(t, dict) or not proc_alive(t.get("pid"), t.get("start") or ""):
            with contextlib.suppress(OSError):
                f.unlink()
            continue
        out.append(t)
    return sorted(out, key=lambda t: t.get("seq", 0))


def wait_slot(repo, cfg, why, bead="", stop=None, sleep=time.sleep, poll=None, on_wait=None):
    """(name, dir, slot bead) once this waiter is first in line and a slot is free; None when stop() says so after a
    look (stop=lambda: True: one look, no wait). on_wait(ahead) is called before each sleep. Never takes a slot while a
    live ticket is ahead of it."""
    first, most = poll or TICKET_POLL
    t, delay = take_ticket(repo, why), first
    try:
        while True:
            ahead = [x for x in waiting_line(repo) if x.get("seq", 0) < t["seq"]]
            if not ahead:
                got = take_slot(repo, cfg, why, bead=bead, ticket=t["seq"])
                if got:
                    return got
            if stop and stop():
                return None
            if on_wait:
                on_wait(len(ahead))
            sleep(delay)
            delay = min(delay * 2, most)
    finally:
        drop_ticket(t)


def take_named_slot(repo, name, cfg, why, bead=""):
    """(slot bead, "") when this session now holds slot `name`, or (None, why not): `slot S held by X since T`. A held
    slot bead is refused even when this session's actor holds it (two hand runs from one session
    share its actor, and bd lets an actor re-claim its own bead); a hold too, its holder's own included."""
    with slot_lock(repo):
        free_expired(repo)
        return take_named_slot_locked(repo, name, cfg, why, bead)


def take_named_slot_locked(repo, name, cfg, why, bead):
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
    mark_held(repo, b["id"], why, bead=bead)
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


def release_slot(repo, name, bead=None, mine=False):
    """Frees slot `name`. mine=True (a run ending): under slot_lock, and only while the slot's marks still name this
    actor (and `bead`, when it is marked): a slot reclaimed and retaken is the new holder's, left alone."""
    with slot_lock(repo):
        return release_slot_locked(repo, name, bead, mine)


def release_slot_locked(repo, name, bead, mine):
    b = slot_bead(repo, name)
    if not b:
        return False
    if mine:
        m = b.get("metadata") or {}
        if m.get("held_by") != actor() or (bead is not None and m.get("held_bead") not in (None, "", bead)):
            print("tl: slot %s is no longer held by %s%s (now %s): left alone" % (
                name, actor(), " for " + bead if bead else "", held_by(b) if b.get("status") != "open" else "free"),
                file=sys.stderr)
            return True
    # the holder's marks go first, while the bead is still claimed: unclaimed first, a hold taken in between would lose
    # its marks to this clean-up (race test, tl-bxk.11.1)
    bd("update", b["id"], *sum((["--unset-metadata", k] for k in HELD_KEYS), []), cwd=repo)
    bd("unclaim", b["id"], cwd=repo)
    event("slot-release", "", slot=name, slot_bead=b["id"], repo=repo)
    return True


def free_expired(repo):
    """An expired hold gives its slot bead back (the holder's claim with it), so the slot is free at once. Takes no
    lock: the caller holds slot_lock, so a stale look never wipes a slot another session took meanwhile."""
    for b in slot_beads(repo):
        m = b.get("metadata") or {}
        if hold_until(b) and not slot_hold(b):
            bd("update", b["id"], *sum((["--unset-metadata", k] for k in HELD_KEYS), []), cwd=repo)  # first: see release_slot
            if b.get("status") == "in_progress" and (b.get("assignee") or "") in ("", m.get("held_by")):
                bd("unclaim", b["id"], cwd=repo)
            event("slot-hold-expired", "", slot=b["title"].split()[-1], slot_bead=b["id"], repo=repo)


def slot_bead(repo, name):
    return next((x for x in slot_beads(repo) if x["title"].split()[-1] == name), None)


HELD_KEYS = ("held_by", "held_since", "held_why", "hold_until", "held_bead")


def stamp(t):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t))


def mark_held(repo, bead_id, why, until=0, bead=""):
    """Who holds a slot, since when and why, on its bead: tl slot list and a refused run-task read them. `until`: a hold
    (tl slot hold), which outlives the bead's lease. `bead`: the bead run there (held_bead), which makes its area busy."""
    sets = ["held_by=" + actor(), "held_since=" + stamp(now()), "held_why=" + why]
    args = sum((["--set-metadata", x] for x in sets), [])
    args += ["--set-metadata", "hold_until=%d" % until] if until else ["--unset-metadata", "hold_until"]
    # unset when none: bd reclaim frees a dead holder's slot bead but keeps its metadata, its bead's area with it
    args += ["--set-metadata", "held_bead=" + bead] if bead else ["--unset-metadata", "held_bead"]
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


def loop_lock(wt, slot, slot_bead, bead=""):
    """The loop's lock from its slot take to its run-task's own: no hand run gets in during the slot reset. `bead`, once
    claimed: the area check sees it there."""
    write_engine_lock(wt, {"pid": os.getpid(), "start": proc_start(os.getpid()), "bead": bead, "slot": slot or "",
                           "slot_bead": slot_bead or "", "by": "loop", "started": now()})


def worktrees(repo, slots=None):
    """Every worktree of the repo (git worktree list) and every slot folder (`slots`: the slot beads, when the caller
    has them): where an engine lock may be."""
    out = git("worktree", "list", "--porcelain", cwd=repo) or ""
    found = [ln[9:] for ln in out.splitlines() if ln.startswith("worktree ")]
    cfg = profile_slots(repo)
    found += [slot_dir(repo, b["title"].split()[-1], cfg) for b in (slot_beads(repo) if slots is None else slots)]
    seen, keep = set(), []
    for d in found:
        k = os.path.realpath(d)
        if k not in seen and os.path.realpath(repo) != k:
            seen.add(k)
            keep.append(d)
    return keep


def error_line(text):
    """The line of git's stderr that says what went wrong: the first fatal/error one, else the last."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    return next((ln for ln in lines if ln.startswith(("fatal:", "error:"))), lines[-1] if lines else "no message from git")


def free_branch(repo, d, branch):
    """Make `branch` free to check out in `d`. Another worktree holding it (a pre-slot worktree, a dead run's) is
    removed when clean, else detached where it stands: its files and commits stay (tl-bxk.10.26, lifesim 2026-10-22).
    Returns "" when free, else why a live run keeps it (the repo's own checkout counts as live)."""
    out = git("worktree", "list", "--porcelain", cwd=d) or ""
    here, held = os.path.realpath(d), []
    for i, block in enumerate(out.split("\n\n")):
        wt = next((ln[9:] for ln in block.splitlines() if ln.startswith("worktree ")), "")
        if wt and "branch refs/heads/%s" % branch in block.splitlines() and os.path.realpath(wt) != here:
            held.append((wt, i == 0))
    for wt, main in held:
        busy = engine_busy(wt)
        if busy or main:
            return "branch %s is checked out in %s%s" % (branch, wt, ": " + busy if busy else " (the repo's own checkout)")
    for wt, _ in held:
        if not git("status", "--porcelain", cwd=wt):
            r = run_git(repo, "worktree", "remove", wt, capture_output=True, text=True, encoding="utf-8", errors="replace")
            if r.returncode == 0:
                print("FREED: branch %s: removed the clean worktree %s" % (branch, wt))
                continue
        r = run_git(wt, "checkout", "--detach", capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode == 0:
            print("FREED: branch %s: detached HEAD in %s (its files and commits stay)" % (branch, wt))
        else:
            return "branch %s is checked out in %s and cannot be detached: %s" % (branch, wt, error_line(r.stderr))
    return ""


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
            if owner != actor() and any(w == owner or w.startswith(owner + "-") for w in live if w):
                continue  # a loop of that session claims as <owner>-<suffix>
            if git("status", "--porcelain", cwd=str(d)):
                print("KEEP dirty " + str(d))
                continue
            run_git(repo, "worktree", "remove", str(d), capture_output=True)
            event("worktree-sunset", "", worktree=str(d), repo=repo)
            print("REMOVED " + str(d))
        git("worktree", "prune", cwd=repo)
        return 0
    return 2


def start_worktree(repo, name=None):
    """This session's loop worktree (`name`: the loop's pick, default this actor's), made once and reused."""
    exclude_local(repo, ".worktrees/", ".task/")
    d = Path(repo) / ".worktrees" / ("loop-" + (name or actor()[3:]))
    if not d.exists():
        fetch(repo)
        r = run_git(repo, "worktree", "add", "--detach", str(d), "origin/main",
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


_dash_mod = []


def dash_module():
    if not _dash_mod:
        import importlib.util
        spec = importlib.util.spec_from_file_location("tl_dash_server", DASH)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _dash_mod.append(m)
    return _dash_mod[0]


def expected_binds():
    """The addresses the installed server would bind now."""
    return dash_module().plan(None, None, dev=False)[0]


def is_dev_checkout():
    return dash_module().is_dev_checkout(HERE)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def ping(port=None):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/version" % (port or PORT), timeout=1.5) as r:
            return json.loads(r.read())
    except Exception:
        return None


def is_dash_server(v):
    """Shape of a task-loop dashboard's /api/version: the only thing ensure may stop."""
    return isinstance(v, dict) and all(k in v for k in ("version", "pid", "urls", "started"))


def stale_reason(v, version, want):
    """Why a running dashboard must be replaced, else None."""
    script = v.get("script")
    if not script:
        return "it predates script/binds reporting"
    if not Path(script).exists():
        return "its script is gone: " + script
    if v.get("version") != version:
        return "version %s differs from installed %s" % (v.get("version"), version)
    missing = [a for a in want if a not in (v.get("binds") or [])]
    if missing:
        return "it does not serve " + ", ".join(missing)
    return None


def stop_server(v=None, port=None):
    """Stop the task-loop server that answers on the port (its own pid, never a stale pidfile's)."""
    v = v or ping(port)
    if not is_dash_server(v) or not v.get("pid"):
        return
    try:
        pid = int(v["pid"])
    except ValueError:
        return
    if pid in (os.getpid(), os.getppid()) or pid <= 1:  # a server that names this very process is a test's, not ours to stop
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    for _ in range(20):
        if not ping(port):
            return
        time.sleep(0.2)


def log_tail(n=5):
    try:
        return "\n".join((config_dir() / "dash.log").read_text(errors="replace").strip().splitlines()[-n:])
    except OSError:
        return ""


def start_server(port, bind=None):
    """Start detached; wait until it answers. Returns (version dict or None, failure text)."""
    log = open(config_dir() / "dash.log", "ab")
    env = {k: val for k, val in os.environ.items()
           if not k.startswith(("CLAUDE_CODE_SESSION", "DELEGATE_", "CODEX_COMPANION"))}
    kw = {"stdin": subprocess.DEVNULL, "stdout": log, "stderr": log, "env": env, "cwd": str(config_dir()), "close_fds": True}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    cmd = [sys.executable, str(DASH), "--port", str(port)] + (["--bind", bind] if bind else [])
    proc = subprocess.Popen(cmd, **kw)
    for _ in range(40):
        if proc.poll() not in (None, 0):
            return None, "dashboard exited %s: %s" % (proc.poll(), log_tail() or "see " + str(config_dir() / "dash.log"))
        v = ping(port)
        if v:
            return v, ""
        time.sleep(0.25)
    return None, "dashboard did not start; see " + str(config_dir() / "dash.log")


def close_stale_asks(every=600):
    """tl-bxk.13.16.5: an open ask whose bead is closed, or does not exist, is closed with the reason (lifesim-u3bx was closed by
    hand a minute after its ask and sat open 40 hours; a demo record named a bead `demo`). A bd that fails for another reason
    changes nothing. At most once per `every` seconds across all callers. -> the bead ids closed."""
    marker = config_dir() / "asks" / ".swept"
    try:
        if time.time() - marker.stat().st_mtime < every:
            return []
    except OSError:
        pass
    done, by_repo = [], {}
    for f in sorted(glob.glob(str(config_dir() / "asks" / "*.json"))):
        try:
            a = json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(a, dict) or a.get("status") not in ("open", "parked") or not a.get("bead"):
            continue
        if not (isinstance(a.get("repo"), str) and (Path(a["repo"]) / ".beads").is_dir()):
            continue  # which repo's tracker to ask is not known (bd would walk up to another one): the ask stays
        by_repo.setdefault(a["repo"], []).append((f, a))
    listed_any = False
    for repo, items in by_repo.items():  # one bd read per repo (tl-u08: a bd show per ask took over two minutes for 25 asks)
        try:
            r = bd("list", "--json", "--all", "-n", "0", cwd=repo)
        except SystemExit:  # no bd on this machine
            return done
        if r.returncode != 0:
            continue
        try:
            status = {b.get("id"): b.get("status") for b in json.loads(r.stdout) if isinstance(b, dict)}
        except (ValueError, TypeError):
            continue
        if not status:
            continue  # an empty answer proves nothing
        listed_any = True
        for f, a in items:
            why = ""
            if a["bead"] not in status:  # the list hides gates, ephemeral and infra beads: ask bd about this one before saying so
                try:
                    one = bd("show", a["bead"], "--json", cwd=repo)
                except SystemExit:
                    return done
                if one.returncode != 0 and re.search(r"no issues? found matching|issue .{0,60}not found|no such issue",
                                                     (one.stderr or "") + (one.stdout or ""), re.I):
                    why = "the bead does not exist"
            elif status[a["bead"]] == "closed":
                why = "the bead is closed"
            if why:
                try:  # the owner or the engine may have written since the read: close only what is still open or parked
                    cur = json.loads(Path(f).read_text(encoding="utf-8"))
                    if cur.get("status") not in ("open", "parked") or cur.get("id") != a.get("id"):
                        continue
                    cur.update(status="closed", closed=time.time(), closed_why=why)
                    Path(f).write_text(json.dumps(cur, indent=1), encoding="utf-8")
                    done.append(a["bead"])
                except (OSError, ValueError):
                    pass
    try:
        if listed_any or not by_repo:  # a bd outage is no sweep: it is tried again at once
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(str(time.time()))
    except OSError:
        pass
    return done


REPUSH, LOOK_BATCH = 24 * 3600, 24 * 3600  # an ask nobody answered is pushed again after this; a batch of looks waits at most this often


def push(kind, bead, ask_id, text, repeat=False):
    """The owner's push (notifier.py: a command in ~/.config/task-loop/notify, or the word `desktop`); the command gets TL_ASK_KIND,
    TL_ASK_BEAD, TL_ASK_ID and TL_ASK_TEXT (and TL_ASK_REPEAT=1 for a second push of the same thing). -> '' when started or when
    there is no channel, else the error."""
    import notifier
    got = notifier.send(kind, text, bead=bead, ask_id=ask_id, repeat=repeat)
    return got[len("failed: "):] if got.startswith("failed") else ""


def _ask_head(markdown):
    lines = [x.strip() for x in str(markdown or "").splitlines() if x.strip()]
    return lines[0].replace("**", "")[:300] if lines else ""


def _stamp(path):
    """The time a marker file says (it holds the time it was written), 0 when there is none."""
    try:
        return float(Path(path).read_text().strip())
    except (OSError, ValueError):
        return 0.0


def renotify(every=3600, now=None):
    """tl-bxk.8.26: one push per new ask was all the owner got. An ask still open and unanswered 24 h after its last push is
    pushed again (once per 24 h until it is answered or parks); once a day, when reviews of how things look wait in the
    repos, one push says how many. Throttled to once per `every` seconds across all callers. -> [(kind, id)] pushed."""
    now = now or time.time()
    marker = config_dir() / "asks" / ".repushed"
    if now - _stamp(marker) < every:
        return []
    sent = []
    try:
        for f in sorted(glob.glob(str(config_dir() / "asks" / "*.json"))):
            try:
                got = _repush_one(f, now)
            except Exception as e:  # one odd ask file never stops the rest, and never the loop that called this
                sys.stderr.write("tl: re-push of %s skipped: %s\n" % (os.path.basename(f), e))
                continue
            if got:
                sent.append(got)
        sent += _push_looks(now)
    except Exception as e:
        sys.stderr.write("tl: re-push skipped: %s\n" % e)
    finally:
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(str(now))
        except OSError:
            pass
    return sent


def _repush_one(f, now):
    """One ask file: pushed again when due. -> (kind, id) or None."""
    def load():
        a = json.loads(Path(f).read_text(encoding="utf-8"))
        return a if isinstance(a, dict) and a.get("bead") and a.get("id") else None

    def due(x):
        last = float(x.get("pushed_at") or x.get("t") or now)
        return (x.get("status") == "open" and not x.get("answer") and not x.get("answer_t")
                and not (x.get("parks_at") and now >= float(x["parks_at"])) and now - last >= REPUSH)
    a = load()
    if not a or not due(a):
        return None
    try:
        with os_lock(config_dir() / "locks" / ("repush-%s.lock" % hashlib.sha1(f.encode()).hexdigest()[:12]), "pid %d" % os.getpid(), timeout=0.3):
            a = load()  # another loop may have pushed it a moment ago
            if not a or not due(a):
                return None
            waited = int((now - float(a.get("t") or now)) // 3600)
            err = push(str(a.get("kind") or "ask"), a["bead"], a["id"], "Still waiting for you (%d h): %s" % (waited, _ask_head(a.get("question"))), True)
            if err:
                sys.stderr.write("tl: notify failed: %s\n" % err)
                return None
            fresh = load() or a  # the dashboard may have written an answer meanwhile: keep it, add only the push
            fresh["pushed_at"], fresh["pushes"] = now, int(fresh.get("pushes") or 0) + 1
            Path(f).write_text(json.dumps(fresh, indent=1), encoding="utf-8")
            return (a.get("kind") or "ask", a["id"])
    except TimeoutError:
        return None


def _push_looks(now):
    """The daily batch: owner-look beads still open across the registered repos."""
    state = config_dir() / "asks" / ".looks_pushed"
    if now - _stamp(state) < LOOK_BATCH:
        return []
    try:
        repos = [r for r in json.loads((config_dir() / "repos.json").read_text(encoding="utf-8")) if isinstance(r, str) and os.path.isdir(r)]
    except (OSError, ValueError):
        return []
    waiting, first = 0, ""
    for r in repos:
        try:
            out = bd("list", "--label", "owner-look", "--json", "-n", "0", cwd=r)
            rows = json.loads(out.stdout or "[]") if out.returncode == 0 else []
        except (SystemExit, ValueError, OSError):
            continue
        rows = [x for x in rows if isinstance(x, dict) and x.get("status") != "closed"]
        waiting += len(rows)
        first = first or (rows[0].get("id") if rows else "")
    try:
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(str(now))  # checked once a day whatever it found
    except OSError:
        return []
    if not waiting:
        return []
    err = push("look", first, "looks-" + time.strftime("%Y%m%d", time.localtime(now)),
               "%d look review%s wait for you: the dashboard's Looks tab has the pictures" % (waiting, "" if waiting == 1 else "s"))
    return [] if err else [("look", "looks")]


def cmd_ask(a):
    """The inbox from the terminal: the dashboard's own code answers and withdraws, so both say the same things."""
    d = dash_module()
    if a.op == "list":
        for b in close_stale_asks():  # throttled: the loop sweeps too, and the inbox hides closed beads itself
            print("closed the ask of %s: its bead is closed or gone" % b)
        rows = d.inbox()
        if a.json:
            print(json.dumps(rows, indent=1))
            return 0
        for r in rows:
            print("%-22s %-8s unblocks %-2d %s" % (r["bead"], r["kind"], r["unblocks"], (r.get("title") or "")[:60]))
            print("    " + " | ".join("%s -> %s" % (o["label"], o["answer"]) for o in r.get("options") or []) if r.get("options") else
                  "    (free text: tl ask answer %s <text>)" % r["bead"])
        if not rows:
            print("nothing waits on you")
        return 0
    if not a.bead:
        print("tl: ask %s needs a bead id" % a.op)
        return 2
    f = config_dir() / "asks" / ("%s.json" % a.bead)
    try:
        ask_id = json.loads(f.read_text()).get("id")
    except (OSError, ValueError):
        print("tl: no ask for %s" % a.bead)
        return 1
    if a.op == "answer":
        code, out = d.answer({"ask": ask_id, "text": " ".join(a.text), "amend": bool(getattr(a, "amend", False))})
    else:
        code, out = d.withdraw({"ask": ask_id, "why": " ".join(a.text) or "withdrawn with tl ask withdraw"})
    print(out.get("next") if code == 200 and out.get("next") else "done" if code == 200 else "tl: " + out.get("error", "failed"))
    return 0 if code == 200 else 1


def park_stale_asks(every=600):
    """tl-bxk.8.25: an open ask nobody answered by its parks_at (3 days after it was asked) is parked: status `parked`, a comment on
    the bead, off the live inbox's top and out of the morning digest's open count. The bead still waits; an answer (the dashboard,
    `tl ask answer`, or a comment on the bead) un-parks it. At most once per `every` seconds across all callers. -> bead ids."""
    marker = config_dir() / "asks" / ".parked"
    try:
        if time.time() - marker.stat().st_mtime < every:
            return []
    except OSError:
        pass
    done = []
    for f in sorted(glob.glob(str(config_dir() / "asks" / "*.json"))):
        try:
            a = json.loads(Path(f).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(a, dict) or a.get("status") != "open" or not a.get("bead") or a.get("answer"):
            continue
        try:
            late = time.time() > float(a.get("parks_at") or 0) > 0
        except (TypeError, ValueError):
            continue
        if not late or not (isinstance(a.get("repo"), str) and Path(a["repo"]).is_dir()):
            continue
        try:  # the engine or the dashboard may have written since the read above: park only what is still open and unanswered
            cur = json.loads(Path(f).read_text(encoding="utf-8"))
            if cur.get("status") != "open" or cur.get("answer") or cur.get("id") != a.get("id"):
                continue
            cur.update(status="parked", parked=time.time())
            a = cur
            Path(f).write_text(json.dumps(a, indent=1), encoding="utf-8")
            bd("comments", "add", a["bead"], "Parked (engine): ask %s got no answer in 3 days. It stays open for an answer: "
               "`tl ask answer %s <text>`, the dashboard, or a comment here." % (a.get("id"), a["bead"]), cwd=a["repo"])
            done.append(a["bead"])
        except (OSError, ValueError, SystemExit):
            pass
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(time.time()))
    except OSError:
        pass
    return done


def cmd_notify(a):
    """tl notify test | desktop | off: the owner's push channel (notifier.py). `desktop` and `off` write ~/.config/task-loop/notify."""
    import notifier
    f = config_dir() / "notify"
    if a.op in ("desktop", "off"):
        config_dir().mkdir(parents=True, exist_ok=True)
        f.write_text(a.op + "\n", encoding="utf-8")
        print("notify: %s" % a.op)
        return 0
    how = notifier.channel()[0]
    got = notifier.send("test", "task-loop push test: if you read this, asks and the morning digest reach you", bead="test")
    print("notify (%s): %s%s" % (how, got, "" if how != "off" else " -- put a shell command, or the word desktop, in %s" % f))
    return 0 if got == "sent" else 1


def cmd_digest(a):
    import digest
    return digest.cmd_digest(a)


def cmd_dash(a):
    dev = is_dev_checkout() and "TASK_LOOP_DASH_PORT" not in os.environ
    if dev and a.op == "ensure":  # tests/dev: own random loopback port; the installed server on :7878 stays untouched
        port = free_port()
        v, err = start_server(port, "127.0.0.1")
        if not v:
            print("tl: " + err)
            return 1
        print_urls(v)
        return 0
    if a.op == "stop":
        v = ping()
        if dev and v and v.get("script") != str(DASH):
            return 0  # never stop the installed server from a dev checkout
        stop_server(v)
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
    # ensure: running and current, else replace it (a stale one: files deleted, old version, or missing an address)
    if v and not is_dash_server(v):
        print("tl: port %d is held by something that is not a task-loop dashboard; not touching it" % PORT)
        return 1
    if v:
        why = stale_reason(v, code_version(), expected_binds())
        if not why:
            print_urls(v)
            return 0
        print("tl: replacing the running dashboard (pid %s): %s" % (v.get("pid"), why))
        stop_server(v)
        if ping():
            print("tl: could not stop the running dashboard (pid %s)" % v.get("pid"))
            return 1
    v, err = start_server(PORT)
    if not v:
        print("tl: " + err)
        return 1
    print_urls(v)
    return 0


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


# ---- doctor -------------------------------------------------------------------------------------------------------

def doctor_warnings(repo):
    """What is off in the repo's git setup for slots (tl-bxk.10.12), one line each."""
    out = []
    if git("config", "--get", "extensions.worktreeConfig", cwd=repo).lower() != "true":
        out.append("extensions.worktreeConfig is off in %s: per-worktree settings (core.worktree, core.bare) then live in "
                   "the one .git/config every slot shares, so a stray one redirects all slots; `git config "
                   "extensions.worktreeConfig true` gives each worktree its own config file." % repo)
    try:  # engine.checks[].inputs globs that match no tracked file would cache a green over changed code
        import checks_speed
        files = git("ls-files", cwd=repo).splitlines()
        for c in (profile(repo).get("engine") or {}).get("checks") or []:
            ins = [c["inputs"]] if isinstance(c.get("inputs"), str) else list(c.get("inputs") or [])
            for g in checks_speed.dead_globs(files, ins):
                out.append("check %s: inputs glob %s matches no tracked file, so the check is never cached; braces are "
                           "{a,b}, `*` stays in one folder, `**` crosses." % (c.get("id") or c.get("cmd"), g))
    except Exception:
        pass
    return out


def cmd_doctor(a):
    repo = repo_root()
    warns = doctor_warnings(repo)
    for w in warns:
        print("WARN " + w)
    if not warns:
        print("ok: no setup problems found in " + repo)
    return 0


# ---- main ---------------------------------------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(prog="tl.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("actor")
    sp.add_parser("doctor", help="warn about git settings that let a slot's git leave the slot")
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
    p = sp.add_parser("ask", help="the owner's inbox: list the open asks, answer one, or withdraw one that no longer applies")
    p.add_argument("op", choices=["list", "answer", "withdraw"])
    p.add_argument("bead", nargs="?")
    p.add_argument("text", nargs="*", help="answer: the answer; withdraw: why")
    p.add_argument("--json", action="store_true")
    p.add_argument("--amend", action="store_true", help="answer: replace an answer no run has used yet (the history stays)")
    p = sp.add_parser("notify", help="the owner's push channel: test it, or choose desktop notifications / off")
    p.add_argument("op", choices=["test", "desktop", "off"])
    p = sp.add_parser("digest", help="the digest of the night (landed, asks, paused, failed) plus refusals, DNS errors, flakes")
    p.add_argument("--since")
    p.add_argument("--until")
    p.add_argument("--send", action="store_true", help="push it through the notify channel (default: print)")
    p = sp.add_parser("dash")
    p.add_argument("op", choices=["ensure", "stop", "status", "url"])
    p = sp.add_parser("run-task")
    p.add_argument("id")
    p.add_argument("--worktree")
    p.add_argument("--slot", help="a slot name, or `any`: the next free slot in line (see --wait)")
    p.add_argument("--wait", action="store_true", help="--slot any: wait in line for a free slot instead of refusing")
    p.add_argument("--exclusive-area", action="store_true",
                   help="refuse (taken) when the bead's area has a bead running elsewhere; default: warn and run")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--fresh", action="store_true", help="drop the bead's checkpoint: plan again from the start")
    p.add_argument("--quiet", action="store_true", help="only steps and ⚠ lines (default: verbose, for a watching coordinator)")
    p.add_argument("--outcome-file", help="also write the outcome (the last stdout line, JSON) to this file")
    p = sp.add_parser("usage", help="pass get_usage's plan.windows (JSON) to delegate, so headless Claude steps may run")
    p.add_argument("windows")
    p = sp.add_parser("land-lock", help="run a command under the repo's land lock (the one the engine lands under)")
    p.add_argument("--repo", default=".", metavar="DIR", help="Git working directory (default: current directory)")
    p.add_argument("--wait-min", type=float, default=None, help="give up (exit 75) after this many minutes")
    p.add_argument("cmd_args", nargs=argparse.REMAINDER, metavar="-- CMD")
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
    p.add_argument("--pin", action="store_true", help="stay on this install (default: between beads, move to the newest installed one)")
    p.add_argument("--last", type=int, default=10, help="status: how many finished beads to show")
    p = sp.add_parser("stop", help="stop the repo's loop after its current bead (--now: SIGTERM the bead's run)")
    p.add_argument("--repo")
    p.add_argument("--now", action="store_true")
    p = sp.add_parser("report", help="the M2 scorecard: landed, asks, parked, paused, failed, crashes, lost work")
    p.add_argument("--repo")
    p.add_argument("--since", metavar="T", help="ISO, HH:MM (today) or a duration back (12h); default 24h")
    p.add_argument("--until", metavar="T", help="as --since; default now")
    p.add_argument("--json", action="store_true")
    p.add_argument("--planner", action="store_true", help="only the planner table: calls and input tokens per bead")
    p.add_argument("--prefix", metavar="P[,P]", help="with --planner: only beads with these id prefixes (default all)")
    p = sp.add_parser("lost", help="task/* and wip/* commits not on the base: landed, reclaimed, pending or lost")
    p.add_argument("--repo")
    p.add_argument("--since", metavar="T")
    p.add_argument("--json", action="store_true")
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
        a.argv = list(argv) if argv is not None else sys.argv[1:]  # the loop re-execs itself with these
        return {"next": loop.cmd_next, "loop": loop.cmd_loop, "stop": loop.cmd_stop}[a.cmd](a)
    if a.cmd in ("report", "lost"):
        import report
        return {"report": report.cmd_report, "lost": report.cmd_lost}[a.cmd](a)
    if a.cmd == "trace":
        return cmd_trace(a)
    if a.cmd == "bd":
        r = subprocess.run([shutil.which("bd") or "bd", "--actor", actor()] + a.rest)
        return r.returncode
    return {"register": cmd_register, "claim": cmd_claim, "heartbeat": cmd_heartbeat, "stage": cmd_stage, "worker": cmd_worker,
            "land": cmd_land, "close": cmd_close, "block": cmd_block, "slot": cmd_slot, "worktree": cmd_worktree,
            "dash": cmd_dash, "ask": cmd_ask, "notify": cmd_notify, "digest": cmd_digest, "hook": cmd_hook, "doctor": cmd_doctor, "land-lock": cmd_land_lock}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
