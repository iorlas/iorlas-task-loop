"""The quote-aware lexer: shell text in, simple commands out. Stdlib only, never raises.

It follows bash for the parts a guard needs: single and double quotes, backslash, `# comment`, the
separators `| || & && ; ;;` newline and `( ) ` ` $(`, redirects with an optional fd, and here-documents.
It does not expand variables, globs or `$'...'`; a line using `$'...'` is unparsable (None).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_SPACE = " \t"
_STOP = set(" \t\n;|&()<>`")
_DQ_ESCAPES = set('$`"\\')
_REDIRECT_OPS = ("<<<", "<<-", ">>", ">&", ">|", "<<", "<&", "<>", ">", "<")


@dataclass
class Raw:
    """A simple command as lexed: words, redirects (`op`, `target`), and the here-document text feeding it."""

    words: list[str] = field(default_factory=list)
    redirects: list[tuple[str, str]] = field(default_factory=list)
    stdin: str | None = None

    def empty(self) -> bool:
        return not (self.words or self.redirects)


@dataclass
class Lexed:
    commands: list[Raw]
    bodies: list[tuple[int, int]]  # here-document spans (body and its terminator line) in the text


def _read_dquoted(text: str, i: int) -> tuple[str, int] | None:
    """The inside of a double-quoted string whose opening quote ends at `i`, and the index after the closing quote."""
    out: list[str] = []
    n = len(text)
    while i < n:
        d = text[i]
        if d == '"':
            return "".join(out), i + 1
        if d == "\\" and i + 1 < n and text[i + 1] in _DQ_ESCAPES | {"\n"}:
            if text[i + 1] != "\n":
                out.append(text[i + 1])
            i += 2
        else:
            out.append(d)
            i += 1
    return None


def _read_word(text: str, i: int) -> tuple[str, bool, int] | None:
    """The word starting at `i`: (value, any part quoted, index after), or None when a quote is never closed."""
    out: list[str] = []
    quoted = False
    n = len(text)
    while i < n:
        c = text[i]
        if c in _STOP or (c == "$" and text[i + 1 : i + 2] == "("):
            break
        if c == "\\":
            quoted = True
            if i + 1 >= n:
                out.append("\\")
                i += 1
            elif text[i + 1] == "\n":
                i += 2
            else:
                out.append(text[i + 1])
                i += 2
        elif c == "'":
            end = text.find("'", i + 1)
            if end < 0:
                return None
            out.append(text[i + 1 : end])
            quoted = True
            i = end + 1
        elif c == '"' or (c == "$" and text[i + 1 : i + 2] == '"'):
            inner = _read_dquoted(text, i + (2 if c == "$" else 1))
            if inner is None:
                return None
            out.append(inner[0])
            quoted = True
            i = inner[1]
        elif c == "$" and text[i + 1 : i + 2] == "'":
            return None
        else:
            out.append(c)
            i += 1
    return "".join(out), quoted, i


def _heredoc_body(text: str, i: int, delim: str, *, strip_tabs: bool) -> tuple[int, int, int]:
    """(start, end, next) of the body that begins at line start `i`; unterminated runs to the end of text."""
    n = len(text)
    j = i
    while j < n:
        eol = text.find("\n", j)
        line_end = n if eol < 0 else eol
        line = text[j:line_end]
        if (line.lstrip("\t") if strip_tabs else line) == delim:
            return i, j, min(n, line_end + 1)
        j = line_end + 1
    return i, n, n


def lex(text: str) -> Lexed | None:
    """Lex `text` into simple commands, or None when a quote is never closed or `$'...'` is used."""
    commands: list[Raw] = []
    bodies: list[tuple[int, int]] = []
    pending: list[tuple[Raw, str, bool]] = []
    cur = Raw()
    n = len(text)
    i = 0

    def end_command() -> None:
        nonlocal cur
        if not cur.empty():
            commands.append(cur)
        cur = Raw()

    while i < n:
        c = text[i]
        if c in _SPACE:
            i += 1
        elif c == "\n":
            end_command()
            i += 1
            for owner, delim, strip_tabs in pending:
                start, end, i = _heredoc_body(text, i, delim, strip_tabs=strip_tabs)
                bodies.append((start, i))
                owner.stdin = text[start:end]
            pending.clear()
        elif c == "\\" and text[i + 1 : i + 2] == "\n":
            i += 2  # a line continuation between words joins nothing
        elif c == "#":
            end = text.find("\n", i)
            i = n if end < 0 else end
        elif c == "$" and text[i + 1 : i + 2] == "(":
            end_command()
            i += 2
        elif c in ";|&()`":
            if c == "&" and text[i + 1 : i + 2] == ">":
                i = _redirect(text, i, "", cur, pending)
                if i < 0:
                    return None
                continue
            end_command()
            i += 1
            if (c in ";|&" and text[i : i + 1] == c) or (c == "|" and text[i : i + 1] == "&"):
                i += 1
        elif c in "<>":
            fd = ""
            if cur.words and cur.words[-1].isdigit() and text[i - 1].isdigit():
                fd = cur.words.pop()
            i = _redirect(text, i, fd, cur, pending)
            if i < 0:
                return None
        else:
            word = _read_word(text, i)
            if word is None:
                return None
            cur.words.append(word[0])
            i = word[2]
    end_command()
    return Lexed(commands, bodies)


def _redirect(text: str, i: int, fd: str, cur: Raw, pending: list[tuple[Raw, str, bool]]) -> int:
    """Read the redirect at `i` into `cur`; the index after it, or -1 on an unclosed quote."""
    op = ("&>>" if text.startswith("&>>", i) else "&>") if text[i] == "&" else next(o for o in _REDIRECT_OPS if text.startswith(o, i))
    i += len(op)
    if op in ("<", ">") and text[i : i + 1] == "(":
        cur.redirects.append((fd + op, "("))  # process substitution; the paren opens a command
        return i
    while i < len(text) and text[i] in _SPACE:
        i += 1
    word = _read_word(text, i)
    if word is None:
        return -1
    target, _, i = word
    if op in ("<<", "<<-"):
        pending.append((cur, target, op == "<<-"))
    heredoc = op in ("<<", "<<-")
    if op == "<<<":
        cur.stdin = target
    quiet = target == "/dev/null" or (op in (">&", "<&") and re.fullmatch(r"\d+|-", target) is not None)
    if not (quiet and not heredoc):
        cur.redirects.append((fd + op, target))
    return i
