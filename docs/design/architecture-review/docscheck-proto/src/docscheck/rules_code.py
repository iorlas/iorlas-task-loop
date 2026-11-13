"""Checks of docs against the target repo's code: paths, globs, symbols, limits, lifecycle enums, rule probes, markers."""

import functools
import os
from pathlib import Path

from any_path_glob import Glob

from docscheck.code_read import (
    SQL_PREFIX, constant_value, literal_members, split_source, sql_column_values, sql_written_values, symbol_exists, tests_in,
)
from docscheck.docs import Doc, walk_rows, walk_values
from docscheck.index import Entry
from docscheck.ontology import Kind
from docscheck.probes import PROBES
from docscheck.values import Finding, as_list, as_map, as_str

SKIP = frozenset({".git", ".venv", "node_modules", "__pycache__", ".beads", ".mypy_cache", ".ruff_cache", ".pytest_cache"})


@functools.cache
def repo_files(repo: Path) -> tuple[str, ...]:
    found: list[str] = []
    for folder, dirs, files in os.walk(repo):
        dirs[:] = sorted(d for d in dirs if d not in SKIP)
        found.extend((Path(folder) / name).relative_to(repo).as_posix() for name in files)
    return tuple(sorted(found))


def references(doc: Doc, kinds: dict[str, Kind], repo: Path) -> list[Finding]:
    """Fields flagged `path`, `glob` or `symbol` resolve in the repo."""
    found: list[Finding] = []
    for path, field, value in walk_values(kinds[doc.kind], kinds, doc.data):
        items = [value] if isinstance(value, str) else [v for v in as_list(value) if isinstance(v, str)]
        for item in items if field.type.base == "string" else []:
            if field.path and not (repo / item).is_file():
                found.append(Finding(doc.id, path, "path-missing", f"no file {item}"))
            if field.glob and not any(Glob(item).matches(name) for name in repo_files(repo)):
                found.append(Finding(doc.id, path, "glob-empty", f"{item} matches no file"))
            if field.symbol and (why := symbol_exists(repo, item)) is not None:
                found.append(Finding(doc.id, path, "symbol-unresolved", f"{item}: {why}"))
    return found


def limits(doc: Doc, kinds: dict[str, Kind], repo: Path) -> list[Finding]:
    found: list[Finding] = []
    for row in walk_rows(kinds[doc.kind], kinds, doc.id, doc.data):
        if row.kind == "limit" and isinstance(row.values.get("value"), int):
            actual = constant_value(repo, as_str(row.values.get("source")))
            if actual is not None and actual != row.values.get("value"):
                found.append(Finding(doc.id, row.path, "limit-differs", f"doc says {row.values.get('value')}, {row.values.get('source')} is {actual}"))
    return found


def probes(doc: Doc, kinds: dict[str, Kind], repo: Path) -> list[Finding]:
    found: list[Finding] = []
    for row in walk_rows(kinds[doc.kind], kinds, doc.id, doc.data):
        name = as_str(row.values.get("probe"))
        if row.kind != "rule" or not name:
            continue
        if name not in PROBES:
            found.append(Finding(doc.id, row.path, "probe-unknown", f"no probe named {name!r}"))
            continue
        found.extend(Finding(doc.id, f"{row.path}.holds", "probe-contradiction", f"{name}: {line}") for line in PROBES[name](repo))
    return found


def lifecycle_source(doc: Doc, repo: Path) -> list[Finding]:
    """Declared states equal the code's: a `Literal`/enum members list, or an SQL `CHECK(col IN (...))`, plus the writes."""
    source = as_str(doc.data.get("source"))
    states = tuple(as_str(s) for s in as_list(doc.data.get("states")))
    _, symbol = split_source(source)
    if symbol.startswith(SQL_PREFIX):
        values, default = sql_column_values(repo, source)
        written = sql_written_values(repo, source)
    else:
        values, default, written = literal_members(repo, source) or (), None, set()
    found: list[Finding] = []
    if not values:
        return [Finding(doc.id, "source", "source-no-members", f"{source} lists no states the checker can read")]
    if set(values) != set(states):
        found.append(Finding(doc.id, "states", "enum-drift", f"doc has {sorted(states)}, code has {sorted(values)}"))
    if written:
        expected = set(states) - ({default} if default else {as_str(doc.data.get("initial"))})
        if written != expected:
            found.append(Finding(doc.id, "transitions", "writes-differ", f"code writes {sorted(written)}, doc expects {sorted(expected)}"))
    return found


def markers(entries: dict[str, Entry], repo: Path) -> list[Finding]:
    """Tests carrying `@pytest.mark.rule("<area>.<n>")` name a rule that exists."""
    found: list[Finding] = []
    for rule, tests in sorted(tests_in(repo).markers.items()):
        if f"rule/{rule}" not in entries:
            found.append(Finding("tests", ",".join(tests), "marker-dangling", f"rule marker {rule!r} names no rule"))
    return found


def weak(doc: Doc, kinds: dict[str, Kind]) -> tuple[int, int]:
    """(rules, rules with no check and no probe)."""
    rows = [row for row in walk_rows(kinds[doc.kind], kinds, doc.id, doc.data) if row.kind == "rule"]
    unchecked = [r for r in rows if as_str(as_map(r.values).get("check")) in {"", "none"} and not r.values.get("probe")]
    return len(rows), len(unchecked)
