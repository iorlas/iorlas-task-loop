"""Shell-text patterns of the plan-check lint: what a command reads, runs, sets as a limit. `import re` is allowed here only."""
import re
import shlex
from types import MappingProxyType

# a check that runs bd or reads the beads files proves the tracker, not the code: no writer can satisfy it (writers cannot run bd)
TRACKER_CHECK = re.compile(r"(?:^|[;&|(`!{]|\b(?:then|do|else|xargs|exec|command|env|time)\b)\s*bd(?=\s|$|[;&|)`])|(?<![\w-])\.beads\b")
CMD_LEAD = r"(?:^|[;&|(`!{]|\b(?:then|do|else|xargs|exec|command|env|time)\b)\s*"
PROC_SUBST = re.compile(r"<\(")
FILE_ARG = re.compile(r"(?:^|[;&|(]\s*)(?:test|\[)\s+-[fesr]\s+(\S+)|(?:^|[;&|(]\s*)(?:cat|bash|sh|node|python3?)\s+(?:-[^\smc]\S*\s+)*"
                      r"([^\s;&|<>$`'\"-]*[./]\S*)")
# python3 -I -m unittest tools.tests.test_x / python3 -I -m tools.x: -I (isolated mode) drops the cwd from sys.path, ModuleNotFoundError
ISOLATED_MODULE = re.compile(r"\bpython3?(?:\.\d+)?\s+(?:-[A-Za-z]+\s+)*-[A-Za-z]*I[A-Za-z]*\s+(?:-[A-Za-z]+\s+)*-m\s+"
                             r"(?:unittest\s+(?!discover\b)(?:-[A-Za-z]+\s+)*)?([A-Za-z_][\w]*(?:\.[\w]+)+)")
SHELL_STOP = frozenset({"if", "then", "else", "elif", "fi", "for", "while", "until", "do", "done", "case", "esac", "{", "}", "(", ")",
              "[[", "]]", "function", "select", "time", "!"})
TIMEOUT_MS = re.compile(r"timeout[_-]?ms\s*[=: ]\s*(\d+)", re.I)
TIMEOUT_MIN = re.compile(r"timeout[_-]?min(?:ute)?s?\s*[=: ]\s*(\d+(?:\.\d+)?)", re.I)
TIMEOUT_SEC = re.compile(r"timeout[_-]?sec(?:ond)?s?\s*[=: ]\s*(\d+(?:\.\d+)?)", re.I)
TIMEOUT_ANY = re.compile(r"(?<![\w-])(?:--timeout|-timeout|timeout)(?:=|\s+)(\d+(?:\.\d+)?)([smhd]?)(?![\w.])", re.I)
UNITY_RECIPE = re.compile(r"(?<![\w-])just\s+(unity-[\w-]+)(?![\w-])")
QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'")
CD = re.compile(r"(?:^|[;&|(\s])cd\s")
PATH_MAGIC = re.compile(r"[$*?{}~`]")
OPERATOR = re.compile(r"[;&|]+")
HEREDOC = re.compile(r"<<|\(\)\s*\{|\bfunction\s+\w|\bsource\b|^\s*\.\s")
ASSIGN = re.compile(r"\w+=.*")
SHELL_SYNTAX = re.compile(r"[$`(){}<>]|^\[")
BRACKETS = re.compile(r"[<>(){}]+")
BAD_WORD = re.compile(r"\bcd\b")
UNIT = MappingProxyType({"": 1 / 60.0, "s": 1 / 60.0, "m": 1.0, "h": 60.0, "d": 1440.0})


def bare(cmd: str) -> str:
    """The command with each quoted string emptied: a quoted mention is text, not a command."""
    return QUOTED.sub("''", cmd)


def reads_tracker(cmd: str) -> bool:
    return bool(TRACKER_CHECK.search(cmd))


def runs_command(cmd: str, whole: str) -> bool:
    """True when the plan check `cmd` runs the command `whole` as a command of its own (not as an argument)."""
    return bool(re.search(CMD_LEAD + r"\s+".join(map(re.escape, whole.split())) + r"(?=\s|$|[;&|)`])", cmd))


