"""Helpers for the engine's check rounds: what a check's result is a fact about (its inputs), what a check costs
(duration history), and which checks repeat another. Pure functions and small files; no engine state.

Cache policy (tl-7y6.7.7): a green result is remembered per check as a fact about the files in its `inputs` (InputKeys).
Widen `inputs`, never narrow: a glob that is too wide only costs a rerun, one that is too narrow serves a green over
code the check never saw, and a wrong cache hit is worse than a miss. A check with no `inputs` is keyed on the whole
tree and base; a glob that matches no tracked file switches the cache off for that round. Only a pass is stored, and
a plan's own (acceptance) check is never cached: it can read what git cannot see. What an acceptance copy of a repo
check reuses is that check's result of the same round (see canon), not an earlier one."""

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


def glob_re(g):
    """A repo path glob: ** crosses folders, * and ? stay in one, {a,b} is either."""
    out, i, depth = "", 0, 0
    while i < len(g):
        c = g[i]
        if g.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
            continue
        if c == "*":
            out, i = out + (".*" if g.startswith("**", i) else "[^/]*"), i + (2 if g.startswith("**", i) else 1)
            continue
        if c == "{":
            out, depth = out + "(?:", depth + 1
        elif c == "}" and depth:
            out, depth = out + ")", depth - 1
        elif c == "," and depth:
            out += "|"
        else:
            out += "[^/]" if c == "?" else re.escape(c)
        i += 1
    return re.compile(out + r"\Z")


def expand_braces(g):
    """['a/{b,c}/d'] -> ['a/b/d', 'a/c/d'] (nested braces too)."""
    m = re.search(r"\{([^{}]*)\}", g)
    if not m:
        return [g]
    return [x for alt in m.group(1).split(",") for x in expand_braces(g[:m.start()] + alt + g[m.end():])]


def literal_prefix(g):
    """The folder a glob alternative cannot leave: its path up to the last `/` before the first `*` or `?`."""
    head = re.split(r"[*?]", g, 1)[0]
    return head[:head.rfind("/") + 1]


def norm(cmd):
    return " ".join(str(cmd).split())


UNITY = re.compile(r"(?i)unity")  # the Unity group: repo checks that name Unity in their id or command (slot queue, minutes each)
SETUP = re.compile(r"^\s*mkdir(?:\s+-p)?\s+\S+\s*$")  # a wrapper's setup that changes nothing the command reads
TAIL_REDIRECT = re.compile(r"""\s*(?:\d*>>?\s*[^\s|&;<>]+|&>>?\s*[^\s|&;<>]+|\d*>&\d|\|\s*tee(?:\s+-a)?\s+[^\s|&;<>]+)\s*$""")


def canon(cmd):
    """What a command is a fact about: whitespace normalised, `mkdir -p dir &&` setup and trailing output redirections
    stripped when exactly one command is left (`mkdir -p e && just unity-tests > e/log` -> `just unity-tests`). An env prefix,
    arguments, a `!` or any other part stay: they change the run. Anything not split by `&&` alone is left as written."""
    segs = split_top(str(cmd))
    if not segs or any(sep not in ("&&", "") for _, sep in segs):
        return norm(cmd)
    keep = [seg for seg, _ in segs if seg.strip() and not SETUP.match(seg)]
    if len(keep) != 1:
        return norm(cmd)
    one = keep[0]
    while True:
        new = TAIL_REDIRECT.sub("", one)
        if new == one:
            return norm(one)
        one = new


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


def dead_globs(paths, globs):
    """The globs that match none of `paths` (tracked files): a typo, or a dialect the glob does not speak."""
    res = [(g, glob_re(g)) for g in globs]
    return [g for g, r in res if not any(r.match(p) for p in paths)]


def inputs_hash(files, globs, exclude=()):
    """Hash of the files in `files` ({path: "mode type sha"}) that match any glob (glob_re: `*` stays in one folder, `**` crosses, `{a,b}` is either). Empty when nothing matches: a check whose inputs are not in the tree has no fact to remember."""
    h = hashlib.sha1()
    n = 0
    res, ex = [glob_re(g) for g in globs], [glob_re(g) for g in exclude]
    for p in sorted(files):
        if any(r.match(p) for r in res) and not any(r.match(p) for r in ex):
            h.update(("%s\t%s\0" % (files[p], p)).encode("utf-8", "surrogateescape"))
            n += 1
    return h.hexdigest() if n else ""


