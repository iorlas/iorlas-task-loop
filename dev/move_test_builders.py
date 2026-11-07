"""Move test data builders to the test kit; rerun after rebasing with --root DIR.

Preflight all Python uses before writing. Unsupported executable uses abort.
Dotted imports and patch targets are rewritten together. Git detects the
filesystem rename without changing the index.
"""
import argparse
import ast
import re
from pathlib import Path

MOVES = {"plans": "tltestkit", "cfgs": "tltestkit"}
OLD = "support"


def references(text: str) -> str:
    for name, parent in MOVES.items():
        text = text.replace(f"{OLD}.{name}", f"{parent}.{name}")
        text = text.replace(f"tests/support/{name}.py", f"packages/testkit/src/tltestkit/{name}.py")
        text = text.replace(f"support/{name}.py", f"tltestkit/{name}.py")
    return text


def parent_import(node: ast.ImportFrom, lines: list[str]) -> str:
    assert node.end_lineno is not None and node.end_col_offset is not None
    groups: dict[str, list[str]] = {}
    for alias in node.names:
        parent = MOVES.get(alias.name, OLD)
        value = alias.name + (f" as {alias.asname}" if alias.asname else "")
        groups.setdefault(parent, []).append(value)
    indent = " " * node.col_offset
    suffix = lines[node.end_lineno - 1][node.end_col_offset:].rstrip("\n")
    first = lines[node.lineno - 1]
    if "# noqa:" in first and "# noqa:" not in suffix:
        suffix += "  # noqa:" + first.split("# noqa:", 1)[1].rstrip()
    return ("\n" + indent).join(
        f"from {parent} import {', '.join(names)}{suffix}"
        for parent, names in groups.items()
    )


def import_edits(path: Path, root: Path) -> tuple[str, list[str]]:
    text = path.read_text()
    lines = text.splitlines(keepends=True)
    edits, errors = [], []
    tree = ast.parse(text, filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            # Replacing the full dotted uses preserves both aliased and plain bindings.
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        assert node.end_lineno is not None and node.end_col_offset is not None
        module = node.module or ""
        if module == OLD and any(a.name in MOVES for a in node.names):
            value = parent_import(node, lines)
        elif any(module == f"{OLD}.{name}" for name in MOVES):
            segment = ast.get_source_segment(text, node)
            assert segment is not None
            value = references(segment)
        else:
            continue
        if node.level:
            errors.append(f"{path.relative_to(root)}:{node.lineno}: unsupported relative builder import")
            continue
        prefix = lines[node.lineno - 1][:node.col_offset]
        suffix = lines[node.end_lineno - 1][node.end_col_offset:].strip()
        if prefix.strip() or (suffix and not suffix.startswith("#")):
            errors.append(f"{path.relative_to(root)}:{node.lineno}: unsupported inline import")
        start = sum(map(len, lines[:node.lineno - 1])) + node.col_offset
        end = sum(map(len, lines[:node.end_lineno - 1])) + node.end_col_offset
        # Include trailing comment once when splitting a mixed import.
        if module == OLD:
            end = sum(map(len, lines[:node.end_lineno - 1])) + len(lines[node.end_lineno - 1].rstrip("\r\n"))
        edits.append((start, end, value))
    for start, end, value in sorted(edits, reverse=True):
        text = text[:start] + value + text[end:]
    return text, errors


def rewrite(path: Path, root: Path) -> tuple[str, list[str]]:
    text, errors = import_edits(path, root)
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.ImportFrom) and node.level and any(a.name in MOVES for a in node.names):
            errors.append(f"{path.relative_to(root)}:{node.lineno}: unsupported relative builder import")
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
                and node.args and isinstance(node.args[0], ast.Name) and node.args[0].id == OLD):
            errors.append(f"{path.relative_to(root)}:{node.lineno}: unsupported dynamic support attribute")
        if isinstance(node, ast.ImportFrom) and node.module == OLD and any(a.name == "*" for a in node.names):
            errors.append(f"{path.relative_to(root)}:{node.lineno}: unsupported support wildcard import")
        if isinstance(node, ast.Import) and any(a.name == OLD and a.asname for a in node.names):
            errors.append(f"{path.relative_to(root)}:{node.lineno}: unsupported aliased support binding")
    text = references(text)
    ast.parse(text)
    return text, errors


def plan(root: Path) -> tuple[list[tuple[Path, str]], list[str]]:
    edits, errors = [], []
    for folder in ("tests",):
        for path in sorted((root / folder).rglob("*.py")):
            if "_vendor" in path.parts or path.name == Path(__file__).name:
                continue
            text = path.read_text()
            if not re.search(r"\b(plans|cfgs)\b", text):
                continue
            new, unsupported = rewrite(path, root)
            errors.extend(unsupported)
            if text != new:
                edits.append((path, new))
    docs = sorted((root / "docs/design").rglob("*.md"))
    for path in docs:
        text = path.read_text()
        new = references(text)
        if new != text:
            edits.append((path, new))
    return edits, errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    root = parser.parse_args().root.resolve()
    edits, errors = plan(root)
    moves = {}
    for name in MOVES:
        source = root / f"tests/support/{name}.py"
        folder = "packages/testkit/src/tltestkit"
        target = root / folder / f"{name}.py"
        if source.exists() == target.exists():
            errors.append(f"expected exactly one of {source} and {target}")
        moves[source] = target
    print(f"preflight: {len(edits)} rewrites; {len(errors)} unsupported forms")
    if errors:
        raise SystemExit("No files written:\n" + "\n".join(errors))
    for source, target in moves.items():
        if source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            source.rename(target)
    for path, text in edits:
        moves.get(path, path).write_text(text)
    print(f"rewrote {len(edits)} files; test builders moved")


if __name__ == "__main__":
    main()
