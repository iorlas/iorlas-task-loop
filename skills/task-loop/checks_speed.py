"""Helpers for the engine's check rounds: what a check's result is a fact about (its inputs), what a check costs
(duration history), and which checks repeat another. Pure functions and small files; no engine state."""

import fnmatch
import hashlib
import json
import os
import re
import statistics
import subprocess
import tempfile
from pathlib import Path

import tl

CHEAP_S = 5.0  # a median under this counts as free: sub-second noise never reorders a round
KEEP_RUNS = 9  # durations kept per command


def norm(cmd):
    return " ".join(str(cmd).split())


# --- per-check input hash -------------------------------------------------------------------------------------------

def tree_files(wt, tree):
    """{path: "mode sha"} for a git tree, from `git ls-tree -r -z`."""
    r = subprocess.run(["git", "ls-tree", "-r", "-z", tree], cwd=wt, env=tl.git_env(wt), capture_output=True)
    out = {}
    for ent in r.stdout.decode("utf-8", "surrogateescape").split("\0"):
        meta, _, path = ent.partition("\t")
        if path:
            out[path] = meta
    return out


def inputs_hash(files, globs):
    """Hash of the files in `files` ({path: "mode type sha"}) that match any glob (fnmatch, as a check's `when`: `*`
    crosses `/`). Empty when nothing matches: a check whose inputs are not in the tree has no fact to remember."""
    h = hashlib.sha1()
    n = 0
    for p in sorted(files):
        if any(fnmatch.fnmatch(p, g) for g in globs):
            h.update(("%s\t%s\0" % (files[p], p)).encode("utf-8", "surrogateescape"))
            n += 1
    return h.hexdigest() if n else ""


def input_key(cmd, files, globs):
    """What a green result of `cmd` is a fact about: the command and the hash of its input files. "" = no key."""
    ih = inputs_hash(files, globs)
    return hashlib.sha1(("%s\0%s" % (norm(cmd), ih)).encode("utf-8", "surrogateescape")).hexdigest() if ih else ""


# --- duration history -----------------------------------------------------------------------------------------------

