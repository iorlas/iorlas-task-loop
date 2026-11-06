"""One simple command of a shell line, and the words around the program name."""

from __future__ import annotations

import posixpath
import re
import shlex
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})


# Wrapper programs that run the rest of their line, with the options that take a separate value (and a
# count of leading positionals). Heuristic: an option missing here would make its value read as the program.
def _opts(names: str) -> frozenset[str]:
    return frozenset(names.split())


WRAPPERS: Mapping[str, tuple[frozenset[str], int]] = {
    "sudo": (_opts("-u -g -h -p -C -D -R -T -U -r -t --user --group --host --prompt --chdir --role --type"), 0),
    "doas": (_opts("-u -C"), 0),
    "env": (_opts("-u -C -S --unset --chdir --split-string"), 0),
    "exec": (_opts("-a"), 0),
    "nohup": (_opts(""), 0),
    "time": (_opts("-f -o --format --output"), 0),
    "command": (_opts(""), 0),
    "builtin": (_opts(""), 0),
    "xargs": (_opts("-n -I -P -L -s -d -E -a -J --max-args --max-procs --delimiter --arg-file"), 0),
    "nice": (_opts("-n --adjustment"), 0),
    "ionice": (_opts("-c -n -p --class --classdata"), 0),
    "timeout": (_opts("-s -k --signal --kill-after"), 1),
    "setsid": (_opts(""), 0),
    "stdbuf": (_opts("-i -o -e"), 0),
}

_ASSIGN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\+?=")
_ASSIGNING = frozenset({"env", "sudo", "doas"})
_OUTPUT_OP_RE = re.compile(r"\d*(?:&>|>|<>)")


def name_of(word: str) -> str:
    """The program a word names, path stripped: `/usr/bin/git` is `git`."""
    return posixpath.basename(word)


def is_assign(word: str) -> bool:
    """A `NAME=value` word."""
    return _ASSIGN_RE.match(word) is not None


def strip_wrappers(argv: Sequence[str], wrappers: Mapping[str, tuple[frozenset[str], int]] = WRAPPERS) -> tuple[str, ...]:
    """The words of `argv` after leading wrapper programs (sudo, env, nohup, ...), their options and `NAME=v` words."""
    words = tuple(argv)
    i = 0
    while i < len(words) and name_of(words[i]) in wrappers:
        name = name_of(words[i])
        takes_value, positionals = wrappers[name]
        i += 1
        while i < len(words):
            word = words[i]
            if word == "--":
                i += 1
                break
            if name in _ASSIGNING and is_assign(word):
                i += 1
            elif name == "env" and (script := _split_string(words, i)) is not None:
                # env -S 'git push' runs the words of its value; strip those again from the top.
                words, i = ("env", *script[0], *words[script[1] :]), -1
                break
            elif word.startswith("-") and len(word) > 1:
                i += 2 if word in takes_value else 1
            else:
                break
        i = 0 if i < 0 else i + positionals
    return words[i:]


def _split_string(words: tuple[str, ...], i: int) -> tuple[tuple[str, ...], int] | None:
    """For `env -S value` / `-Svalue` / `--split-string=value` at `words[i]`: the value split into words, and the index after it."""
    word = words[i]
    if word in ("-S", "--split-string"):
        value, after = (words[i + 1], i + 2) if i + 1 < len(words) else ("", i + 1)
    elif word.startswith("--split-string="):
        value, after = word.partition("=")[2], i + 1
    elif word.startswith("-S") and not word.startswith("--"):
        value, after = word[2:], i + 1
    else:
        return None
    try:
        return tuple(shlex.split(value)), after
    except ValueError:
        return (value,), after


@dataclass(frozen=True)
class Command:
    """One simple command: its words, leading `NAME=value` assignments, and the redirects it carries.

    Redirects are `<op><target>` strings (`>out.txt`, `2>>log`, `<in`, `<<EOF`); quiet ones (to /dev/null,
    between descriptors) are dropped. `stdin` is the text a here-document or here-string feeds it.
    """

    argv: tuple[str, ...] = ()
    assigns: tuple[str, ...] = ()
    redirects: tuple[str, ...] = ()
    stdin: str | None = None

    @property
    def words(self) -> tuple[str, ...]:
        """`argv` after wrapper programs."""
        return strip_wrappers(self.argv)

    @property
    def name(self) -> str:
        """The program run, wrappers and path stripped; empty for a bare redirect or assignment."""
        words = self.words
        return name_of(words[0]) if words else ""

    @property
    def output_redirects(self) -> tuple[str, ...]:
        """The redirects that write: output operators (`>`, `>>`, `&>`, `<>`), not input ones."""
        return tuple(r for r in self.redirects if _OUTPUT_OP_RE.match(r))
