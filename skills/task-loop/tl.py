#!/usr/bin/env python3
"""tl.py: the task-loop helper. Python 3.8+, standard library only; macOS, Linux (also in Docker).

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
  tl.py reflect digest [--since 24h] [--dry-run]  the last day's run reflections into one bead per recurring cause
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
  tl.py pin [VERSION] [--delegate V] [--clear]  pin the plugin install a loop and run-task use (owner override; the loop never pins)
  tl.py rollback                                pin the previous task-loop version (the delegate stays as it is)
  tl.py cutover check [--json]                  live runs and loops on this machine; exit 1 if any (docs/cutover.md)
  tl.py hook session-start                      SessionStart hook: index session id -> transcript path

State: ~/.config/task-loop : repos.json, events.jsonl, sessions/, dash.*.
"""

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote



import vendored  # noqa: F401  (puts _vendor on sys.path)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))  # taskloop: the typed records and adapters ship in the plugin dir
from taskloop.adapters import applog, locks
from taskloop.adapters import delegate as sdelegate, procs as sproc
from taskloop.adapters.bd import BdStore
from taskloop.adapters.gitenv import git_env, pinned_env, run_git  # noqa: F401  (tl.run_git and tl.pinned_env are the callers' names)
from taskloop.adapters.slot_git import RealSlotGit
from taskloop.app.slots import env as slots_env
from taskloop.app.slots import line as slots_line
from taskloop.app.slots.env import SlotEnv, stamp
from taskloop.app.slots.pool import SlotPool
from taskloop.cli import slots as slots_cli
from taskloop.contracts import config, paths
from taskloop.contracts.bead import Bead
from taskloop.contracts.locks import LockTimeout
from taskloop.contracts.slots import SlotFail
from taskloop.stores.files import FileTickets
from taskloop.app.asks import sweeps as ask_sweeps
from taskloop.app.doctor import profiles
from taskloop.cli import asks as cli_asks
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import BdFailure, BeadPatch, BeadQuery
from taskloop.contracts.stores import AskStore
from taskloop_dash import bind as dash_bind
from taskloop_dash.cli import dash as dash_cli

HERE = Path(__file__).resolve().parent
DASH = HERE.parents[1] / "src" / "taskloop_dash" / "__main__.py"  # the script a running `python3 -m taskloop_dash` reports
PORT = int(os.environ.get("TASK_LOOP_DASH_PORT", "7878"))
SOURCE = "task-loop"
RETAIN_DAYS = 7


# ---- paths and identity -------------------------------------------------------------------------------------------

@contextlib.contextmanager
def os_lock(path, holder, waiting=None, timeout=None):
    """One holder at a time, across processes (the vendored ProcessLock; the OS drops it when the process dies); a second
    taker waits. `waiting(text)` is called with the holder's name once, before blocking. With `timeout` (seconds) a wait that
    long raises TimeoutError (the holder's name in it)."""
    told = (lambda rec: waiting(rec.holder if rec else "?")) if waiting else None
    try:
        with locks.hold_path(path, holder, timeout=timeout, waiting=told):
            yield path
    except LockTimeout as e:
        raise TimeoutError(e.holder.holder if e.holder else "?") from None


def land_lock_path(url):
    """The repo's land lock (one per origin URL): every land, and a release's push, take it (os_lock)."""
    return config_dir() / "locks" / ("land-%s.lock" % hashlib.sha1(url.encode()).hexdigest()[:12])


def config_dir():
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "task-loop"
    d.mkdir(parents=True, exist_ok=True)
    return d


def opencode_db():
    """OpenCode's session store (macOS/Linux); OPENCODE_DB overrides it (tests)."""
    env = os.environ.get("OPENCODE_DB")
    if env:
        return env
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return str(Path(base) / "opencode" / "opencode.db")


def opencode_id(ref):
    """`ses_...` or `opencode:ses_...` -> the OpenCode session id, else ""."""
    ref = str(ref or "")
    if ref.startswith("opencode:"):
        ref = ref[9:]
    return ref if re.match(r"^ses_[A-Za-z0-9]+$", ref) else ""


def opencode_rows(sql, args=()):
    """Read-only query of OpenCode's DB (session, message and part tables only): a list of rows, [] when the DB is missing,
    locked or another shape. Never writes, never reads the credential tables."""
    path = opencode_db()
    if not os.path.isfile(path):
        return []
    try:
        con = sqlite3.connect("file:%s?mode=ro" % quote(path), uri=True, timeout=1.0)
        try:
            return con.execute(sql, args).fetchall()
        finally:
            con.close()
    except (sqlite3.Error, ValueError, OSError):
        return []


def opencode_has(sid):
    return bool(sid) and bool(opencode_rows("SELECT 1 FROM session WHERE id = ?", (sid,)))


def opencode_updated(sid):
    """Seconds since the epoch of the session's last change (OpenCode stores ms), or None."""
    rows = opencode_rows("SELECT MAX(t) FROM (SELECT MAX(time_updated) t FROM message WHERE session_id = ? "
                         "UNION ALL SELECT MAX(time_updated) FROM part WHERE session_id = ?)", (sid, sid))
    return rows[0][0] / 1000.0 if rows and rows[0][0] else None


