"""Move gate helpers; rerun after rebasing with --root DIR.

Preflight all Python uses before writing. Unsupported executable uses abort.
Historical dev strings are reported and retained. Git detects filesystem renames
when the index is unavailable.
"""
import argparse
import ast
import re
import subprocess
from pathlib import Path

MOVES = {
    "check_files": "tlkernel",
    "profile_at": "tlkernel",
    "base_tree": "taskloop.app.checks",
}
OLD = "taskloop" + ".adapters"


def references(text: str) -> str:
    for name, parent in MOVES.items():
        text = text.replace(f"{OLD}.{name}", f"{parent}.{name}")
        text = text.replace(f"adapters.{name}", f"{parent}.{name}")
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
            for alias in node.names:
                if any(alias.name == f"{OLD}.{name}" or alias.name.startswith(f"{OLD}.{name}.") for name in MOVES):
                    errors.append(f"{path.relative_to(root)}:{node.lineno}: unsupported import {alias.name}")
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
    if path.parts[-2:] == ("dev", "split_wire_slots.py"):
        if text != path.read_text():
            errors.append(f"{path.relative_to(root)}: executable import needs manual review")
        if any(name in text for name in MOVES):
            print(f"{path.relative_to(root)}: retained historical import in string constant")
        return path.read_text(), errors
    text = references(text)
    # Parent-module attribute access cannot preserve its binding after the move.
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Attribute) and ast.unparse(node) == OLD:
            errors.append(f"{path.relative_to(root)}:{node.lineno}: unsupported adapters attribute use")
    return text, errors


def plan(root: Path) -> tuple[list[tuple[Path, str]], list[str]]:
    edits, errors = [], []
    for folder in ("src", "packages", "tests", "dev", "skills"):
        for path in sorted((root / folder).rglob("*.py")):
            if "_vendor" in path.parts or path.name == Path(__file__).name:
                continue
            text = path.read_text()
            if not re.search(r"\b(check_files|profile_at|base_tree)\b", text):
                continue
            new, unsupported = rewrite(path, root)
            errors.extend(unsupported)
            if text != new:
                edits.append((path, new))
    for path in sorted((root / "docs/design").rglob("*.md")):
        text = path.read_text()
        new = text.replace("adapters/check_files.py", "tlkernel/check_files.py")
        new = new.replace("adapters.{check_files,base_tree,childenv,profile_at}",
                          "tlkernel.{check_files,profile_at}, app.checks.base_tree, adapters.childenv")
        new = new.replace("adapters.{pidcheck,ident,agent,locks,profile_at}",
                          "adapters.{pidcheck,ident,agent,locks}, tlkernel.profile_at")
        if new != text:
            edits.append((path, new))
    return edits, errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    root = parser.parse_args().root.resolve()
    edits, errors = plan(root)
    moves = {}
    for name, parent in MOVES.items():
        source = root / f"src/taskloop/adapters/{name}.py"
        folder = "packages/kernel/src/tlkernel" if parent == "tlkernel" else "src/taskloop/app/checks"
        target = root / folder / f"{name}.py"
        if source.exists() == target.exists():
            errors.append(f"expected exactly one of {source} and {target}")
        moves[source] = target
    if errors:
        raise SystemExit("No files written:\n" + "\n".join(errors))
    for source, target in moves.items():
        if source.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            moved = subprocess.run(
                ["git", "mv", str(source), str(target)], cwd=root,
                capture_output=True, text=True, check=False,
            )
            if moved.returncode:
                print(f"git mv unavailable: {moved.stderr.strip()}; using rename")
                source.rename(target)
    for path, text in edits:
        moves.get(path, path).write_text(text)
    print(f"rewrote {len(edits)} files; gate helpers moved")


if __name__ == "__main__":
    main()
