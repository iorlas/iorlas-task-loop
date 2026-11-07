"""Dashboard SQL stays within index tables, apart from its read-only run projection."""

import ast
import re
from pathlib import Path

import pytest

from rules.gate_rules import parsed
from taskloop.contracts.factorydb import OWNERS

ENGINE_TABLES = tuple(table for table, role in OWNERS.items() if role != "index")
ENGINE_SQL = re.compile(
    r"\b(?=(?:SELECT|INSERT|UPDATE|DELETE|REPLACE)\b).*?"
    r"\b(?:FROM|INTO|UPDATE|JOIN)\s+(?:" + "|".join(map(re.escape, ENGINE_TABLES)) + r")\b",
    re.IGNORECASE | re.DOTALL,
)


RUN_READ = re.compile(r"^SELECT\b[^;]*\bFROM run\b[^;]*$", re.IGNORECASE | re.DOTALL)
RUN_FORBIDDEN = re.compile(r"\b(?:INSERT|UPDATE|DELETE|REPLACE|JOIN)\b", re.IGNORECASE)
TABLE_READ = re.compile(r"\bFROM\s+(\w+)", re.IGNORECASE)


def _run_read(sql: str) -> bool:
    return bool(RUN_READ.fullmatch(sql) and not RUN_FORBIDDEN.search(sql)
                and all(table.lower() == "run" for table in TABLE_READ.findall(sql)))


def engine_sql(tree: ast.AST, *, run_projection: bool = False) -> list[int]:
    """Find SQL in string constants, including the literal parts of f-strings."""
    return [node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and ENGINE_SQL.search(node.value)
            and not (run_projection and _run_read(node.value))]


def test_dashboard_has_no_engine_table_sql() -> None:
    root = Path(__file__).resolve().parents[2] / "src" / "taskloop_dash"
    bad = []
    for path in sorted(root.rglob("*.py")):
        bad.extend(f"{path.relative_to(root)}:{line}" for line in engine_sql(
            parsed(path)[1], run_projection=path.relative_to(root).as_posix() == "readers/runprojection.py"))
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


def test_run_projection_may_only_read_runs():
    for sql in ("SELECT facts FROM run", "SELECT * FROM run WHERE repo=?"):
        assert engine_sql(ast.parse(repr(sql)), run_projection=True) == []
    for sql in ("DELETE FROM run", "UPDATE run SET facts=NULL", "SELECT * FROM run JOIN lease ON 1=1",
                "SELECT * FROM run; DELETE FROM run", "SELECT * FROM lease"):
        assert engine_sql(ast.parse(repr(sql)), run_projection=True) == [1]