def opencode_context(sid):
    """-> input + cache read + cache write tokens of the session's last assistant message that reports any, or None."""
    for (data,) in opencode_rows("SELECT data FROM message WHERE session_id = ? ORDER BY time_created DESC, id DESC LIMIT 20", (sid,)):
        try:
            d = json.loads(data)
            if d.get("role") != "assistant":
                continue
            t = d["tokens"]
            n = int(t.get("input") or 0) + int((t.get("cache") or {}).get("read") or 0) + int((t.get("cache") or {}).get("write") or 0)
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
        if n:
            return n
    return None


def transcript_of(family, ref):
    """Where a worker session's transcript lives on this machine: Codex rollouts and Claude projects, by session id; for
    family xai (OpenCode) the session's `opencode:ses_...` reference into its DB."""
    if not ref:
        return ""
    if family == "xai" or opencode_id(ref):
        sid = opencode_id(ref)
        return "opencode:" + sid if opencode_has(sid) else ""
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
                                                               (r.get("cost") or {}).get("usd", 0) if isinstance(r.get("cost"), dict) else (r.get("cost") or 0), tok, r.get("coordinator_session") or "-"))
        for s in r.get("sessions", []):
            print("  %-7s %-8s %-6s %-9s %s  %s" % (s.get("node"), s.get("role"), s.get("family") or "?", s.get("status"),
                                                   s.get("ref") or "-", s.get("transcript") or ""))
    return 0


def session_id():
    """The session this process acts for: a Claude session, or the engine's own id when nobody drives it."""
    return (os.environ.get("TASK_LOOP_SESSION") or os.environ.get("CLAUDE_CODE_SESSION_ID")
            or os.environ.get("CLAUDE_SESSION_ID") or "")