ROOT_FILES = ("justfile", "Justfile", ".justfile", "*.lock", "packages-lock.json", "package-lock.json", "Directory.Packages.props",
              "Directory.Build.props", "Directory.Build.targets", "global.json", "nuget.config", ".task-loop.json")
BIG = 16 * 1024 * 1024  # an ignored input bigger than this counts by size, not content


def ignored_paths(wt, globs, exclude=()):
    """Ignored (untracked, gitignored) files in the worktree that match any glob (glob_re, as tracked files do). git lists
    only under the globs' literal folders (`client/Assets/{App,Core}/**` -> client/Assets/App/, client/Assets/Core/), so a
    Library/ the globs do not name is never walked; a glob with no literal folder lists the whole tree."""
    alts = [x for g in globs for x in expand_braces(g)]
    prefixes = sorted({literal_prefix(x) for x in alts})
    spec = [] if "" in prefixes else [":(literal)" + p for p in prefixes]
    if exclude:  # git prunes the walk at excluded folders where it can; the filter below is the rule
        spec = (spec or [":(literal)."]) + [":(exclude,glob)" + x for g in exclude for x in expand_braces(g)]
    r = subprocess.run(["git", "ls-files", "-z", "-o", "-i", "--exclude-standard"] + (["--"] + spec if spec else []),
                       cwd=wt, env=tl.git_env(wt), capture_output=True)
    paths = r.stdout.decode("utf-8", "surrogateescape").split("\0")
    res, ex = [glob_re(g) for g in globs], [glob_re(g) for g in exclude]
    return [p for p in paths if p and any(x.match(p) for x in res) and not any(x.match(p) for x in ex)]


def file_digest(path):
    h = hashlib.sha1()
    try:
        size = os.path.getsize(path)
        if size > BIG:
            return "big:%d" % size
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    except OSError:
        return "gone"
    return h.hexdigest()


class InputKeys:
    """A check's cache key for one tree: its command and env, the hash of the tree files matching its `inputs`, of the
    gitignored files matching them (their contents, read directly: tree_hash never sees them), and unless the check sets
    `"inputs_only": true` also of the justfile, lockfiles and .task-loop.json anywhere in the tree, and the base sha."""

    def __init__(self, wt, tree, base=""):
        self.wt, self.tree, self.base = wt, tree, base
        self.files = None
        self.ignored = {}  # globs -> [paths]

    def dead(self, c):
        """The check's `inputs` globs that match no tracked file in the tree."""
        if self.files is None:
            self.files = tree_files(self.wt, self.tree)
        return dead_globs(self.files, list(c.get("inputs") or []))

    def key(self, c):
        globs = list(c.get("inputs") or [])
        if not globs:
            return ""
        if self.files is None:
            self.files = tree_files(self.wt, self.tree)
        h = hashlib.sha1()
        excl = list(c.get("exclude") or [])
        ih = inputs_hash(self.files, globs, excl)
        gk = (tuple(globs), tuple(excl))
        if gk not in self.ignored:
            self.ignored[gk] = ignored_paths(self.wt, globs, excl)
        ign = sorted(self.ignored[gk])
        for p in ign:
            h.update(("I\t%s\t%s\0" % (p, file_digest(os.path.join(self.wt, p)))).encode("utf-8", "surrogateescape"))
        if not ih and not ign:
            return ""
        h.update(("%s\0%s\0%s\0%s" % (norm(c["cmd"]), ih, json.dumps(c.get("env") or {}, sort_keys=True), "\0".join(excl))).encode("utf-8", "surrogateescape"))
        if not c.get("inputs_only"):
            h.update(inputs_hash(self.files, ["*/" + g for g in ROOT_FILES] + list(ROOT_FILES)).encode())
            h.update(("\0" + self.base).encode())
        return h.hexdigest()


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

def order_by_cost(items, history, rank, deps=None, late=()):
    """Stable order by (late, expected cost, rank(item), declaration); `late` (ids of items) go after every other item whose
    dependencies allow it (the Unity group: cheap checks, acceptance included, get their verdict first). deps: {id(item): [items it must come after]}; an item
    waits for its dependencies (a check reading $TL_CHECK_LOG_X goes after X). Dependencies never loop forever: a
    cycle is broken by declaration order."""
    deps = deps or {}
    keyed = sorted(range(len(items)), key=lambda i: (id(items[i]) in late, expected_secs(items[i]["cmd"], history), rank(items[i]), i))
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


