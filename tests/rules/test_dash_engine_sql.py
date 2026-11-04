"""Dashboard SQL must stay within index-owned tables."""

import ast
import re
from pathlib import Path

import pytest

from taskloop.contracts.factorydb import OWNERS

ENGINE_TABLES = tuple(table for table, role in OWNERS.items() if role != "index")
ENGINE_SQL = re.compile(
    r"\b(?=(?:SELECT|INSERT|UPDATE|DELETE|REPLACE)\b).*?"
    r"\b(?:FROM|INTO|UPDATE|JOIN)\s+(?:" + "|".join(map(re.escape, ENGINE_TABLES)) + r")\b",
    re.IGNORECASE | re.DOTALL,
)


def engine_sql(tree: ast.AST) -> list[int]:
    """Find SQL in string constants, including the literal parts of f-strings."""
    return [node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and ENGINE_SQL.search(node.value)]


def test_dashboard_has_no_engine_table_sql() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "taskloop_dash"
    bad = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        bad.extend(f"{path.relative_to(root)}:{line}" for line in engine_sql(tree))
    assert bad == []


@pytest.mark.parametrize("table", ENGINE_TABLES)
@pytest.mark.parametrize("statement", (
    "SELECT facts FROM {table}",
    "INSERT INTO {table} VALUES (?)",
    "UPDATE {table} SET facts=NULL",
    "DELETE FROM {table}",
    "REPLACE INTO {table} VALUES (?)",
    "select * from source\njoin {table} on 1=1",
))
def test_checker_sees_a_planted_sql_string(table: str, statement: str) -> None:
    sql = statement.format(table=table)
    assert engine_sql(ast.parse(repr(sql))) == [1]
    assert engine_sql(ast.parse('f' + repr(sql + " WHERE run={run}"))) == [1]
    assert engine_sql(ast.parse(repr("SELECT * ") + " " + repr("FROM " + table))) == [1]
    assert engine_sql(ast.parse(repr("SELECT * FROM " + table + "_archive"))) == []
    for owned in (name for name, role in OWNERS.items() if role == "index"):
        assert engine_sql(ast.parse(repr(statement.format(table=owned)))) == []
