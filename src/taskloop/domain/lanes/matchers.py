"""Which worker commands only read (a refused read gets one retry). A command with any shell operator is not judged, so no
shell grammar is parsed here: shlex words and a per-program table. The one place in the lane rules that uses `re`."""

import re
import shlex
from pathlib import Path
from typing import Final

READ_ONLY_WORDS: Final = {
    "head",
    "tail",
    "cat",
    "rg",
    "grep",
    "egrep",
    "fgrep",
    "ls",
    "wc",
    "sort",
    "uniq",
    "nl",
    "cut",
    "tr",
    "stat",
    "file",
    "diff",
    "cmp",
    "basename",
    "dirname",
    "pwd",
    "echo",
    "printf",
    "true",
    "test",
    "[",
}
READ_ONLY_GIT: Final = {
    "log",
    "diff",
    "show",
    "status",
    "rev-parse",
    "ls-files",
    "ls-tree",
    "grep",
    "blame",
    "cat-file",
    "describe",
    "shortlog",
    "branch",
    "rev-list",
    "name-rev",
    "merge-base",
}
FIND_WRITES: Final = {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"}


SED_PRINT: Final = re.compile(r"^\s*(?:\d+|\$)?(?:,\s*(?:\d+|\$))?\s*[pd]\s*$")  # sed -n 'N,Mp': the one script that only prints
GIT_BAD = ("--output", "--ext-diff", "--open-files-in-pager", "-O", "-c", "-C", "--git-dir", "--work-tree", "--exec-path", "--textconv")


def _git_reads(w: list[str]) -> bool:
    if any(x == f or x.startswith(f + "=") for x in w[1:] for f in GIT_BAD):
        return False
    rest = [x for x in w[1:] if not x.startswith("-")]
    return bool(rest) and rest[0] in READ_ONLY_GIT and not (rest[0] == "branch" and len(rest) > 1)


def _find_reads(w: list[str]) -> bool:
    return not any(x in FIND_WRITES for x in w)


def _sed_reads(w: list[str]) -> bool:
    scripts = [x for x in w[1:] if not x.startswith("-")]
    writes = any(x.startswith("-i") or x == "--in-place" or x in ("-f", "-e", "--file", "--expression") for x in w[1:])
    return "-n" in w and not writes and bool(scripts) and bool(SED_PRINT.match(scripts[0]))


def _sort_reads(w: list[str]) -> bool:
    return not any(
        x == "-o" or x.startswith("--output") or (x.startswith("-") and not x.startswith("--") and "o" in x[1:] and not x[1:].isdigit())
        for x in w[1:]
    )


def _rg_reads(w: list[str]) -> bool:
    return not any(x == "--pre" or x.startswith("--pre=") or x.startswith("--pre-glob") for x in w[1:])


PART_CHECKS: Final = {"git": _git_reads, "find": _find_reads, "sed": _sed_reads, "sort": _sort_reads, "rg": _rg_reads}


def _argv_reads(w: list[str]) -> bool:
    if not w:
        return False
    head = Path(w[0]).name
    check = PART_CHECKS.get(head)
    return check(w) if check else head in READ_ONLY_WORDS


def read_only_command(cmd: object) -> bool:
    """True when a worker's shell command is one simple read-only program call (head, cat, rg, grep, git log/diff/show, ls, find
    without -exec or -delete): no pipe, `&&`, `;`, redirection, substitution, heredoc or background `&` (each is an operator word
    to shlex, and the command is refused), no flag that writes or runs a program (sort -o, --output, rg --pre, git --ext-diff, a
    sed script beyond printing). The payload of `/bin/zsh -lc "..."` is judged alone. Unsure is False (tl-bxk.10.21)."""
    if not isinstance(cmd, str) or not cmd.strip():
        return False
    lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
    lex.whitespace_split = False
    try:
        words = list(lex)
    except ValueError:
        return False
    if len(words) >= 3 and Path(words[0]).name in ("zsh", "bash", "sh") and words[1] in ("-c", "-lc", "-ic", "-l", "-cl"):
        return len(words) == 3 and read_only_command(words[2])  # the payload of `/bin/zsh -lc "..."`, and nothing after it
    if any(re.fullmatch(r"[;&|<>()]+", x) for x in words) or any(c in cmd for c in ("`", "$(", "${", "\n", "\r")):
        return False
    return _argv_reads(words)
