"""Every regular expression the checks need over text: globs, command text, a check's output. The one place in domain/checks
that imports `re` (rule: import re only in domain/**/matchers.py)."""
import re
from collections.abc import Callable

from taskloop.domain.checks.names import norm
from taskloop.domain.checks.shellsplit import quoted_at, split_top

# -- globs: ** crosses folders, * and ? stay in one, {a,b} is either --------------------------------------------------


def glob_re(g: str) -> re.Pattern[str]:
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


def expand_braces(g: str) -> list[str]:
    """['a/{b,c}/d'] -> ['a/b/d', 'a/c/d'] (nested braces too)."""
    m = re.search(r"\{([^{}]*)\}", g)
    if not m:
        return [g]
    return [x for alt in m.group(1).split(",") for x in expand_braces(g[:m.start()] + alt + g[m.end():])]


def literal_prefix(g: str) -> str:
    """The folder a glob alternative cannot leave: its path up to the last `/` before the first `*` or `?`."""
    head = re.split(r"[*?]", g, maxsplit=1)[0]
    return head[:head.rfind("/") + 1]


# -- command text -------------------------------------------------------------------------------------------------------
UNITY = re.compile(r"(?i)unity")  # the Unity group: repo checks that name Unity in their id or command (slot queue, minutes each)
SETUP = re.compile(r"^\s*mkdir(?:\s+-p)?\s+\S+\s*$")  # a wrapper's setup that changes nothing the command reads
TAIL_REDIRECT = re.compile(r"""\s*(?:\d*>>?\s*[^\s|&;<>]+|&>>?\s*[^\s|&;<>]+|\d*>&\d|\|\s*tee(?:\s+-a)?\s+[^\s|&;<>]+)\s*$""")
REDIRECTS = re.compile(r"""^(?:\s*(?:\d*>>?\s*[^\s|&;<>]+|\d*>&\d|&>>?\s*[^\s|&;<>]+|\|\s*tee(?:\s+-a)?\s+[^\s|&;<>]+))*\s*$""")
TARGET = re.compile(r"""(?:\d*>>?|&>>?)\s*([^\s|&;<>]+)|\|\s*tee(?:\s+-a)?\s+([^\s|&;<>]+)""")
SETUP_WORDS = ("mkdir", "echo", "printf", "export", "true", "test", "[", ":")  # no cd: another directory is another command
READ_WORDS = ("grep", "egrep", "fgrep", "test", "[", "wc", "tail", "head", "cat")  # an extra part that only reads
ENV_REF = re.compile(r"TL_CHECK_(?:LOG|RC)_(\w+)")
CONFLICT_BUILD = re.compile(r"(?i)(?<![a-z])(build|compile)(?![a-z])")  # a repo check a conflict fix still runs
SLOW_CMD = re.compile(r"(?i)(?<![a-z])(unity|play|test[-_]all|check|build|dotnet)")


def is_unity(text: str) -> bool:
    return bool(UNITY.search(text))


def is_build(text: str) -> bool:
    return bool(CONFLICT_BUILD.search(text))


def looks_slow(cmd: str) -> bool:
    """A command nobody has timed that is named like a Unity, play, full test, check or build run."""
    return bool(SLOW_CMD.search(cmd))


def env_refs(cmd: str) -> list[str]:
    """The mangled ids of the checks whose log or exit code the command reads, once each."""
    return list(dict.fromkeys(ENV_REF.findall(cmd)))


def canon(cmd: str) -> str:
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


def mentions_cmd(outer: str, inner: str) -> bool:
    """True when `inner` (a whole command) appears in `outer` on word boundaries, whitespace-insensitive."""
    words = str(inner).split()
    return bool(words) and bool(re.search(r"(?<![\w-])" + r"\s+".join(map(re.escape, words)) + r"(?![\w-])", str(outer)))


def contains_cmd(outer: str, inner: str, unquoted: bool = False) -> bool:
    """True when `inner` (a whole command) appears in `outer` on word boundaries, whitespace-insensitive. unquoted: a
    match inside quotes (`echo 'just unity-tests'`) is text, not a command, and does not count."""
    words = str(inner).split()
    if not words or norm(outer) == norm(inner):
        return False
    for m in re.finditer(r"(?<![\w-])" + r"\s+".join(map(re.escape, words)) + r"(?![\w-])", str(outer)):
        if not unquoted or not quoted_at(str(outer), m.start()):
            return True
    return False


def _reads_only(seg: str, targets: set[str], exists: Callable[[str], bool]) -> bool:
    """A segment after the command that only reads what the command wrote (grep/test/wc/tail/head/cat)."""
    toks = seg.split()
    if not toks or toks[0] not in READ_WORDS or "$(" in seg or "`" in seg or "<" in seg or ">" in seg:
        return False
    for word in toks[1:]:
        t = word.strip("'\"")
        if t in targets or t.startswith("-") or not t:
            continue
        if t.startswith(("/", "./", "../", "~")) or exists(t):
            return False
    return True


