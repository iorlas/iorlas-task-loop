"""Arguments that keep a path out of a search, so a word naming a path is not read as touching it."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

_GLOB_OPTS = frozenset({"-g", "--glob", "--iglob", "--exclude", "--exclude-dir", "--exclude-from"})
_PATH_OPTS = frozenset({"-path", "-ipath", "-name", "-iname", "-wholename", "-iwholename", "-regex", "-iregex"})
_NEGATIONS = ("-not", "!")
_INLINE_RE = re.compile(r"--exclude(?:-dir|-from)?=|(?:--i?glob=|-g)!")
_PATHSPEC_RE = re.compile(r":(?:!|\(exclude\))")


def strip_excluded(argv: Iterable[str]) -> tuple[str, ...]:
    """`argv` without the arguments that only exclude: rg `--glob '!x'`, grep `--exclude x`, find `-not -path x`, git `':!x'`.

    Quote splicing is already collapsed in `argv`, so `'"'!'"\\.env*'` is one word here.
    """
    out: list[str] = []
    prev = prev2 = ""
    for word in argv:
        glob_value = prev in _GLOB_OPTS and (word.startswith("!") or prev.startswith("--exclude"))
        path_value = prev in _PATH_OPTS and prev2 in _NEGATIONS
        dropped = (
            glob_value
            or path_value
            or _INLINE_RE.match(word)
            or word in _GLOB_OPTS
            or _PATHSPEC_RE.match(word)
            or word in _NEGATIONS
            or (word in _PATH_OPTS and prev in _NEGATIONS)
        )
        if not dropped:
            out.append(word)
        prev2, prev = prev, word
    return tuple(out)