def _sig(path):
    """What a file is now, as the file system says: (inode, mtime ns, size); None when it is missing. A git ref or lock file is replaced
    by a rename, so a changed ref always changes this."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_ino, st.st_dev, st.st_mtime_ns, st.st_size)


def _git_dirs(cwd):
    """(git dir, common dir, the `.git` entry of the checkout) read from the file system, or None when `cwd` is no plain checkout or uses
    a ref backend this reads nothing of (reftable)."""
    pin = pinned_env(cwd)
    gd = pin.get("GIT_DIR")
    if not gd:
        return None
    gd = Path(gd)
    common = gd
    try:
        c = (gd / "commondir").read_text(encoding="utf-8", errors="replace").strip()
        common = (gd / c).resolve()
    except OSError:
        pass
    if (common / "reftable").exists():
        return None
    return gd, common, Path(pin["GIT_WORK_TREE"]) / ".git"


def config_key(path):
    """What decides every `git config` answer for the checkout at `path`, as the file system shows it: its `.git`, each config file git
    reads for it, and the GIT_ environment that moves them. None when `path` is no plain checkout (nothing is to be cached then)."""
    dirs = _git_dirs(path)
    if not dirs:
        return None
    gd, common, dot_git = dirs
    home = Path(os.environ.get("HOME") or os.path.expanduser("~"))
    xdg = Path(os.environ.get("XDG_CONFIG_HOME") or (home / ".config"))
    files = [gd / "config.worktree", common / "config", common / "config.worktree", home / ".gitconfig", xdg / "git" / "config",
             Path("/etc/gitconfig"), Path("/opt/homebrew/etc/gitconfig"), Path("/usr/local/etc/gitconfig")]
    env = tuple(sorted((k, v) for k, v in os.environ.items() if k.startswith("GIT_") and k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR"))
                + [("HOME", str(home))])
    return (str(path), _is_dir_sig(dot_git), tuple(_sig(f) for f in files), env)


# Answers of read-only git questions that the file system can vouch for. `git()` runs a process (~14 ms) for each of
# them and the engine asks the same few dozen times per run (tl-speedgit).
_COMMON_DIR_MEMO = {}   # (resolved cwd, sig of its .git entry) -> the absolute git common dir
_REF_MEMO = {}          # (git dir, args) -> (sigs of every file the answer comes from, answer)


def _is_dir_sig(p):
    """A `.git` directory changes its mtime with every lock file; only which directory it is counts. A `.git` file (a slot) is stable."""
    try:
        st = os.stat(p)
    except OSError:
        return None
    return (st.st_ino, st.st_dev) if os.path.isdir(p) else (st.st_ino, st.st_dev, st.st_mtime_ns, st.st_size)


_COMMON_ARGS = ("rev-parse", "--path-format=absolute", "--git-common-dir")


_BAD_NAME = re.compile(r"[~^@:{}*?\\[\s]|\.\.|\.lock$|^-|^[0-9a-f]{4,40}$")


def _ref_files(args, dirs):
    """The files a `git rev-parse`, `symbolic-ref` or `merge-base` of ref names reads (loose refs, HEAD, packed-refs); None when it is a
    question the memo does not know (a revision expression, a sha that may be a prefix)."""
    gd, common, _ = dirs
    if args == ("symbolic-ref", "--short", "-q", "HEAD"):
        return [gd / "HEAD"]
    if len(args) == 2 and args[0] == "rev-parse":
        names = [args[1]]
    elif len(args) == 4 and args[:3] == ("rev-parse", "--verify", "-q"):
        names = [args[3]]
    elif len(args) == 3 and args[0] == "merge-base":
        names = list(args[1:])
    else:
        return None
    files = [common / "packed-refs", common / "shallow"]
    for name in names:
        for suffix in ("^{commit}", "^{tree}"):
            if name.endswith(suffix):
                name = name[:-len(suffix)]
        if not name or _BAD_NAME.search(name):
            return None
        if name == "HEAD":
            files.append(gd / "HEAD")
            try:
                head = (gd / "HEAD").read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                return None
            if head.startswith("ref:"):
                files.append(common / head[4:].strip())
            continue
        files += [common / (pre + name) for pre in ("", "refs/", "refs/tags/", "refs/heads/", "refs/remotes/")]
        files.append(common / "refs" / "remotes" / name / "HEAD")
    return files


def git(*args, cwd=None):
    common_key = ref_key = sigs = None
    if cwd is None and args == _COMMON_ARGS and not any(k in os.environ for k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR")):
        try:
            here = os.getcwd()  # the process's own checkout (repo_root() of every event): nothing is pinned, so only plain checkouts count
        except OSError:  # its folder is gone: git answers "" below
            here = None
        dirs = _git_dirs(here) if here else None
        if dirs:
            common_key = (here, _is_dir_sig(dirs[2]))
            if common_key in _COMMON_DIR_MEMO:
                return _COMMON_DIR_MEMO[common_key]
    elif cwd and args == ("remote", "get-url", "origin"):
        dirs = _git_dirs(cwd)
        ck = config_key(cwd) if dirs else None  # the url comes from config only (insteadOf included)
        if ck:
            common_key = ("get-url", ck)
            if common_key in _COMMON_DIR_MEMO:
                return _COMMON_DIR_MEMO[common_key]
    elif cwd:
        dirs = _git_dirs(cwd) if args and args[0] in ("rev-parse", "symbolic-ref", "merge-base") else None
        if dirs and args == _COMMON_ARGS:
            common_key = (str(Path(cwd).resolve()), _is_dir_sig(dirs[2]))
            if common_key in _COMMON_DIR_MEMO:
                return _COMMON_DIR_MEMO[common_key]
        elif dirs:
            files = _ref_files(args, dirs)
            if files:
                ref_key, sigs = (str(dirs[0]), args), tuple(_sig(f) for f in files)  # taken before git runs: a change during it shows next time
                hit = _REF_MEMO.get(ref_key)
                if hit and hit[0] == sigs:
                    return hit[1]
    r = subprocess.run(["git"] + list(args), cwd=cwd, env=git_env(cwd) if cwd else None, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    out = r.stdout.strip() if r.returncode == 0 else ""
    if common_key and out:
        _COMMON_DIR_MEMO[common_key] = out
    elif ref_key and (out or "--verify" in args):  # a ref that is missing is an answer too, until a file for it appears
        _REF_MEMO[ref_key] = (sigs, out)
    return out


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
                sproc.stop_tree(c)  # the child's tree, through stream-proc
        if not child:
            raise SystemExit(128 + sig)

    old = {s: signal.signal(s, stop) for s in (signal.SIGINT, signal.SIGTERM)}
    try:
        with os_lock(path, holder, lambda who: print("waiting for the land lock (held by %s)" % who, flush=True), secs):
            try:
                p, hold = sproc.popen_held(cmd)
            except OSError as e:
                print("land-lock: cannot run %s: %s" % (cmd[0], e), file=sys.stderr)
                return 127
            child.append(p)
            hold.replay()
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


def bd_store(cwd=None):
    """The bd of this session (adapters/bd.py, the one place that starts `bd`), asking the tracker of `cwd` (default: here)."""
    if not shutil.which("bd"):
        sys.exit("tl: bd is not on PATH")
    return BdStore(actor(), str(cwd) if cwd else None)


def peek(store, bead_id):
    """The bead, None when it is not there or bd could not be asked (a caller that must tell the two apart calls store.show)."""
    try:
        return store.show(bead_id)
    except BdFailure:
        return None


def cmd_bd(a):
    """`tl bd ...`: bd with this session's actor and --json, through the adapter."""
    r = bd_store().passthrough(a.rest)
    sys.stdout.write(r.out)
    sys.stderr.write(r.err)
    return r.code


def must(call, *args):
    """A bd write that ends the command when bd refuses."""
    try:
        return call(*args)
    except BdFailure as e:
        sys.exit("tl: " + e.error.text)


def listed(call, *args):
    """The beads a bd read lists, none when bd could not be asked."""
    try:
        return call(*args)
    except BdFailure:
        return []


def attempt(call, *args, **kw):
    """A bd write whose refusal changes nothing: True when it worked."""
    try:
        call(*args, **kw)
        return True
    except BdFailure:
        return False


# ---- records ------------------------------------------------------------------------------------------------------

def now():
    return time.time()


