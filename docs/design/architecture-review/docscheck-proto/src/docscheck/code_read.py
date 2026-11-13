"""Read facts from the target repo's source by `ast` and text. Nothing is imported or executed."""

import ast
import configparser
import functools
import re
from dataclasses import dataclass
from pathlib import Path

SQL_PREFIX = "sql:"


@functools.cache
def parse_file(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text())
    except (OSError, SyntaxError):
        return None


def split_source(source: str) -> tuple[str, str]:
    """`path::symbol` as (path, symbol); a source with no `::` is a path alone."""
    path, _, symbol = source.partition("::")
    return path, symbol


def _top_level(tree: ast.Module, name: str) -> ast.stmt | None:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == name:
            return node
        if isinstance(node, ast.TypeAlias) and isinstance(node.name, ast.Name) and node.name.id == name:
            return node
        if isinstance(node, ast.Assign) and any(isinstance(item, ast.Name) and item.id == name for item in node.targets):
            return node
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            return node
    return None


def symbol_exists(repo: Path, source: str) -> str | None:
    """None when `source` resolves, else why not."""
    rel, symbol = split_source(source)
    path = repo / rel
    if not path.is_file():
        return f"no file {rel}"
    if not symbol or symbol.startswith(SQL_PREFIX):
        return None
    tree = parse_file(path)
    if tree is None:
        return f"{rel} does not parse"
    head = symbol.split(".")[0]
    return None if _top_level(tree, head) is not None else f"{rel} has no top-level {head}"


def constant_value(repo: Path, source: str) -> int | str | None:
    rel, symbol = split_source(source)
    tree = parse_file(repo / rel)
    node = _top_level(tree, symbol) if tree else None
    value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
    return value.value if isinstance(value, ast.Constant) and isinstance(value.value, (int, str)) else None


def _literal_strings(node: ast.expr) -> tuple[str, ...] | None:
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "Literal":
        inner = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        values = [item.value for item in inner if isinstance(item, ast.Constant) and isinstance(item.value, str)]
        return tuple(values) if len(values) == len(inner) else None
    return None


def literal_members(repo: Path, source: str) -> tuple[str, ...] | None:
    """Members of `type X = Literal[...]`, `X = Literal[...]` or a class of `NAME = "value"` lines."""
    rel, symbol = split_source(source)
    tree = parse_file(repo / rel)
    node = _top_level(tree, symbol) if tree else None
    if isinstance(node, ast.TypeAlias):
        return _literal_strings(node.value)
    if isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
        return _literal_strings(node.value)
    if isinstance(node, ast.ClassDef):
        members = [item.value.value for item in node.body if isinstance(item, ast.Assign) and isinstance(item.value, ast.Constant)
                   and isinstance(item.value.value, str)]
        return tuple(members) or None
    return None


def _table_block(text: str, table: str) -> str:
    match = re.search(rf"CREATE TABLE {re.escape(table)} \((.*?)\n\);", text, re.S)
    return match.group(1) if match else ""


def sql_column_values(repo: Path, source: str) -> tuple[tuple[str, ...], str | None]:
    """Allowed values of `CHECK(col IN (...))` and the DEFAULT of a column, from `path::sql:table.column`."""
    rel, symbol = split_source(source)
    table, _, column = symbol.removeprefix(SQL_PREFIX).partition(".")
    path = repo / rel
    block = _table_block(path.read_text(), table) if path.is_file() else ""
    allowed = re.search(rf"\b{re.escape(column)}\s+IN\s*\(([^)]*)\)", block)
    default = re.search(rf"\b{re.escape(column)}\s+\w+\s+NOT NULL\s+DEFAULT\s+'(\w+)'", block)
    values = tuple(re.findall(r"'(\w+)'", allowed.group(1))) if allowed else ()
    return values, default.group(1) if default else None


def sql_written_values(repo: Path, source: str) -> set[str]:
    """Every literal a source file writes with `UPDATE table SET column='value'`, over the whole `src` tree."""
    _, symbol = split_source(source)
    table, _, column = symbol.removeprefix(SQL_PREFIX).partition(".")
    pattern = re.compile(rf"UPDATE\s+{re.escape(table)}\s+SET\s+{re.escape(column)}\s*=\s*'(\w+)'", re.I)
    return {value for path in sorted((repo / "src").rglob("*.py")) for value in pattern.findall(path.read_text())}


@dataclass(frozen=True)
class RepoTests:
    functions: dict[str, str]  # test function name -> "path"
    markers: dict[str, list[str]]  # rule id named by a `rule` marker -> the test names carrying it


_DEF = re.compile(r"^\s*(?:async\s+)?def (test_\w+)", re.M)
_MARK = re.compile(r"@pytest\.mark\.rule\(\s*[\"']([^\"']+)[\"']")


@functools.cache
def tests_in(repo: Path) -> RepoTests:
    """Test function names and `@pytest.mark.rule("<id>")` markers, read as text: a parse of every test file costs seconds."""
    functions: dict[str, str] = {}
    markers: dict[str, list[str]] = {}
    for path in sorted((repo / "tests").rglob("*.py")):
        text = path.read_text()
        defs = list(_DEF.finditer(text))
        for index, match in enumerate(defs):
            functions.setdefault(match.group(1), path.relative_to(repo).as_posix())
            before = text[defs[index - 1].end() if index else 0 : match.start()]
            for rule in _MARK.findall(before):
                markers.setdefault(rule, []).append(match.group(1))
    return RepoTests(functions, markers)


def contract_ids(repo: Path) -> dict[str, str]:
    """import-linter contract section keys, as `check/<key>` -> `.importlinter::<key>`."""
    path = repo / ".importlinter"
    if not path.is_file():
        return {}
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.read_string(path.read_text())
    return {f"check/{name.split(':')[-1]}": f".importlinter::{name.split(':')[-1]}"
            for name in parser.sections() if name.startswith("importlinter:contract:")}


def repo_check_ids(repo: Path) -> dict[str, str]:
    facts = tests_in(repo)
    ids = {f"check/{name}": f"{rel}::{name}" for name, rel in facts.functions.items()}
    ids.update(contract_ids(repo))
    return ids
