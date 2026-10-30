"""Command patterns of the plan-check lint over argv lists: what a check runs, reads, sets as a limit. `import re` is allowed here only."""
import contextlib
import re
import shlex
from collections.abc import Sequence
from types import MappingProxyType
from typing import Final

from taskloop.contracts.argv import OPERATORS, SHELL_FLAGS, SHELLS

# a check that runs bd or reads the beads files proves the tracker, not the code: no writer can satisfy it (writers cannot run bd)
BEADS_DIR: Final = re.compile(r"(?<![\w-])\.beads\b")
WRAPPERS: Final = frozenset({"env", "command", "exec", "time", "xargs", "nice"})
ASSIGN: Final = re.compile(r"\w+=.*")
PYTHON: Final = re.compile(r"python3?(?:\.\d+)?")
ISOLATED_FLAG: Final = re.compile(r"-[A-Za-z]*I[A-Za-z]*")
DOTTED: Final = re.compile(r"[A-Za-z_]\w*(?:\.\w+)+")
FILE_READERS: Final = frozenset({"cat", "bash", "sh", "node", "python", "python3"})
TEST_FLAGS: Final = frozenset({"-f", "-e", "-s", "-r"})
RECIPE: Final = re.compile(r"[\w-]+")
PATH_MAGIC: Final = re.compile(r"[$*?{}~`]")
TIMEOUT_MS: Final = re.compile(r"timeout[_-]?ms\s*[=: ]\s*(\d+)", re.I)
TIMEOUT_MIN: Final = re.compile(r"timeout[_-]?min(?:ute)?s?\s*[=: ]\s*(\d+(?:\.\d+)?)", re.I)
TIMEOUT_SEC: Final = re.compile(r"timeout[_-]?sec(?:ond)?s?\s*[=: ]\s*(\d+(?:\.\d+)?)", re.I)
TIMEOUT_ANY: Final = re.compile(r"(?<![\w-])(?:--timeout|-timeout|timeout)(?:=|\s+)(\d+(?:\.\d+)?)([smhd]?)(?![\w.])", re.I)
UNIT: Final = MappingProxyType({"": 1 / 60.0, "s": 1 / 60.0, "m": 1.0, "h": 60.0, "d": 1440.0})


def head(argv: Sequence[str]) -> list[str]:
    """The argv without its wrappers (`env X=1 time nice`), so its first word is the program that really runs."""
    i = 0
    while i < len(argv) and (argv[i] in WRAPPERS or ASSIGN.fullmatch(argv[i])
                             or (i and argv[i - 1] in WRAPPERS and argv[i].startswith("-"))):
        i += 1
    return list(argv[i:])


def reads_tracker(argv: Sequence[str]) -> bool:
    h = head(argv)
    return bool(h and h[0] == "bd") or any(BEADS_DIR.search(a) for a in argv)


def runs_command(argv: Sequence[str], whole: Sequence[str]) -> bool:
    """True when the check runs the command `whole` as its own program and arguments (wrappers aside), not as an argument."""
    h = head(argv)
    return bool(whole) and h[:len(whole)] == list(whole)


def contains_argv(outer: Sequence[str], inner: Sequence[str]) -> bool:
    """True when `inner` appears in `outer` as a run of whole words."""
    n = len(inner)
    return n > 0 and any(list(outer[i:i + n]) == list(inner) for i in range(len(outer) - n + 1))


def commands(argv: Sequence[str]) -> list[list[str]]:
    """The simple commands an argv chains: split at `&&`, `;`, `|`, a redirect or a subshell paren, and the string a shell runs
    with `-c` read the same way. A word inside quotes (an echo's text) is no command."""
    out: list[list[str]] = [[]]
    for w in argv:
        if w in OPERATORS:
            out.append([])
        else:
            out[-1].append(w)
    for c in list(out):
        h = head(c)
        if len(h) > 2 and h[0].rsplit("/", maxsplit=1)[-1] in SHELLS and h[1] in SHELL_FLAGS:
            lex = shlex.shlex(h[2], posix=True, punctuation_chars=True)
            lex.whitespace_split = True
            with contextlib.suppress(ValueError):  # an unbalanced quote: the shell would not run it either
                out += commands(list(lex))
    return [c for c in out if c]


