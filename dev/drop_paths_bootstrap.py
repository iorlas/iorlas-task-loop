"""Remove pytest-redundant support.paths imports; preflight before writing.

Use --dry-run for a full report, --limit N and/or --paths P... for a subset.
Support helpers retain their import-time bootstrap. Standalone test execution
is outside this migration's scope. After writes, run the printed pinned Ruff
command (I,F401) to sort imports and remove unused preamble imports. Ruff is
intentionally explicit: review its additional unused-import fixes separately.
"""
import argparse
import ast
import shlex
import tomllib
from pathlib import Path

PREAMBLE = 'sys.path.insert(0, str(Path(__file__).resolve().parents[1]))'


def rewrite(text: str, relative: Path) -> tuple[str, list[str]]:
    """Conservatively remove whole, top-level, unaliased side-effect imports."""
    tree = ast.parse(text, filename=str(relative))
    nodes = list(ast.walk(tree))
    targets = [n for n in nodes if isinstance(n, ast.Import)
               and any(a.name == 'support.paths' for a in n.names)]
    if not targets:
        return text, []
    if relative == Path('tests/conftest.py'):
        return text, ['pytest bootstrap owner']
    if relative.is_relative_to('tests/support'):
        return text, ['support helper: import-time bootstrap may be required']
    if any(isinstance(n, ast.Name) and n.id == 'support' and isinstance(n.ctx, ast.Load) for n in nodes):
        return text, ['support binding used (attribute or dynamic access)']
    lines = text.splitlines(keepends=True)
    remove: set[int] = set()
    reports = []
    for node in targets:
        line = lines[node.lineno - 1]
        suffix = line[node.end_col_offset:].strip()
        if (node not in tree.body or len(node.names) != 1 or node.names[0].asname
                or node.lineno != node.end_lineno or node.col_offset
                or (suffix and not suffix.startswith('#'))):
            reports.append(f'line {node.lineno}: nonstandard import (kept)')
            continue
        remove.add(node.lineno - 1)
        index = node.lineno - 2
        if index >= 0 and lines[index].strip() == PREAMBLE:
            # Only the exact adjacent call is eligible; retain it if either
            # binding is read anywhere else, including before this preamble.
            call_line = index + 1
            used = any(isinstance(n, ast.Name) and n.id in {'Path', 'sys'}
                       and isinstance(n.ctx, ast.Load) and n.lineno != call_line for n in nodes)
            if used:
                reports.append(f'line {call_line}: preamble kept: Path/sys used elsewhere')
            else:
                remove.add(index)
                # Remove the separator belonging to this pair, never comments.
                if index > 0 and not lines[index - 1].strip():
                    remove.add(index - 1)
    result = ''.join(line for i, line in enumerate(lines) if i not in remove)
    ast.parse(result, filename=str(relative))
    return result, reports


def plan(root: Path, paths: list[str]) -> tuple[list[tuple[Path, str]], list[tuple[Path, str]]]:
    """Validate all selected inputs and outputs before returning any writes."""
    tests = (root / 'tests').resolve()
    if not tests.is_dir():
        raise ValueError(f'missing tests directory: {tests}')
    selected = set()
    for name in paths:
        path = (root / name).resolve()
        if not path.is_relative_to(tests) or not path.exists():
            raise ValueError(f'path must exist under tests/: {name}')
        if path.is_file() and path.suffix != '.py':
            raise ValueError(f'expected Python file: {name}')
        selected.update(path.rglob('*.py') if path.is_dir() else [path])
    edits, reports = [], []
    for path in sorted(selected if paths else tests.rglob('*.py')):
        if not path.resolve().is_relative_to(tests):
            raise ValueError(f'symlink outside tests/: {path}')
        relative = path.relative_to(root)
        text = path.read_text(encoding='utf-8')
        new, reasons = rewrite(text, relative)
        reports.extend((relative, reason) for reason in reasons)
        if new != text:
            edits.append((path, new))
    return edits, reports


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--limit', type=int)
    parser.add_argument('--paths', nargs='+', default=[])
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.limit is not None and args.limit < 0:
        parser.error('--limit must be nonnegative')
    root = args.root.resolve()
    try:
        pin = tomllib.loads((root / 'mise.toml').read_text())['tools']['ruff']
        edits, reports = plan(root, args.paths)
    except (ValueError, SyntaxError, OSError, KeyError) as error:
        parser.exit(1, f'preflight failed; no files written: {error}\n')
    kept = {p for p, _ in reports if root / p not in {p for p, _ in edits}}
    print(f'preflight: {len(edits)} files would change; {len(kept)} bootstrap files kept')
    for path, reason in reports:
        print(f'KEEP {path}: {reason}')
    selected = edits if args.limit is None else edits[:args.limit]
    for path, text in selected:
        print(f"{'WOULD CHANGE' if args.dry_run else 'CHANGE'} {path.relative_to(root)}")
        if not args.dry_run:
            path.write_text(text, encoding='utf-8')
    if selected:
        command = ['uv', 'tool', 'run', f'ruff@{pin}', 'check', '--fix', '--select', 'I,F401',
                   *(str(p.relative_to(root)) for p, _ in selected)]
        print(f'Run from {root}:\n{shlex.join(command)}')


if __name__ == '__main__':
    main()
