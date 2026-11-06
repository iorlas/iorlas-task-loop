"""Shell text to simple commands, looking through `sh -c`, `eval` and here-documents fed to a shell."""

from __future__ import annotations

import re

from any_shell_policy.command import SHELLS, Command, is_assign, name_of, strip_wrappers
from any_shell_policy.lex import Lexed, Raw, lex

MAX_DEPTH = 3  # sh -c nested deeper than this is not looked into: parse returns None (fail closed)

_SHELL_C_RE = re.compile(r"[-+][a-z]*c[a-z]*")
_SHELL_VALUE_OPTS = frozenset({"-o", "+o", "-O", "+O", "--rcfile", "--init-file"})
_LEADING_KEYWORDS = frozenset({"if", "then", "else", "elif", "do", "while", "until", "!", "{", "}"})
_HEADERS = frozenset({"for", "select", "case"})
_CLOSERS = frozenset({"done", "fi", "esac"})
# A quote-blind view, so a quoted word cannot hide a write from the text check.
_QUIET_RE = re.compile(r"\d?>&(?:\d|-)(?![\w])|&?\d?>\s*/dev/null(?![\w./-])")
_WRITES_RE = re.compile(r"`|\$\(|[<>]\(|>")


def _shell_script(words: tuple[str, ...], stdin: str | None) -> str | None:
    """The script a shell run `words` (program first) executes, or None when it runs a file or nothing is known."""
    i = 1
    while i < len(words):
        w = words[i]
        if _SHELL_C_RE.fullmatch(w):
            return words[i + 1] if i + 1 < len(words) else ""
        if w == "--":
            i += 1
            break
        if w in _SHELL_VALUE_OPTS:
            i += 2
        elif w[:1] in "-+" and len(w) > 1:
            i += 1
        else:
            break
    return stdin if i >= len(words) else None


def _command(raw: Raw) -> Command | None:
    words = list(raw.words)
    while words and words[0] in _LEADING_KEYWORDS:
        words.pop(0)
    if words and (words[0] in _HEADERS or (words[0] in _CLOSERS and len(words) == 1)):
        words = list[str]()
    n = next((k for k, w in enumerate(words) if not is_assign(w)), len(words))
    redirects = tuple(f"{op}{target}" if target != "(" else op for op, target in raw.redirects)
    if not words and not redirects:
        return None
    return Command(tuple(words[n:]), tuple(words[:n]), redirects, raw.stdin)


def _commands(lexed: Lexed, depth: int) -> list[Command] | None:
    out: list[Command] = []
    for raw in lexed.commands:
        cmd = _command(raw)
        if cmd is None:
            continue
        words = strip_wrappers(cmd.argv)
        script: str | None = None
        if words and name_of(words[0]) in SHELLS:
            script = _shell_script(words, cmd.stdin)
        elif words and name_of(words[0]) == "eval" and len(words) > 1:
            script = " ".join(words[1:])
        if script is None:
            out.append(cmd)
            continue
        inner = _parse(script, depth + 1)
        if inner is None:
            return None
        if cmd.redirects:
            out.append(Command(redirects=cmd.redirects))
        out.extend(inner)
    return out


def _parse(text: str, depth: int) -> list[Command] | None:
    if depth > MAX_DEPTH:
        return None
    lexed = lex(text)
    return None if lexed is None else _commands(lexed, depth)


def parse(text: str) -> list[Command] | None:
    """The simple commands in `text`, in order, or None when it cannot be understood.

    Splits on unquoted `| || & && ; ;;` newline, subshell parens, backticks and `$(`; a separator inside
    quotes stays in its word. `for/while/if ... do ... done` reduce to the commands inside. A shell run
    with `-c` (also `eval`, or a shell fed by a here-document) is replaced by the commands of its script,
    nested to depth 3. None means: an unclosed quote, `$'...'`, or `sh -c` nested deeper than 3. Never raises.
    """
    return _parse(text, 0)


def strip_heredocs(text: str) -> str:
    """`text` without here-document bodies (quote-aware); the text unchanged when it does not lex."""
    lexed = lex(text)
    if lexed is None or not lexed.bodies:
        return text
    out: list[str] = []
    pos = 0
    for start, end in sorted(lexed.bodies):
        out.append(text[pos:start])
        pos = end
    out.append(text[pos:])
    return "".join(out)


def has_write_syntax(text: str) -> bool:
    """True when the text redirects output to a file or substitutes a command (backtick, `$(`, `<(`, `>(`).

    A quote-blind regex over the text, here-document bodies excluded: a `>` inside quotes counts, a
    substitution inside double quotes counts. Redirects to /dev/null and between descriptors do not.
    """
    return _WRITES_RE.search(_QUIET_RE.sub(" ", strip_heredocs(text))) is not None