def just_target(argv: Sequence[str], plain_flags: frozenset[str]) -> str:
    """The recipe a `just ... <recipe> [args]` command runs, whatever its arguments, else ''."""
    h = head(argv)
    if not h or h[0] != "just":
        return ""
    rest = [x for x in h[1:] if x not in plain_flags]
    return rest[0] if rest and RECIPE.fullmatch(rest[0]) else ""


def runs_again(argv: Sequence[str], inner: Sequence[str], plain_flags: frozenset[str]) -> bool:
    """True when some command the argv chains runs the argv `inner`, or, when `inner` is a bare `just <recipe>`, that recipe with any
    arguments."""
    recipe = just_target(inner, plain_flags) if len(inner) == 2 else ""
    return any(runs_command(c, inner) or (recipe and just_target(c, plain_flags) == recipe) for c in commands(argv))


def isolated_module(argv: Sequence[str]) -> str:
    """The module a `python -I -m` command names, else ''."""
    h = head(argv)
    if not h or not PYTHON.fullmatch(h[0].rsplit("/", maxsplit=1)[-1]) or "-m" not in h:
        return ""
    at = h.index("-m")
    if not any(ISOLATED_FLAG.fullmatch(x) for x in h[1:at]):
        return ""
    rest = h[at + 1:]
    if rest[:1] == ["unittest"]:
        rest = [x for x in rest[1:] if not x.startswith("-")][:1]
        return rest[0] if rest and rest[0] != "discover" and DOTTED.fullmatch(rest[0]) else ""
    return rest[0] if rest and DOTTED.fullmatch(rest[0]) else ""


def file_operands(argv: Sequence[str]) -> list[str]:
    """The files `test -f`, `cat`, `bash`, `python3`... read, as written."""
    h = head(argv)
    if not h:
        return []
    if h[0] in ("test", "["):
        return [h[i + 1] for i, x in enumerate(h[:-1]) if x in TEST_FLAGS]
    if h[0] not in FILE_READERS:
        return []
    for x in h[1:]:
        if x in ("-m", "-c"):
            return []
        if not x.startswith("-"):
            return [x] if ("." in x or "/" in x) else []
    return []


def is_plain_path(f: str) -> bool:
    """A file operand worth judging: no variable, glob, brace, home or URL in it, and not absolute."""
    return bool(f) and not PATH_MAGIC.search(f) and not f.startswith("/") and "://" not in f


def just_recipe(argv: Sequence[str], plain_flags: frozenset[str]) -> str:
    """The recipe name of a `just <recipe>` check, else ''; options that take a value are not judged."""
    h = head(argv)
    if not h or h[0] != "just":
        return ""
    after = h[1:8]
    if any(x.startswith("-") and x not in plain_flags for x in after):
        return ""
    rest = [x for x in after if not x.startswith("-")]
    return rest[0] if rest and RECIPE.fullmatch(rest[0]) else ""


def own_timeouts(check: str) -> list[tuple[float, str]]:
    """[(minutes, the text)]: the time limits a check sets for itself: `timeout_ms 2400000`, `--timeout=40m`, `timeout 2400 cmd`,
    `-timeout_min 40`. A bare number is seconds."""
    out = [(float(m.group(1)) / 60000.0, m.group(0)) for m in TIMEOUT_MS.finditer(check)]
    out += [(float(m.group(1)), m.group(0)) for m in TIMEOUT_MIN.finditer(check)]
    out += [(float(m.group(1)) / 60.0, m.group(0)) for m in TIMEOUT_SEC.finditer(check)]
    out += [(float(m.group(1)) * UNIT[m.group(2).lower()], m.group(0)) for m in TIMEOUT_ANY.finditer(check)]
    return out