def reuse_log(outer: str, inner: str, log_var: str, exists: Callable[[str], bool]) -> str | None:
    """`outer` with the segment that is exactly `inner` replaced by `cat "$log_var"` (same output redirections), or None.
    Only when: the segments are joined by `&&` alone (no `;`, newline, `||`, `&`); exactly one segment is the command, with
    nothing before it (no env prefix, `!`, args) and nothing after it but output redirections; the segments before it are
    setup (mkdir, echo...) and the ones after it only read: grep/test/wc/tail/head/cat with no substitution, whose file
    operands are the command's redirect targets (a path that `exists` and is not a target refuses)."""
    segs = split_top(outer)
    if not segs or any(sep not in ("&&", "") for _, sep in segs):
        return None
    pat = re.compile(r"^(\s*)" + r"\s+".join(map(re.escape, str(inner).split())) + r"(?![\w-])(.*)$", re.S)
    hits, out, targets = 0, "", set()
    for seg, sep in segs:
        m = pat.match(seg)
        if m:
            if hits or not REDIRECTS.match(m.group(2)):
                return None
            hits += 1
            targets |= {a or b for a, b in TARGET.findall(m.group(2))}
            out += f'{m.group(1)}cat "${log_var}"{m.group(2)}{sep}'
            continue
        elif contains_cmd(seg, inner, unquoted=True):
            return None
        elif not hits:
            if (seg.split() or ["true"])[0] not in SETUP_WORDS:
                return None
        elif not _reads_only(seg, targets, exists):
            return None
        out += seg + sep
    return out if hits else None


# -- a check's output ---------------------------------------------------------------------------------------------------
STALE_TREE = re.compile(r"does not contain recipe|This checkout has no |no recipe (?:named|called)|Justfile does not contain", re.I)
COMPILE_FAIL = re.compile(r"error CS(?!0006\b|2001\b)\d+|SyntaxError")
IMPORT_RACE = re.compile(r"Library/|Temp/|asset import|importing asset|refresh", re.I)
LOCK_FAIL = re.compile(r"another Unity instance|Multiple Unity instances|It looks like another Unity instance is running", re.I)
LOCK_FILE = re.compile(r"(\S*Temp/UnityLockfile)")
SLOT_WAIT = re.compile(r"\bgot slot \S+ after (\d+) ?s\b")
CS_ERROR = re.compile(r"error CS\d+")
ELLIPSIS = re.compile(r"\.\.\.|\u2026")
SAFE_NAME = re.compile(r"[^\w.-]+")
TIMING = re.compile(r"\[\d+ ?m?s\]|\b\d+(?:\.\d+)?\s?(?:ms|s|sec|secs|seconds|min|mins)\b", re.I)


def failure_kind(text: str) -> str:
    """'lock' (an editor or project lock: wait, then rerun), 'deterministic' (a CS compile error or SyntaxError: a rerun
    fails the same way), 'import' (the same, but the log mentions Library/, Temp/ or an asset import: retry once anyway),
    else 'flaky' (today's retry)."""
    if LOCK_FAIL.search(text):
        return "lock"
    if COMPILE_FAIL.search(text):
        return "import" if IMPORT_RACE.search(text) else "deterministic"
    return "flaky"


def stale_tree(tail: str) -> str:
    """The words of the last output that say the tree is older than the config it runs, else ''."""
    m = STALE_TREE.search(tail[-500:])
    return m.group(0) if m else ""


def lock_files(text: str) -> list[str]:
    """The Unity lockfile paths a check's output names."""
    return LOCK_FILE.findall(text)


def slot_wait_secs(text: str) -> int:
    """Seconds a check's output says it queued for a Unity slot, all waits together."""
    return sum(int(m.group(1)) for m in SLOT_WAIT.finditer(text or ""))


def cs_error_lines(text: str, n: int = 20) -> list[str]:
    """The first n lines of `text` that are C# compile errors."""
    return [ln.strip() for ln in text.splitlines() if CS_ERROR.search(ln)][:n]


def output_signature(text: str, lines: int = 8) -> str:
    """What a red check's output says, whatever time it took: its last lines with the durations cut out."""
    rows = [ln.strip() for ln in str(text).splitlines() if ln.strip()][-lines:]
    return "\n".join(TIMING.sub("", r) for r in rows)


def names_shortened(said: str, mine: str) -> bool:
    """True when a writer's shortened spelling of a command (`...` for what it cut, or a stretch most of the command's length) is `mine`."""
    if ELLIPSIS.search(said):
        parts = [x.strip() for x in ELLIPSIS.split(said) if len(x.strip()) >= 6]
        at = 0
        for part in parts:
            at = mine.find(part, at)
            if at < 0:
                return False
            at += len(part)
        return bool(parts)
    return len(said) >= 20 and (said in mine or mine in said) and min(len(said), len(mine)) >= 0.8 * max(len(said), len(mine))


def safe_name(check_id: str, width: int = 40) -> str:
    """A check's id as a file name part."""
    return SAFE_NAME.sub("_", check_id)[:width]


# -- trimming a log ------------------------------------------------------------------------------------------------------
FAIL_LINE = re.compile(r"(?i)fail|error|assert|traceback|exception|panic|fatal|\bnot ok\b|\bexpected\b|\bbut was\b|✗|✘|: E\b|^E\s")
NOISE_LINE = re.compile(r"(?i)\b0 errors?\b|\b0 error\(s\)|\b0 fail\w*|\bfail\w*[:=] ?0\b|\berrors?[:=] ?0\b|"
                        r"\bwarning [A-Z]+\d+:|\bwarn(?:ing)?:")
NAME_LINE = re.compile(
    r"^\s*(?:FAIL(?:ED)?\b|ERROR\b|Failed\b|\[FAIL\]|not ok\b|\d+\) )|^_{2,} .+ _{2,}$|^=+ (?:FAILURES|ERRORS) =+|"
    r"\berror [A-Za-z]*\d+|: error\b|^\s*Traceback \(|\bfailed\b.*\[\d+ ?m?s\]|\bFAILED \(")
NOTABLE = re.compile(r"(?i)\b(skip|skipped|steps run|passed|failed|warnings?|errors?)\b")


def is_failure(row: str) -> bool:
    return bool(FAIL_LINE.search(row))


def is_noise(row: str) -> bool:
    return bool(NOISE_LINE.search(row))


def is_name(row: str) -> bool:
    return bool(NAME_LINE.search(row))


def is_notable(row: str) -> bool:
    return bool(NOTABLE.search(row))
