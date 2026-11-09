"""Retain static caps and disallow hidden baseline or process imports."""

import ast
import io
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