def repo_key(wt):
    """One name per repo, shared by its slots and worktrees: the origin url, else the common git dir."""
    env = tl.git_env(wt)

    def git(*a):
        r = subprocess.run(["git"] + list(a), cwd=wt, env=env, capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""
    ident = git("config", "--get", "remote.origin.url") or git("rev-parse", "--path-format=absolute", "--git-common-dir") or str(wt)
    return "%s-%s" % (re.sub(r"[^\w.-]+", "_", Path(ident.rstrip("/")).name)[:40] or "repo",
                      hashlib.sha1(ident.encode("utf-8", "surrogateescape")).hexdigest()[:10])


def durations_path(wt, config_dir=None):
    return Path(config_dir or tl.config_dir()) / "check-durations" / ("%s.json" % repo_key(wt))


def load_durations(wt, config_dir=None):
    """{normalized cmd: [secs, ...]}, newest last."""
    try:
        data = json.loads(durations_path(wt, config_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: [float(x) for x in v if isinstance(x, (int, float))] for k, v in data.items() if isinstance(v, list)} \
        if isinstance(data, dict) else {}


def record_durations(wt, runs, config_dir=None):
    """Add [(cmd, secs)] to the repo's history. Read-merge-replace, so slots writing at once lose at most one entry."""
    if not runs:
        return
    path = durations_path(wt, config_dir)
    data = load_durations(wt, config_dir)
    for cmd, secs in runs:
        data.setdefault(norm(cmd), []).append(round(float(secs), 1))
    data = {k: v[-KEEP_RUNS:] for k, v in data.items()}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, path)
    except OSError:
        pass


def expected_secs(cmd, history):
    """Median of earlier runs of the command; unknown = 0 (cheap), and anything under CHEAP_S is 0 too."""
    runs = history.get(norm(cmd))
    s = statistics.median(runs) if runs else 0.0
    return 0.0 if s < CHEAP_S else s


# --- order ----------------------------------------------------------------------------------------------------------

def order_by_cost(items, history, rank, deps=None):
    """Stable order by (expected cost, rank(item), declaration). deps: {id(item): [items it must come after]}; an item
    waits for its dependencies (a check reading $TL_CHECK_LOG_X goes after X). Dependencies never loop forever: a
    cycle is broken by declaration order."""
    deps = deps or {}
    keyed = sorted(range(len(items)), key=lambda i: (expected_secs(items[i]["cmd"], history), rank(items[i]), i))
    placed, out, left = set(), [], list(keyed)
    while left:
        for i in left:
            if all(id(d) in placed or d is items[i] for d in deps.get(id(items[i]), ())):
                break
        else:
            i = left[0]
        left.remove(i)
        placed.add(id(items[i]))
        out.append(items[i])
    return out


# --- a command inside another ---------------------------------------------------------------------------------------

def quoted_at(text, idx):
    """True when position idx of `text` sits inside a '...' or "..." span."""
    q, i = "", 0
    while i < idx:
        ch = text[i]
        if q:
            if ch == "\\" and q == '"':
                i += 1
            elif ch == q:
                q = ""
        elif ch == "\\":
            i += 1
        elif ch in "'\"":
            q = ch
        i += 1
    return bool(q)


def contains_cmd(outer, inner, unquoted=False):
    """True when `inner` (a whole command) appears in `outer` on word boundaries, whitespace-insensitive. unquoted: a
    match inside quotes (`echo 'just unity-tests'`) is text, not a command, and does not count."""
    words = str(inner).split()
    if not words or norm(outer) == norm(inner):
        return False
    for m in re.finditer(r"(?<![\w-])" + r"\s+".join(map(re.escape, words)) + r"(?![\w-])", str(outer)):
        if not unquoted or not quoted_at(str(outer), m.start()):
            return True
    return False


def split_top(cmd):
    """[(segment, separator)] cut at top-level `&&`, `;` and newlines; None when the command has a top-level `||`, a
    background `&`, or quoting/nesting this scan does not follow (then it is not split)."""
    segs, cur, i, depth, quote = [], "", 0, 0, ""
    while i < len(cmd):
        ch = cmd[i]
        if quote:
            cur += ch
            if ch == "\\" and quote == '"' and i + 1 < len(cmd):
                cur += cmd[i + 1]
                i += 1
            elif ch == quote:
                quote = ""
        elif ch == "\\" and i + 1 < len(cmd):
            cur += cmd[i:i + 2]
            i += 1
        elif ch in "'\"`":
            quote = ch
            cur += ch
        elif ch in "({":
            depth += 1
            cur += ch
        elif ch in ")}":
            depth -= 1
            cur += ch
        elif depth == 0 and cmd.startswith("&&", i):
            segs.append((cur, "&&"))
            cur, i = "", i + 1
        elif depth == 0 and cmd.startswith("||", i):
            return None
        elif depth == 0 and ch == "&" and not cmd.startswith(">&", i - 1) and not cmd.startswith("&>", i):
            return None
        elif depth == 0 and ch in ";\n":
            segs.append((cur, ch))
            cur = ""
        else:
            cur += ch
        i += 1
    if quote or depth:
        return None
    segs.append((cur, ""))
    return segs


REDIRECTS = re.compile(r"""^(?:\s*(?:\d*>>?\s*[^\s|&;<>]+|\d*>&\d|&>>?\s*[^\s|&;<>]+|\|\s*tee(?:\s+-a)?\s+[^\s|&;<>]+))*\s*$""")


SETUP_WORDS = ('mkdir', 'echo', 'printf', 'export', 'true', 'test', '[', 'cd', 'set', ':')


def reuse_log(outer, inner, log_var):
    """`outer` with the segment that is exactly `inner` (plus output redirections) replaced by `cat "$log_var"` with the
    same redirections, so the wrapper's own checks read the log of the run that already happened. None when no segment
    is exactly that (the inner command sits inside a subshell, an `if`, a pipe to something else...)."""
    segs = split_top(outer)
    if not segs:
        return None
    words = str(inner).split()
    pat = re.compile(r"^(\s*)" + r"\s+".join(map(re.escape, words)) + r"(?![\w-])(.*)$", re.S)
    hits, out = 0, ""
    for seg, sep in segs:
        m = pat.match(seg)
        if not hits and not m and (seg.split() or ["true"])[0] not in SETUP_WORDS:
            return None  # something before the command (rm, mv, a build) may clear what the command leaves behind
        if m and REDIRECTS.match(m.group(2)):
            hits += 1
            seg = '%scat "$%s"%s' % (m.group(1), log_var, m.group(2))
        elif contains_cmd(seg, inner, unquoted=True):
            return None
        out += seg + sep
    return out if hits else None
