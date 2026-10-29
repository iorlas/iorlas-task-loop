"""Checks for a no-build static web page. Each returns problem strings; an empty list means fine."""

from __future__ import annotations

import gzip
import hashlib
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

__all__ = ["budget_problems", "colour_problems", "import_problems", "page_problems", "pin_problems"]

_IMPORT = re.compile(r"""^\s*import\s+(?:(\{[^}]*\}|\*\s+as\s+\w+|\w+)\s+from\s+)?['"]([^'"]+)['"]""", re.MULTILINE)
_EXPORT = re.compile(r"^export\s+(?:async\s+)?(?:function|const|let|class)\s+(\w+)", re.MULTILINE)
_EXPORT_LIST = re.compile(r"^export\s*\{([^}]*)\}", re.MULTILINE)
_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b(?![-\w])|\brgba?\(|\bhsla?\(")
_REFERENCE = re.compile(r"""(?:href|src)=["']([^"']*)["']""")
_ANCHOR_REF = re.compile(r"""(?:href=|url\()["']?#\w+""")
_SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def _within(static_dir: Path, name: str | Path) -> Path:
    return static_dir / name  # an absolute name wins, by pathlib's rule


def _rel(static_dir: Path, path: Path) -> str:
    return path.relative_to(static_dir).as_posix()


def _files(static_dir: Path, suffixes: Iterable[str], skip: Iterable[Path] = ()) -> list[Path]:
    skipped = {p.resolve() for p in skip}
    return sorted(p for p in static_dir.rglob("*") if p.is_file() and p.suffix in set(suffixes) and p.resolve() not in skipped)


def _missing_dir(static_dir: Path) -> list[str]:
    return [] if static_dir.is_dir() else [f"{static_dir}: not a directory"]


def _exports(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    names = set(_EXPORT.findall(text))
    for group in _EXPORT_LIST.findall(text):
        names |= {n.split(" as ")[-1].strip() for n in group.split(",") if n.strip()}
    return names


def import_problems(static_dir: Path, *, vendored: Iterable[str | Path] = ()) -> list[str]:
    """Problems with the ES imports of every `.js` file under ``static_dir`` (``vendored`` files are not scanned)."""
    if bad := _missing_dir(static_dir):
        return bad
    bundles = {_within(static_dir, v).resolve() for v in vendored}
    problems: list[str] = []
    for path in _files(static_dir, [".js"], bundles):
        for names, spec in _IMPORT.findall(path.read_text(encoding="utf-8")):
            where = f"{_rel(static_dir, path)}: import '{spec}'"
            if not spec.startswith("."):
                problems.append(f"{where}: imports are relative, no bare or absolute specifier")
                continue
            target = (path.parent / spec).resolve()
            if not target.is_file():
                problems.append(f"{where}: no such file")
            elif names.startswith("{"):
                wanted = {n.split(" as ")[0].strip() for n in names.strip("{}").split(",") if n.strip()}
                if target in bundles:
                    text = target.read_text(encoding="utf-8")
                    missing = {n for n in wanted if not re.search(rf"\b{re.escape(n)}\b", text)}
                else:
                    missing = wanted - _exports(target)
                if missing:
                    problems.append(f"{where}: does not export {sorted(missing)}")
    return problems


def page_problems(static_dir: Path) -> list[str]:
    """Problems with the `href`/`src` references of every `.html` file: each must be relative and exist."""
    if bad := _missing_dir(static_dir):
        return bad
    problems: list[str] = []
    for page in _files(static_dir, [".html"]):
        for ref in _REFERENCE.findall(page.read_text(encoding="utf-8")):
            where = f"{_rel(static_dir, page)}: '{ref}'"
            if ref.startswith("#"):
                continue
            if ref.startswith("/") or _SCHEME.match(ref):
                problems.append(f"{where}: not a relative url")
            elif not (page.parent / re.split(r"[?#]", ref)[0]).is_file():
                problems.append(f"{where}: no such file")
    return problems


def pin_problems(static_dir: Path, pins: Mapping[str | Path, str]) -> list[str]:
    """Problems with vendored files: each ``pins`` entry maps a file to the sha256 it must have."""
    if bad := _missing_dir(static_dir):
        return bad
    problems: list[str] = []
    for name, sha256 in pins.items():
        path = _within(static_dir, name)
        if not path.is_file():
            problems.append(f"{name}: pinned file is missing")
        elif (got := hashlib.sha256(path.read_bytes()).hexdigest()) != sha256.lower():
            problems.append(f"{name}: sha256 {got} is not the pinned {sha256}; replace the file with a new pin, never edit it")
    return problems


def _without_css_selectors(text: str) -> str:
    """CSS minus comments and selector text (so an id selector is no colour); newlines stay, for line numbers."""
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.DOTALL)
    return re.sub(r"[^{}]*\{", lambda m: "\n" * m.group(0).count("\n") + "{", text)


def colour_problems(static_dir: Path, tokens: str | Path, *, vendored: Iterable[str | Path] = ()) -> list[str]:
    """Problems with colour literals (`#hex`, `rgb(`, `hsl(`) written in any `.js`, `.css` or `.html` file but ``tokens``."""
    if bad := _missing_dir(static_dir):
        return bad
    skip = [_within(static_dir, tokens), *(_within(static_dir, v) for v in vendored)]
    problems: list[str] = []
    for path in _files(static_dir, [".js", ".css", ".html"], skip):
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".css":
            text = _without_css_selectors(text)
        text = _ANCHOR_REF.sub("", text)
        for n, line in enumerate(text.splitlines(), 1):
            if hits := [m.group(0) for m in _COLOUR.finditer(line)]:
                problems.append(f"{_rel(static_dir, path)}:{n}: colour outside {tokens}: {hits}")
    return problems


def budget_problems(static_dir: Path, max_gzip_bytes: int) -> list[str]:
    """A problem when all `.js` and `.css` under ``static_dir`` gzip (level 9, file by file) to more than the budget."""
    if bad := _missing_dir(static_dir):
        return bad
    total = sum(len(gzip.compress(p.read_bytes(), 9)) for p in _files(static_dir, [".js", ".css"]))
    return [f"JS+CSS is {total} bytes gzipped, budget {max_gzip_bytes}"] if total > max_gzip_bytes else []
