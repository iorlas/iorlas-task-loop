"""A gitignore matcher for FakeGit: the common subset (globs, ``**``, anchoring, folder-only, negation).

Not covered: a ``.gitignore`` below the root, ``.git/info/exclude``, character classes beyond ``[...]``
passed through, escapes. The contract suite pins what is covered.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = ["Ignore"]


def _glob(pattern: str) -> str:
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("/**", i) and i + 3 == len(pattern):
            out.append("/.*")
            i += 3
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return "".join(out)


class _Rule:
    def __init__(self, line: str) -> None:
        self.negated = line.startswith("!")
        text = line.removeprefix("!")
        self.folder_only = text.endswith("/")
        text = text.rstrip("/")
        anchored = "/" in text
        body = _glob(text.removeprefix("/"))
        self.regex = re.compile(f"^{body}$" if anchored else f"^(?:.*/)?{body}$")

    def matches(self, path: str, *, is_folder: bool) -> bool:
        return (is_folder or not self.folder_only) and self.regex.match(path) is not None


class Ignore:
    """Rules in order of precedence: the last one that matches decides."""

    def __init__(self, lines: Iterable[str]) -> None:
        stripped = (line.rstrip() for line in lines)
        self._rules = [_Rule(line) for line in stripped if line and not line.startswith("#")]

    def _verdict(self, path: str, *, is_folder: bool) -> bool:
        ignored = False
        for rule in self._rules:
            if rule.matches(path, is_folder=is_folder):
                ignored = not rule.negated
        return ignored

    def ignores(self, path: str) -> bool:
        """True when ``path`` (a file) or any folder above it is ignored."""
        parts = path.split("/")
        for depth in range(1, len(parts)):
            if self._verdict("/".join(parts[:depth]), is_folder=True):
                return True
        return self._verdict(path, is_folder=False)