def has_proc_subst(cmd: str) -> bool:
    return bool(PROC_SUBST.search(bare(cmd)))


def isolated_module(cmd: str) -> str:
    """The module a `python -I -m` command names, else ''."""
    m = ISOLATED_MODULE.search(bare(cmd))
    return m.group(1) if m else ""


def has_cd(cmd: str) -> bool:
    return bool(CD.search(cmd))


def file_operands(cmd: str) -> list[str]:
    """The files `test -f`, `cat`, `bash`, `python3`... read: unquoted, as written."""
    return [(m.group(1) or m.group(2) or "").strip("\"'") for m in FILE_ARG.finditer(cmd)]


def is_plain_path(f: str) -> bool:
    """A file operand worth judging: no variable, glob, brace, home or URL in it, and not absolute."""
    return bool(f) and not PATH_MAGIC.search(f) and not f.startswith("/") and "://" not in f


def written_by(cmd: str, f: str) -> bool:
    """True when the command redirects its output to the file `f`."""
    return bool(re.search(rf">\s*{re.escape(f)}(?![\w./-])", cmd))


def unity_recipe(cmd: str) -> str:
    """The `unity-*` recipe a command runs through `just`, else ''."""
    m = UNITY_RECIPE.search(bare(cmd))
    return m.group(1) if m else ""


def shell_tokens(cmd: str) -> list[str]:
    """cmd split like a shell, operators (`;`, `&&`, `|`, `>`) apart; [] when the quoting does not close."""
    lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    lex.commenters = "#"
    try:
        return list(lex)
    except ValueError:
        return []


def is_operator(tok: str) -> bool:
    return bool(OPERATOR.fullmatch(tok))


def first_words(cmd: str) -> list[str]:
    """The command words of a plan check's simple commands: the first word of each command between `;`, `&&`, `||`, `|`,
    after env assignments, `!` and `time`. Stops at a compound command (if, for, a subshell, $(...)): nothing is claimed
    past it."""
    out: list[str] = []
    start = True
    if HEREDOC.search(cmd):  # a heredoc, a function, a sourced file: not judged
        return []
    for t in shell_tokens(cmd):
        if is_operator(t):
            start = True
            continue
        if not start:
            continue
        if ASSIGN.fullmatch(t) or t in ("!", "time", "command", "exec", "env", "builtin") or t.startswith("-"):
            continue
        if t in SHELL_STOP or SHELL_SYNTAX.search(t) or BRACKETS.fullmatch(t):
            return out
        out.append(t)
        start = False
    return out


def uses_cd(cmd: str) -> bool:
    return bool(BAD_WORD.search(cmd))


def own_timeouts(check: str) -> list[tuple[float, str]]:
    """[(minutes, the text)]: the time limits a check sets for itself: `timeout_ms 2400000`, `--timeout=40m`, `timeout 2400 cmd`,
    `-timeout_min 40`. A bare number is seconds."""
    out = [(float(m.group(1)) / 60000.0, m.group(0)) for m in TIMEOUT_MS.finditer(check)]
    out += [(float(m.group(1)), m.group(0)) for m in TIMEOUT_MIN.finditer(check)]
    out += [(float(m.group(1)) / 60.0, m.group(0)) for m in TIMEOUT_SEC.finditer(check)]
    out += [(float(m.group(1)) * UNIT[m.group(2).lower()], m.group(0)) for m in TIMEOUT_ANY.finditer(check)]
    return out


def just_recipe_calls(toks: list[str], plain_flags: frozenset[str]) -> list[str]:
    """The recipe name of each `just <recipe>` at the start of a command in the tokens; options that take a value are not judged."""
    out = []
    for k, t in enumerate(toks):
        if t == "just" and (k == 0 or is_operator(toks[k - 1])):
            after = toks[k + 1:k + 8]
            if any(x.startswith("-") and x not in plain_flags for x in after):
                continue
            rest = [x for x in after if not x.startswith("-")]
            if rest and re.fullmatch(r"[\w-]+", rest[0]):
                out.append(rest[0])
    return out