def event(kind, bead="", **fields):
    """One line per event in events.jsonl: the dashboard's fast local index (transcripts are local too)."""
    rec = {"t": now(), "kind": kind, "bead": bead, "session": session_id(), "actor": actor(),
           "repo": fields.pop("repo", None) or repo_root(), "host": socket.gethostname()}
    rec.update({k: v for k, v in fields.items() if v is not None})
    line = json.dumps(rec, ensure_ascii=False) + "\n"
    applog.append(config_dir() / "events.jsonl", line)  # tl-64i: one held handle per process, a line at a time
    register_repo(rec["repo"])
    return rec


def provenance(bead, kind, ref, ref_kind, payload=None, cwd=None, store=None):
    """The shared record in bd (append-only, idempotent); a bd without provenance is not fatal."""
    try:
        (store or bd_store(cwd)).provenance(bead, kind, SOURCE, ref, ref_kind, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                            json.dumps(payload) if payload else "")
    except BdFailure as e:
        sys.stderr.write("tl: provenance not recorded: " + (e.error.text.strip().splitlines() or ["?"])[-1] + "\n")


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

def cmd_claim(a, store=None):
    st = store or bd_store()
    if not st.claim(a.id):
        print("TAKEN")
        return 1
    b = peek(st, a.id) or Bead(id=a.id, title="", status="")
    if b.assignee not in ("", actor()):
        print("TAKEN by " + b.assignee)
        return 1
    wt = str(Path(a.worktree).resolve()) if a.worktree else git("rev-parse", "--show-toplevel")
    branch = b.metadata.get("branch") or "task/" + a.id
    attempt(st.update, a.id, BeadPatch(set_metadata=dict({"branch": branch}, **({"slot": a.slot} if a.slot else {}))))
    event("claim", a.id, worktree=wt, branch=branch, title=b.title, slot=a.slot)
    provenance(a.id, "claim", session_id() or actor(), "transcript" if session_id() else "work-id",
               {"worktree": wt, "actor": actor(), "slot": a.slot}, store=st)
    print("CLAIMED " + a.id + " branch=" + branch)
    return 0


def cmd_land(a):
    sha = git("rev-parse", "--verify", "-q", a.sha + "^{commit}", cwd=a.worktree) or a.sha
    event("land", a.id, sha=sha)
    provenance(a.id, "land", sha, "git-sha")
    return 0


def cmd_close(a, store=None):
    try:
        (store or bd_store()).close(a.id, a.reason or "done")
    except BdFailure as e:
        sys.stderr.write(e.error.text + "\n")
        return 1
    event("close", a.id, reason=a.reason)
    prune_events()
    return 0


def cmd_block(a, store=None):
    # tl-159: a parked bead lets go of its claim; the actor that held it stays live (a loop holds other beads), and a claim
    # nobody works on refused --fresh as 'taken: live claim'. A person's pre-existing claim is released too: parking ends the work.
    st = store or bd_store()
    held = (peek(st, a.id) or Bead(id=a.id, title="", status="")).assignee
    # a claim by an engine's actor ends with the run; a person's own claim stays theirs (tl-159)
    try:
        st.update(a.id, BeadPatch(status="blocked", assignee="" if held.startswith("tl-") else None))
    except BdFailure as e:
        sys.stderr.write(e.error.text + "\n")
        return 1
    attempt(st.add_comment, a.id, "Blocked: " + a.why)
    event("block", a.id, why=a.why)
    provenance(a.id, "suspend", session_id() or actor(), "transcript", {"why": a.why}, store=st)
    return 0


# ---- slots --------------------------------------------------------------------------------------------------------
# A slot is a persistent worktree, set up once and reused task after task. Each slot is a bead labelled `slot`
# (never picked as work); holding a slot = claiming its bead, so the lease, heartbeat and reclaim come from bd.

def profile(repo, base=None):
    """The repo's loop profile (.task-loop.json, parsed). With `base` (a ref such as origin/main), the copy committed
    there, so a pushed rule counts after a fetch even when nobody pulled the checkout; the working tree only when
    `base` does not resolve here (no remote). A file missing on the base is {}: committed wins."""
    return profile_source(repo, base)[0]


def profile_source(repo, base=None):
    """The profile and its exact commit, or an empty commit for the working-tree fallback."""
    commit = git("rev-parse", "--verify", "-q", base + "^{commit}", cwd=repo) if base else ""
    if commit:
        try:
            return json.loads(git("show", "%s:.task-loop.json" % commit, cwd=repo) or "{}"), commit
        except ValueError:
            return {}, commit
    try:
        return json.loads((Path(repo) / ".task-loop.json").read_text(encoding="utf-8")), ""
    except (OSError, ValueError):
        return {}, ""


def load_profile(data):
    """A parsed .task-loop.json as a RepoProfile; an unknown key or a wrong type exits, naming it. A retired key is said once."""
    try:
        return config.load(data, say_to=sys.stderr)
    except config.ConfigError as e:
        sys.exit("task-loop: %s" % e)


def profile_slots(repo):
    """The `slots` block of the repo's loop profile (.task-loop.json in the working tree)."""
    try:
        return load_profile(json.loads((Path(repo) / ".task-loop.json").read_text(encoding="utf-8"))).slots
    except (OSError, ValueError):
        return config.SlotsConfig()


def slot_dir(repo, name, cfg):
    root = cfg.dir
    return str(Path(root if os.path.isabs(root) else os.path.join(repo, root)) / name)


