"""Named probes: facts read from the code that a rule's `probe` field compares with the rule."""

import ast
import re
from collections.abc import Callable
from pathlib import Path

from docscheck.code_read import parse_file

STORE_FILES = frozenset({"factory_schema.py"})


def _writers(repo: Path) -> dict[str, set[str]]:
    """table -> modules that write it, from the policy test's WRITERS dict."""
    tree = parse_file(repo / "tests/rules/test_policy.py")
    for node in tree.body if tree else ():
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "WRITERS" for t in node.targets):
            pairs = ast.literal_eval(node.value)
            tables: dict[str, set[str]] = {}
            for (verb, table), module in pairs.items():
                if verb != "CREATE TABLE" and verb != "CREATE INDEX":
                    tables.setdefault(table, set()).add(module)
            return tables
    return {}


def one_writer_per_table(repo: Path) -> list[str]:
    """Tables with more than one writing module."""
    return [f"{table} is written by {len(modules)} modules: {', '.join(sorted(modules))}"
            for table, modules in sorted(_writers(repo).items()) if len(modules) > 1]


SQL_CALL = re.compile(r"\.(?:execute|executemany|executescript)\(")


def sql_outside_store(repo: Path) -> list[str]:
    """Modules outside `*_store.py` that call `.execute(` (read as text; a parse of every module costs half a second)."""
    outside: list[str] = []
    for path in sorted((repo / "src/taskloop").glob("*.py")):
        if path.name.endswith("_store.py") or path.name in STORE_FILES:
            continue
        calls = len(SQL_CALL.findall(path.read_text()))
        if calls:
            outside.append(f"{path.name} issues {calls} SQL call(s)")
    return outside


PROBES: dict[str, Callable[[Path], list[str]]] = {
    "one-writer-per-table": one_writer_per_table,
    "sql-outside-store": sql_outside_store,
}