SETUP_WORDS = ('mkdir', 'echo', 'printf', 'export', 'true', 'test', '[', ':')  # no cd: another directory is another command
READ_WORDS = ('grep', 'egrep', 'fgrep', 'test', '[', 'wc', 'tail', 'head', 'cat')  # an extra part that only reads
TARGET = re.compile(r"""(?:\d*>>?|&>>?)\s*([^\s|&;<>]+)|\|\s*tee(?:\s+-a)?\s+([^\s|&;<>]+)""")


def reuse_log(outer, inner, log_var, wt=None):
    """`outer` with the segment that is exactly `inner` replaced by `cat "$log_var"` (same output redirections), or None.
    Only when: the segments are joined by `&&` alone (no `;`, newline, `||`, `&`); exactly one segment is the command, with
    nothing before it (no env prefix, `!`, args) and nothing after it but output redirections; the segments before it are
    setup (mkdir, echo...) and the ones after it only read: grep/test/wc/tail/head/cat with no substitution, whose file
    operands are the command's redirect targets (a path that exists in `wt` and is not a target refuses)."""
    segs = split_top(outer)
    if not segs or any(sep not in ("&&", "") for _, sep in segs):
        return None
    words = str(inner).split()
    pat = re.compile(r"^(\s*)" + r"\s+".join(map(re.escape, words)) + r"(?![\w-])(.*)$", re.S)
    hits, out, targets = 0, "", set()
    for seg, sep in segs:
        m = pat.match(seg)
        if m:
            if hits or not REDIRECTS.match(m.group(2)):
                return None
            hits += 1
            targets |= {a or b for a, b in TARGET.findall(m.group(2))}
            seg = '%scat "$%s"%s' % (m.group(1), log_var, m.group(2))
        elif contains_cmd(seg, inner, unquoted=True):
            return None
        elif not hits:
            if (seg.split() or ["true"])[0] not in SETUP_WORDS:
                return None
        else:
            toks = seg.split()
            if not toks or toks[0] not in READ_WORDS or "$(" in seg or "`" in seg or "<" in seg or ">" in seg:
                return None
            for t in toks[1:]:
                t = t.strip("'\"")
                if t in targets or t.startswith("-") or not t:
                    continue
                if t.startswith(("/", "./", "../", "~")) or (wt and os.path.exists(os.path.join(wt, t))):
                    return None
        out += seg + sep
    return out if hits else None


# --- activity of a running check ------------------------------------------------------------------------------------

def parse_cpu(text):
    """Seconds from ps's [[dd-]hh:]mm:ss[.ff]."""
    days, rest = (text.split("-", 1) if "-" in text else ("0", text))
    secs = 0.0
    for part in rest.split(":"):
        secs = secs * 60 + float(part)
    return secs + float(days) * 86400


def tree_cpu(root_pid):
    """{pid: cpu seconds} for the process tree under root_pid and every member of its group; {} when ps is missing."""
    out = tl.ps("-A", "-o", "pid=,ppid=,pgid=,time=")
    rows = {}
    for ln in (out or "").splitlines():
        f = ln.split()
        if len(f) == 4 and all(x.isdigit() for x in f[:3]):
            try:
                rows[int(f[0])] = (int(f[1]), int(f[2]), parse_cpu(f[3]))
            except ValueError:
                pass
    mine, todo = {root_pid}, [root_pid]
    while todo:
        cur = todo.pop()
        for k, (ppid, _, _) in rows.items():
            if ppid == cur and k not in mine:
                mine.add(k)
                todo.append(k)
    mine |= {k for k, (_, g, _) in rows.items() if g == root_pid}
    return {k: rows[k][2] for k in mine if k in rows}


def files_signature(wt):
    """(files, bytes, newest mtime) under the worktree, .git left out."""
    n = size = newest = 0
    for dp, dns, fns in os.walk(wt):
        dns[:] = [d for d in dns if d != ".git"]
        for f in fns:
            try:
                st = os.lstat(os.path.join(dp, f))
            except OSError:
                continue
            n += 1
            size += st.st_size
            newest = max(newest, st.st_mtime_ns)
    return (n, size, newest)


def activity(wt, root_pid, seen):
    """True when since the last call the tree under root_pid used CPU (or started a process) or a file under `wt` changed
    (a count, a size or an mtime). `seen` carries the last look; the first call only takes it (and counts as activity)."""
    cpu, sig = tree_cpu(root_pid), files_signature(wt)
    prev_cpu, prev_sig = seen.get("cpu") or {}, seen.get("files")
    seen["cpu"], seen["files"] = cpu, sig
    if prev_sig is None or sig != prev_sig:
        return True
    return any(k not in prev_cpu or v > prev_cpu[k] for k, v in cpu.items())