HOST = socket.gethostname().split(".")[0].lower()
DEFAULT_PRIO = slots_env.DEFAULT_PRIO
TICKET_POLL = slots_env.TICKET_POLL


def repo_key(repo):
    return "%s-%s" % (Path(repo).name, hashlib.sha1(str(repo).encode()).hexdigest()[:8])


def slot_env(repo, store=None, cfg=None):
    """The slot code's world (app/slots): this repo's bd, git, ticket line and take lock, and the effects it may cause."""
    return SlotEnv(
        repo=repo, repo_key=repo_key(repo), cfg=cfg or profile_slots(repo), store=store or bd_store(repo), git=RealSlotGit(),
        tickets=FileTickets(paths.ConfigDir(config_dir())), cfgdir=paths.ConfigDir(config_dir()), actor=actor(), host=HOST,
        take_lock=lambda: os_lock(config_dir() / "locks" / ("slot-take-%s.lock" % repo_key(repo)), "pid %d" % os.getpid()),
        busy=engine_busy, drop_engine_lock=drop_engine_lock, event=event, say=print,
        warn=lambda m: print(m, file=sys.stderr), pid=os.getpid(),
        run_setup=lambda argv, d: subprocess.run(argv, cwd=d, check=False).returncode,
        exclude_local=lambda r: exclude_local(r, ".slots/", ".task/"), now=now)


def cmd_slot(a):
    return slots_cli.run(slot_env(repo_root()), a)


def slot_beads(repo, store=None):
    return SlotPool(slot_env(repo, store)).beads()


def slot_bead(repo, name, store=None):
    return SlotPool(slot_env(repo, store)).bead(name)


def slot_of(repo, wt, store=None):
    """The slot whose worktree `wt` is, or ""."""
    return SlotPool(slot_env(repo, store)).name_of(wt)


def waiting_line(repo):
    """The live tickets (Ticket), first in line first; a dead waiter's ticket is removed."""
    return FileTickets(paths.ConfigDir(config_dir())).line(repo_key(repo))


def wait_slot(repo, cfg, why, bead="", stop=None, sleep=time.sleep, poll=None, on_wait=None, prio=DEFAULT_PRIO, store=None):
    """(name, dir, slot bead) once this waiter is first in line and a slot is free; None when stop() says so (see app/slots/line.py)."""
    return slots_line.wait_slot(slot_env(repo, store, cfg), why, bead, stop, sleep, poll, on_wait, prio)


def take_named_slot(repo, name, cfg, why, bead="", store=None):
    """(slot bead, "") when this session now holds slot `name`, or (None, why not)."""
    try:
        return SlotPool(slot_env(repo, store, cfg)).slot(name).take(why, bead), ""
    except SlotFail as e:
        return None, e.why


def release_slot(repo, name, bead=None, mine=False, force=False, store=None):
    """Frees slot `name` (see Slot.release); False when there is no such slot."""
    try:
        return SlotPool(slot_env(repo, store)).slot(name).release(bead, mine=mine, force=force)
    except SlotFail:
        return False


def prio_of(bead):
    """The priority number of a bead (0 = P0), DEFAULT_PRIO when it has none."""
    return bead.priority if bead and bead.priority is not None else DEFAULT_PRIO


def bead_priority(repo, bead_id, store=None):
    """The priority (0 = P0) of a bead, DEFAULT_PRIO when it cannot be read."""
    try:
        return prio_of(peek(store or bd_store(repo), bead_id))
    except SystemExit:  # no bd: it waits as a P2
        return DEFAULT_PRIO


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
    found += [slot_dir(repo, b.title.split()[-1], cfg) for b in (slot_beads(repo) if slots is None else slots)]
    seen, keep = set(), []
    for d in found:
        k = os.path.realpath(d)
        if k not in seen and os.path.realpath(repo) != k:
            seen.add(k)
            keep.append(d)
    return keep


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


# ---- processes: alive and start token, through stream-proc (/proc where there is one; no ps) ------------------------

def proc_start(pid):
    """The process's start token as text, "" when unknown."""
    return (sproc.proc_start(int(pid)) or "") if pid else ""


def proc_alive(pid, start=""):
    """The process `pid` lives, is no zombie, and (when `start` is known) is the one that started then."""
    return bool(pid) and sproc.alive(int(pid), start or None)


def pid_alive(pid):
    return bool(pid) and sproc.alive(int(pid))


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


def live_actors(repo, store=None):
    """Actors holding a live lease on any bead: a session that heartbeats is alive."""
    try:
        beads = (store or bd_store(repo)).find(BeadQuery(status="in_progress"))
    except BdFailure:
        return set()
    t = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
    return {b.assignee for b in beads if b.lease_expires_at >= t}


# ---- dashboard server ---------------------------------------------------------------------------------------------

def code_version():
    return dash_cli.code_version()


def dash_ports():
    """The Ports the dashboard process is started with (`--ports tl:dash_ports`) and the terminal's `tl ask` uses."""
    import dash_wiring
    import engine
    import reflect_digest
    return dash_wiring.make_ports(sys.modules[__name__], engine, reflect_digest)


