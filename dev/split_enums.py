"""Split kernel enums by owner, rewriting tracked Python importers; safe to rerun with --root DIR.

Unsupported module attribute uses are reported before any writes. Successful runs finish with the pinned ruff import sorter.
"""
import argparse
import ast
import io
import subprocess
import tokenize
import tomllib
from pathlib import Path

KERNEL = Path("packages/kernel/src/tlkernel")
OWNERS = {
    "AskKind": "askenums", "AskClass": "askenums", "AskStatus": "askenums",
    "CheckStatus": "checkenums", "LockWhat": "lockenums", "WaitWhat": "waitenums",
}
MODULES = ("askenums", "checkenums", "enums", "lockenums", "waitenums")
WIRE = "tests/contracts/test_wire.py"


def split_source(text: str) -> dict[str, str]:
    """Return module filenames and contents, preserving class source and trailing comments verbatim."""
    lines = text.splitlines(keepends=True)
    classes = [node for node in ast.parse(text).body if isinstance(node, ast.ClassDef)]
    groups: dict[str, list[str]] = {}
    for i, node in enumerate(classes):
        start = min([node.lineno, *(d.lineno for d in node.decorator_list)]) - 1
        end = classes[i + 1].lineno - 1 if i + 1 < len(classes) else len(lines)
        groups.setdefault(OWNERS.get(node.name, "enums"), []).append("".join(lines[start:end]).rstrip("\n"))
    result = {}
    for module, blocks in groups.items():
        owner = "The shared run vocabulary." if module == "enums" else f"The {module.removesuffix('enums')} owner's vocabulary."
        result[module + ".py"] = f'"""{owner}"""\nfrom enum import StrEnum\n\n\n' + "\n\n\n".join(blocks) + "\n"
    return result


def replace_lines(text: str, edits: list[tuple[int, int, str]]) -> str:
    lines = text.splitlines(keepends=True)
    for start, end, replacement in sorted(edits, reverse=True):
        lines[start - 1:end] = [replacement]
    return "".join(lines)


def import_line(text: str, node: ast.ImportFrom, module: str, names: list[str]) -> str:
    lines = text.splitlines(keepends=True)
    indent = lines[node.lineno - 1][:node.col_offset]
    comments = [token.string for token in tokenize.generate_tokens(io.StringIO(text).readline)
                if token.type == tokenize.COMMENT and node.lineno <= token.start[0] <= node.end_lineno
                and token.string.startswith("# noqa")]
    suffix = "  " + "  ".join(dict.fromkeys(comments)) if comments else ""
    return f"{indent}from {module} import {', '.join(sorted(set(names)))}{suffix}\n"


def rewrite_imports(text: str) -> str:
    """Rewrite ImportFrom line ranges, retaining aliases, indentation and noqa comments."""
    edits = []
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.ImportFrom) or node.level or node.module != "tlkernel.enums":
            continue
        groups: dict[str, list[str]] = {}
        for alias in node.names:
            name = alias.name + (f" as {alias.asname}" if alias.asname else "")
            groups.setdefault(OWNERS.get(alias.name, "enums"), []).append(name)
        replacement = "".join(import_line(text, node, "tlkernel." + mod, groups[mod]) for mod in MODULES if mod in groups)
        edits.append((node.lineno, node.end_lineno, replacement))
    return replace_lines(text, edits)


def rewrite_wire(text: str) -> str:
    """Extend the wire contract's enum enumeration without changing its loop body."""
    edits = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.ImportFrom) and node.module == "tlkernel" and any(a.name == "enums" for a in node.names):
            names = [a.name + (f" as {a.asname}" if a.asname else "") for a in node.names]
            names.extend(m for m in MODULES if m != "enums")
            edits.append((node.lineno, node.end_lineno, import_line(text, node, "tlkernel", names)))
        if isinstance(node, ast.For) and ast.get_source_segment(text, node.iter) == "vars(enums).values()":
            lines = text.splitlines(keepends=True)
            old = "".join(lines[node.iter.lineno - 1:node.iter.end_lineno])
            new = "(e for module in (enums, askenums, checkenums, lockenums, waitenums) for e in vars(module).values())"
            edits.append((node.iter.lineno, node.iter.end_lineno, old.replace("vars(enums).values()", new)))
    return replace_lines(text, edits)


def unsupported(text: str) -> list[str]:
    """Find enum module imports and moved attributes, including module aliases."""
    tree = ast.parse(text)
    aliases = {"enums", "tlkernel.enums"}
    reports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "tlkernel":
            aliases.update(a.asname or a.name for a in node.names if a.name == "enums")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "tlkernel.enums":
                    aliases.add(alias.asname or "tlkernel.enums")
                    reports.append(f"{node.lineno}: import tlkernel.enums")
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in OWNERS and ast.unparse(node.value) in aliases:
            reports.append(f"{node.lineno}: {ast.unparse(node)}")
    return sorted(set(reports))


def migrate(root: Path, names: list[str]) -> int:
    """Apply the migration to supplied tracked paths; no git or subprocess calls here."""
    sources = {}
    reports = []
    for name in sorted(set(names)):
        path = root / name
        if (not name.startswith(("src/", "packages/", "tests/", "dev/", "skills/")) or not name.endswith(".py")
                or name == "dev/split_enums.py" or name.startswith("skills/task-loop/_vendor/") or not path.is_file()):
            continue
        sources[name] = path.read_text(encoding="utf-8")
        reports.extend(f"{name}:{report}" for report in unsupported(sources[name]))
    if reports:
        print("Unsupported enum uses (fix by hand):\n" + "\n".join(reports))
        return 1
    enum_path = (KERNEL / "enums.py").as_posix()
    source = (root / enum_path).read_text(encoding="utf-8")
    moved = sum(isinstance(n, ast.ClassDef) and n.name in OWNERS for n in ast.parse(source).body)
    outputs = {name: rewrite_imports(rewrite_wire(text) if name == WIRE else text) for name, text in sources.items()}
    outputs.update({(KERNEL / name).as_posix(): text for name, text in split_source(source).items()})
    changed = 0
    for name, text in outputs.items():
        path = root / name
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            path.write_text(text, encoding="utf-8")
            changed += 1
    print(f"files rewritten: {changed}; names moved: {moved}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    root = parser.parse_args().root.resolve()
    tracked = subprocess.run(["git", "ls-files", "-z", "--", "*.py"], cwd=root, capture_output=True, text=True, check=True)
    status = migrate(root, tracked.stdout.rstrip("\0").split("\0"))
    if status:
        return status
    pin = tomllib.loads((root / "mise.toml").read_text(encoding="utf-8"))["tools"]["ruff"]
    return subprocess.run(["uv", "tool", "run", f"ruff@{pin}", "check", "--select", "I", "--fix", "-q", "."],
                          cwd=root, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
