"""Which shell commands only read (a refused read gets one retry), and a command's top-level parts (what a check may reuse).
Prose-free text matchers over command lines: the one place in the lane rules that uses `re`."""

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


SED_PRINT = re.compile(r"^\s*(?:\d+|\$)?(?:,\s*(?:\d+|\$))?\s*[pd]\s*$")  # sed -n 'N,Mp': the one script that only prints
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


def _part_reads(part: str) -> bool:
    try:
        w = shlex.split(part)
    except ValueError:
        return False
    if not w:
        return False
    head = Path(w[0]).name
    check = PART_CHECKS.get(head)
    return check(w) if check else head in READ_ONLY_WORDS


def _writes_or_hides(cmd: str) -> bool:
    """A redirection, a background job, a substitution or a newline: it writes, runs in the background or hides what it runs."""
    if "\n" in cmd or "\r" in cmd:
        return True
    bare = re.sub(r"'[^']*'|\"[^\"]*\"", "''", cmd).replace("2>&1", "").replace("2>/dev/null", "").replace(">/dev/null", "")
    return bool(re.search(r"[<>]|\|\|", bare) or re.search(r"(?<!&)&(?!&)", bare) or re.search(r"`|\$\(|\$\{", cmd))


def read_only_command(cmd: object) -> bool:
    """True when every part of a shell command only reads (head, cat, rg, grep, git log/diff/show, ls, find without -exec or
    -delete, a pipe or && chain of those): no redirection, no substitution, no heredoc, no newline or single &, no flag that
    writes or runs a program (sort -o, --output, rg --pre, git --ext-diff, a sed script beyond printing). Unsure is False
    (tl-bxk.10.21)."""
    if not isinstance(cmd, str) or not cmd.strip():
        return False
    try:
        words = shlex.split(cmd)
    except ValueError:
        return False
    if len(words) >= 3 and Path(words[0]).name in ("zsh", "bash", "sh") and words[1] in ("-c", "-lc", "-ic", "-l", "-cl"):
        return len(words) == 3 and read_only_command(words[2])  # the payload of `/bin/zsh -lc "..."`, and nothing after it
    if _writes_or_hides(cmd) or split_top(cmd) is None:
        return False
    return all(_part_reads(part) for part in re.split(r"\s*(?:\|\||\||&&|;)\s*", cmd))


def split_top(cmd: str) -> list[tuple[str, str]] | None:
    """A shell command's top-level parts and the `&&` or `;` after each, or None when quoting or nesting makes it
    unclear (then nothing is reused)."""
    parts: list[str] = []
    sep: list[str] = []
    cur, depth, q, i = "", 0, "", 0
    while i < len(cmd):
        ch = cmd[i]
        if q:
            if ch == "\\" and q == '"' and i + 1 < len(cmd):
                cur += cmd[i : i + 2]
                i += 2
                continue
            if ch == q:
                q = ""
        elif ch in "'\"":
            q = ch
        elif ch == "`":
            return None
        elif ch in "({":
            depth += 1
        elif ch in ")}":
            depth -= 1
        elif depth == 0 and (cmd.startswith("&&", i) or ch == ";"):
            parts.append(cur)
            sep.append("&&" if ch == "&" else ";")
            cur, i = "", i + (2 if ch == "&" else 1)
            continue
        cur += ch
        i += 1
    if q or depth:
        return None
    parts.append(cur)
    return list(zip(parts, [*sep, ""], strict=False))
