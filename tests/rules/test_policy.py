"""Retain static caps and disallow hidden baseline or process imports."""

import ast
import io
import re
import tokenize
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FILES = sorted(path for folder in ("src", "tests") for path in (ROOT / folder).rglob("*.py"))


def code_lines(source: str, tree: ast.Module) -> set[int]:
    """Count nonblank, noncomment, nondocstring lines as in the baseline policy."""
    ignored = {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENCODING, tokenize.ENDMARKER}
    lines: set[int] = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type not in ignored:
            lines.update(range(token.start[0], token.end[0] + 1))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                lines.difference_update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return lines


@pytest.mark.parametrize("path", FILES, ids=lambda path: str(path.relative_to(ROOT)))
def test_source_policy(path: Path) -> None:
    source = path.read_text()
    tree = ast.parse(source)
    limits = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["shelf-size"]
    lines = code_lines(source, tree)
    cap = limits["test-file"] if path.is_relative_to(ROOT / "tests") else limits["code-file"]
    assert len(lines) <= cap, path
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = min([node.lineno, *[decorator.lineno for decorator in node.decorator_list]])
            assert len(lines & set(range(start, (node.end_lineno or node.lineno) + 1))) <= limits["function"], node.name
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"Any", "cast"}, (path, node.lineno)
        if isinstance(node, ast.Name):
            assert node.id not in {"Any", "cast"}, (path, node.lineno)
        if isinstance(node, ast.ImportFrom):
            assert all(alias.name not in {"Any", "cast"} for alias in node.names)
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            assert all(name.split(".")[0] not in {"subprocess", "tlkernel", "tltestkit", "delegate"} for name in names)
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            assert not any(marker in token.string for marker in ("type: ignore", "pyrefly: ignore", "noqa"))


def test_caps_cannot_be_relaxed() -> None:
    limits = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["shelf-size"]
    assert limits == {"code-file": 400, "function": 80, "test-file": 800}



# Every SQL write in the source, by (verb, table) -> the one module allowed to issue it. Anything unlisted is refused.
WRITERS = {
    ("CREATE TABLE", "slot"): "plan_schema.py",
    ("CREATE TABLE", "reservation"): "plan_schema.py",
    ("CREATE TABLE", "plan_attempt"): "plan_schema.py",
    ("CREATE TABLE", "plan_execution"): "plan_schema.py",
    ("CREATE TABLE", "plan_verification"): "plan_schema.py",
    ("CREATE TABLE", "plan_release"): "plan_schema.py",
    ("INSERT", "slot"): "slots.py",
    ("INSERT", "reservation"): "plan_admit.py",
    ("INSERT", "plan_attempt"): "plan_admit.py",
    ("UPDATE", "reservation"): "plan_admit.py",
    ("UPDATE", "slot"): "plan_admit.py",
    ("INSERT", "plan_release"): "plan_release.py",
    ("UPDATE", "plan_release"): "plan_release.py",
    ("DELETE FROM", "reservation"): "plan_release.py",
    ("INSERT", "plan_execution"): "plan_store.py",
    ("INSERT", "plan_verification"): "plan_store.py",
    ("UPDATE", "plan_attempt"): "plan_store.py",
    ("UPDATE", "plan_execution"): "plan_store.py",
}
WRITE = re.compile(
    r"\b(CREATE\s+TABLE|(?:INSERT|REPLACE)(?:\s+OR\s+\w+)?\s+INTO|UPDATE(?:\s+OR\s+\w+)?|DELETE\s+FROM)\s+(\w+)", re.IGNORECASE
)


def sql_writes() -> set[tuple[str, str, str]]:
    found: set[tuple[str, str, str]] = set()
    for path in (ROOT / "src" / "taskloop").glob("*.py"):
        for match in WRITE.finditer(path.read_text()):
            verb = " ".join(match.group(1).upper().split())
            kind = "INSERT" if verb.startswith(("INSERT", "REPLACE")) else verb.split()[0] if verb.startswith("UPDATE") else verb
            found.add((kind, match.group(2).lower(), path.name))
    return found


def test_every_sql_write_has_its_one_owner() -> None:
    found = sql_writes()
    assert {(kind, table): owner for kind, table, owner in found} == WRITERS
    assert len(found) == len(WRITERS), sorted(found)


@pytest.mark.parametrize(
    "statement",
    ["INSERT INTO slot(a) VALUES (1)", "REPLACE INTO reservation VALUES (1)", "delete from plan_attempt", "UPDATE OR ABORT slot SET a=1"],
)
def test_write_pattern_catches_spelling_variants(statement: str) -> None:
    assert WRITE.search(statement) is not None


GIT_WRITES = frozenset({"stage", "stage_tracked", "record", "take_branch", "park"})


def git_writers() -> set[tuple[str, str]]:
    """Every use of a Git write on a checkout (`GIT_WRITES`) in the factory source, by module: a call or reference of
    that attribute on any receiver, a bare call of that name, or the name as a string (`getattr(slot, "record")`). Its
    limit: a name built at runtime (`getattr(slot, "re" + "cord")`) or a write through another library API is not seen."""
    found: set[tuple[str, str]] = set()
    for path in (ROOT / "src" / "taskloop").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            called = node.func if isinstance(node, ast.Call) else None
            name = (
                node.attr if isinstance(node, ast.Attribute)
                else called.id if isinstance(called, ast.Name)
                else node.value if isinstance(node, ast.Constant) and isinstance(node.value, str)
                else None
            )
            if name in GIT_WRITES:
                found.add((name, path.name))
    return found


def test_only_the_commit_prepare_and_release_modules_write_git() -> None:
    expected = {
        ("stage", "plan_commit.py"), ("record", "plan_commit.py"), ("take_branch", "plan_prepare.py"), ("park", "plan_prepare.py"),
        ("park", "plan_release.py"),
    }
    assert git_writers() == expected


def bd_importers() -> set[str]:
    """Every factory module that imports the tracker client `Bd` (from `beads_client` or a submodule, or the module itself
    to reach `beads_client.Bd`)."""
    found: set[str] = set()
    for path in (ROOT / "src" / "taskloop").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "beads_client":
                found.update(path.name for alias in node.names if alias.name in {"Bd", "client", "*"})
            if isinstance(node, ast.Import) and any(alias.name.split(".")[0] == "beads_client" for alias in node.names):
                found.add(path.name)
    return found


def test_only_composition_constructs_the_tracker_client() -> None:
    """The tracker's writes (claim, unclaim, heartbeat) have one wiring owner."""
    assert bd_importers() == {"composition.py"}
