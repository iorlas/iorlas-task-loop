"""One copy of the base-.gitignore flattening: the ignore rules of a commit's every ``.gitignore``, as a single list.

``core.excludesFile`` is flat, so a nested ``.gitignore`` has to be rewritten with its folder as a prefix: an
anchored pattern (one with a ``/`` inside) is rooted under the folder, a bare one matches at any depth below it.
Both ``RealGit`` (which hands the list to ``git check-ignore``) and ``FakeGit`` (which matches it itself) use this,
so the rewrite exists once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["flatten", "is_ignore_file"]


def is_ignore_file(path: str) -> bool:
    return path == ".gitignore" or path.endswith("/.gitignore")


def flatten(files: Mapping[str, str]) -> list[str]:
    """Rules of ``files`` (``.gitignore`` path to its text), nested ones prefixed with their folder. A deeper file's
    rules come later, so they win, as git lets them."""
    rules: list[str] = []
    for path in sorted(files, key=lambda p: (p.count("/"), p)):
        folder = path.removesuffix(".gitignore").rstrip("/")
        for raw in files[path].splitlines():
            line = raw.rstrip()
            if not line or line.startswith("#"):
                continue
            rules.append(line if not folder else _prefixed(line, folder))
    return rules


def _prefixed(line: str, folder: str) -> str:
    negated = line.startswith("!")
    body = line.removeprefix("!")
    inner = body.rstrip("/")
    rooted = f"/{folder}/{inner.removeprefix('/')}" if "/" in inner else f"/{folder}/**/{inner}"
    tail = "/" if body.endswith("/") else ""
    return ("!" if negated else "") + rooted + tail