def expected_binds():
    """The addresses the installed server would bind now."""
    return dash_bind.plan(None, None, dev=False)[0]


def is_dev_checkout():
    return dash_bind.is_dev_checkout(HERE)


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
    sproc.stop_pid(pid)
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
    kw["start_new_session"] = True
    kw["env"]["PYTHONPATH"] = os.pathsep.join([str(DASH.parents[1]), str(HERE), str(HERE / "_vendor")]
                                             + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    cmd = [sys.executable, "-m", "taskloop_dash", "--ports", "tl:dash_ports", "--port", str(port)] + (["--bind", bind] if bind else [])
    proc = sproc.spawn(cmd, **kw)
    for _ in range(40):
        if proc.poll() not in (None, 0):
            return None, "dashboard exited %s: %s" % (proc.poll(), log_tail() or "see " + str(config_dir() / "dash.log"))
        v = ping(port)
        if v:
            return v, ""
        time.sleep(0.25)
    return None, "dashboard did not start; see " + str(config_dir() / "dash.log")


def ask_store():
    return AskStore.at(ConfigDir(config_dir()))


def cmd_ask(a):
    """The owner's inbox and typed verbs (answer, hint, hold, override) from the terminal: src/taskloop/cli/asks.py over the AskStore. A
    bead's ask names its repo, and the bd of that repo takes the bead's state."""
    if a.op == "list":
        for b in ask_sweep("close"):  # throttled: the loop sweeps too
            print("closed the ask of %s: its bead is closed or gone" % b)
    return cli_asks.run(a, ask_store(), lambda repo: bd_store(repo or None), now, actor())


def ask_sweep(which, every=600):
    """The throttled sweeps over open asks (app/asks/sweeps.py): close those of closed or missing beads, park those unanswered in 3 days."""
    cfg = ConfigDir(config_dir())
    fn = ask_sweeps.close_stale if which == "close" else ask_sweeps.park_stale
    try:
        return fn(ask_store(), lambda repo: bd_store(repo), cfg.ask_marker("swept" if which == "close" else "parked"), now(), every)
    except SystemExit:  # no bd on this machine
        return []


def sweep_asks(say=print, cfg=None):
    """The loop's pass over asks: close the stale, park the unanswered, and shout about an answer no run used for 30 minutes (an engine
    fault, not the owner's). The three are throttled by marker files, so any caller may call it as often as it likes."""
    ask_sweep("close")
    ask_sweep("park")
    if cfg:
        ask_sweeps.reask_orphans(ask_store(), bd_store(), ConfigDir(config_dir()).ask_marker("orphans"), now(),
                                 cfg.pick_label or "", cfg.needs_info_label or "", say)
    ask_sweeps.shout(ask_store(), ConfigDir(config_dir()).ask_marker("unused"), now(), say)


def cmd_reflect(a):
    import reflect_digest
    return reflect_digest.cmd_reflect(a)


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
            sproc.spawn([sys.executable, str(Path(__file__).resolve()), "dash", "ensure"], stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
    return 0


# ---- doctor -------------------------------------------------------------------------------------------------------

def doctor_warnings(repo, source=None):
    """What is off in the repo's git setup for slots (tl-bxk.10.12), one line each."""
    out = []
    if git("config", "--get", "extensions.worktreeConfig", cwd=repo).lower() != "true":
        out.append("extensions.worktreeConfig is off in %s: per-worktree settings (core.worktree, core.bare) then live in "
                   "the one .git/config every slot shares, so a stray one redirects all slots; `git config "
                   "extensions.worktreeConfig true` gives each worktree its own config file." % repo)
    try:  # engine.checks[].inputs globs that match no tracked file would cache a green over changed code
        from taskloop.domain.checks.inputs import dead_globs
        if source is None:
            import engine
            source = engine.cfg_source(repo)
        profile, base, commit = source
        files = (git("ls-tree", "-r", "--name-only", "-z", commit, cwd=repo).split("\0") if commit
                 else git("ls-files", "-z", cwd=repo).split("\0"))
        files = [path for path in files if path]
        for c in profile.engine.checks:
            ins = [c.inputs] if isinstance(c.inputs, str) else list(c.inputs)
            for g in dead_globs(files, ins):
                out.append("check %s: inputs glob %s matches no tracked file, so the check is never cached; braces are "
                           "{a,b}, `*` stays in one folder, `**` crosses." % (c.id, g))
    except Exception:
        pass
    return out


def bead_lint_warnings(repo, store=None):
    """tl-f52: one line per open bead whose text cites material outside the repo (beadlint). [] when bd cannot be read."""
    from taskloop.domain.beads import matchers as beadlint
    try:
        beads = (store or bd_store(repo)).find(BeadQuery(status="open"))
    except (SystemExit, OSError, BdFailure):
        return []
    out = []
    for b in beads:
        if b.issue_type == "epic" or "slot" in b.labels:
            continue
        r = beadlint.refs(b, str(repo))
        if r:
            out.append("bead %s: %s: %s; inline the facts, or label it %s if this is a false positive" % (
                b.id, beadlint.REASON, "; ".join("%s %s" % (k, t[:60]) for k, t in r[:3]), beadlint.ESCAPE_LABEL))
    return out


def cmd_doctor(a):
    import engine
    repo = git("rev-parse", "--show-toplevel") or os.getcwd()
    if profiles.report(repo, config_dir() / "repos.json"):  # a bad profile is a red row of its repo, not a traceback
        return 1
    source = engine.cfg_source(repo)
    _, base, commit = source
    print("config: .task-loop.json from base %s at commit %s" % (base, commit) if commit else
          "config: .task-loop.json from working tree %s (base %s unresolved; no commit read)" % (repo, base))
    warns = doctor_warnings(repo, source)
    warns += bead_lint_warnings(repo)
    if sys.version_info >= (3, 12):  # src/ is written for the 3.12 floor; older interpreters skip it
        try:
            from taskloop import contracts  # the typed records, in src/ next to skills/
            print("contracts: %s" % Path(contracts.__file__).resolve().parent)
        except Exception as e:  # an install without src/
            warns.append("taskloop.contracts does not import: %s: %s" % (type(e).__name__, e))
    for w in warns:
        print("WARN " + w)
    if not warns:
        print("ok: no setup problems found in " + repo)
    return 0


# ---- main ---------------------------------------------------------------------------------------------------------

# ---- pin, rollback, cutover check ---------------------------------------------------------------------------------------
# pinned.json ({"task-loop": "0.23.38", "delegate": "0.40.1"}, each key optional) is written by `tl pin` and `tl rollback`
# only: the owner's override. The loop reads it, never writes it. A pin names a plugin cache dir that must exist.

PLUGINS = {"task-loop": ("iorlas-task-loop", "skills/task-loop/tl.py"), "delegate": ("iorlas-delegate", "skills/delegate/route.py")}


def claude_dir():
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def version_tuple(name):
    return tuple(int(x) for x in name.split(".")) if re.fullmatch(r"\d+(\.\d+)*", name) else None


def cache_dirs(key):
    """{version: dir} of the installed cache dirs of plugin `key` ("task-loop" | "delegate") that hold the plugin's main
    file: <claude dir>/plugins/cache/<marketplace>/<plugin>/<version>. Half-copied dirs and non-version names are left out."""
    plugin, mark = PLUGINS[key]
    out = {}
    for d in sorted((claude_dir() / "plugins" / "cache").glob("*/%s/*" % plugin)):
        if version_tuple(d.name) and (d / mark).is_file():
            out.setdefault(d.name, d)
    return out


def installed_version(key):
    """The version in installed_plugins.json (user scope) for plugin `key`, else ""."""
    plugin = PLUGINS[key][0]
    try:
        recs = json.loads((claude_dir() / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))["plugins"]
    except (OSError, ValueError, KeyError, TypeError):
        return ""
    for name, entries in recs.items():
        if name.split("@")[0] == plugin and isinstance(entries, list):
            for e in entries:
                if isinstance(e, dict) and e.get("scope") == "user":
                    return Path(str(e.get("installPath") or "")).name
    return ""


def pin_file():
    return config_dir() / "pinned.json"


def read_pin():
    try:
        pin = json.loads(pin_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return pin if isinstance(pin, dict) else {}


def write_pin(pin):
    f = pin_file()
    tmp = f.with_name(f.name + ".%d.tmp" % os.getpid())
    tmp.write_text(json.dumps(pin, indent=1), encoding="utf-8")
    os.replace(tmp, f)


def pinned_dir(key):
    """The cache dir `pinned.json` names for plugin `key`, None when it pins no version of it. A pin whose dir is gone gives
    a path that does not exist (the caller refuses; no fallback to another version)."""
    v = read_pin().get(key)
    if not v:
        return None
    return cache_dirs(key).get(str(v)) or claude_dir() / "plugins" / "cache" / "-" / PLUGINS[key][0] / str(v)


def cmd_pin(a):
    pin = read_pin()
    if a.clear:
        if a.version or a.delegate:
            sys.exit("tl: pin --clear takes no version")
        with contextlib.suppress(OSError):
            pin_file().unlink()
        print("PIN CLEARED" if pin else "no pin was set")
        return 0
    if not (a.version or a.delegate):
        print(json.dumps(pin) if pin else "no pin")
        return 0
    want = {"task-loop": a.version, "delegate": a.delegate}
    for key, v in want.items():
        if v and v not in cache_dirs(key):
            have = sorted(cache_dirs(key), key=version_tuple)
            print("tl: refused: %s %s is not installed under %s (installed: %s)"
                  % (PLUGINS[key][0], v, claude_dir() / "plugins" / "cache", ", ".join(have) or "none"), file=sys.stderr)
            return 2
    pin.update({k: v for k, v in want.items() if v})
    pin["pinned_at"] = now()
    write_pin(pin)
    print("PINNED " + " ".join("%s %s" % (k, pin[k]) for k in want if k in pin))
    return 0


def releases_behind(version, key="task-loop"):
    """How many installed releases of plugin `key` are newer than `version` (0 when it is the newest or unknown)."""
    mine = version_tuple(version)
    return sum(1 for v in cache_dirs(key) if mine and version_tuple(v) > mine)


def previous_version(key, current):
    below = [v for v in cache_dirs(key) if version_tuple(v) < version_tuple(current)]
    return max(below, key=version_tuple) if below else ""


def cmd_rollback(a):
    pin = read_pin()
    cur = pin.get("task-loop") or installed_version("task-loop") or max(cache_dirs("task-loop"), key=version_tuple, default="")
    if not cur:
        print("tl: refused: no task-loop install to roll back from", file=sys.stderr)
        return 2
    prev = previous_version("task-loop", cur)
    if not prev:
        print("tl: refused: no task-loop version older than %s is installed" % cur, file=sys.stderr)
        return 2
    a.version, a.delegate, a.clear = prev, "", False
    pin_delegate = pin.get("delegate") or installed_version("delegate")
    if pin_delegate in cache_dirs("delegate"):
        a.delegate = pin_delegate
    return cmd_pin(a)


def live_work():
    """What runs on this machine: ("loop"|"run", text) for every live loop and every busy engine lock of the registered repos."""
    import loop_env
    try:
        repos = [r for r in json.loads((config_dir() / "repos.json").read_text(encoding="utf-8")) if os.path.isdir(r)]
    except (OSError, ValueError):
        repos = []
    out = []
    for r in repos:
        for st in loop_env.live_loops(r):
            out.append(("loop", "loop pid %s on %s%s" % (st.pid, r, (" running " + st.bead) if st.bead else "")))
        for wt in [r] + worktrees(r, slots=None if shutil.which("bd") else []):  # slot dirs need bd
            busy = engine_busy(wt)
            if busy:
                out.append(("run", "run in %s: %s" % (wt, busy)))
    return out


def cmd_cutover(a):
    live = live_work()
    if a.json:
        print(json.dumps({"live": [{"kind": k, "what": w} for k, w in live]}))
    elif live:
        print("\n".join("LIVE %s" % w for _, w in live))
    else:
        print("CLEAR: no live loop or run")
    return 1 if live else 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="tl.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("actor")
    sp.add_parser("selftest", help="run one bead through the engine with a fake lane in a temp repo; exit 1 when it cannot")
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
    cli_asks.add_parsers(sp)
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
    p = sp.add_parser("reflect", help="turn the last day's run reflections into beads, one per recurring cause (tl-bl5)")
    p.add_argument("op", choices=["digest"])
    p.add_argument("--since", help="window start: 24h (default), a time, or epoch seconds")
    p.add_argument("--until", help="window end (default now)")
    p.add_argument("--dry-run", action="store_true", help="file nothing, write no state")
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
    p = sp.add_parser("pin", help="pin the plugin install loops and runs use (owner override; --clear removes the pin)")
    p.add_argument("version", nargs="?", help="task-loop version (a cache dir under ~/.claude/plugins/cache)")
    p.add_argument("--delegate", metavar="V", help="delegate version")
    p.add_argument("--clear", action="store_true")
    sp.add_parser("rollback", help="pin the previous task-loop version")
    p = sp.add_parser("cutover", help="cutover check: live runs and loops; exit 1 if any (docs/cutover.md)")
    p.add_argument("op", choices=["check"])
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
        route = sdelegate.find_route("", pinned_dir("delegate"), claude_dir() / "plugins" / "cache", sdelegate.installed_dir(claude_dir()))
        if not route:
            print("no delegate installed: nothing to feed")
            return 0
        r = sproc.capture([sys.executable, route, "status", "--claude-usage", a.windows, "--json"], None, None, 60.0)
        try:
            lane = json.loads(r.out)["lanes"]["CLAUDE_SUBSCRIPTION"]
            print("fed %s: Claude subscription 5h %s%%, week %s%%%s" % (route, lane.get("five"), lane.get("week"),
                                                                      ", OUT" if lane.get("out") else ""))
        except (ValueError, KeyError, TypeError):
            print("delegate did not take the reading (exit %d): %s" % (r.exit, (r.err or r.out)[-400:]))
            return 1
        return 0
    if a.cmd == "selftest":
        import selftest
        return selftest.cmd_selftest(a)
    if a.cmd in ("next", "loop", "stop"):
        import loop_env
        a.argv = list(argv) if argv is not None else sys.argv[1:]  # the loop re-execs itself with these
        return {"next": loop_env.cmd_next, "loop": loop_env.cmd_loop, "stop": loop_env.cmd_stop}[a.cmd](a)
    if a.cmd in ("report", "lost"):
        import report
        return {"report": report.cmd_report, "lost": report.cmd_lost}[a.cmd](a)
    if a.cmd == "trace":
        return cmd_trace(a)
    if a.cmd == "bd":
        return cmd_bd(a)
    return {"register": cmd_register, "claim": cmd_claim, "land": cmd_land, "close": cmd_close, "block": cmd_block, "slot": cmd_slot, "worktree": cmd_worktree,
            "dash": cmd_dash, "ask": cmd_ask, "answer": cmd_ask, "hint": cmd_ask, "hold": cmd_ask, "override": cmd_ask, "reflect": cmd_reflect, "hook": cmd_hook, "doctor": cmd_doctor, "land-lock": cmd_land_lock,
            "pin": cmd_pin, "rollback": cmd_rollback, "cutover": cmd_cutover}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
