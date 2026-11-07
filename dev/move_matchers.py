"""Move shared text matchers to the kernel; rerunnable with --root DIR.

Unsupported uses are reported before any files are written. Import ordering is
left to the repository's Ruff configuration after the move.
"""
import argparse
import ast
import re
import subprocess
from pathlib import Path

OLD = 'taskloop.domain.matchers'
NEW = 'tlkernel.matchers'
SOURCE = Path('src/taskloop/domain/matchers.py')
TARGET = Path('packages/kernel/src/tlkernel/matchers.py')


def rewrite(text):
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    edits, reports = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0:
            if node.module == OLD:
                edits.append((node.lineno, node.end_lineno, OLD, NEW))
            elif node.module == 'taskloop.domain' and any(a.name == 'matchers' for a in node.names):
                if len(node.names) != 1:
                    reports.append(f'{node.lineno}: mixed domain import: {ast.unparse(node)}')
                else:
                    edits.append((node.lineno, node.end_lineno, 'taskloop.domain', 'tlkernel'))
        elif isinstance(node, ast.Import) and any(a.name == OLD for a in node.names):
            reports.append(f'{node.lineno}: unsupported module import: {ast.unparse(node)}')
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and OLD in node.value:
            reports.append(f'{node.lineno}: old module in string; review manually')
    for start, end, old, new in sorted(edits, reverse=True):
        block = ''.join(lines[start - 1:end])
        pattern = r'(\bfrom\s+)' + re.escape(old) + r'(?=\s+import\b)'
        rewritten, count = re.subn(pattern, lambda match, new=new: match[1] + new, block, count=1)
        if not count:
            reports.append(f'{start}: unsupported import formatting')
        lines[start - 1:end] = [rewritten]
    result = ''.join(lines)
    ast.parse(result)
    return result, reports


def migrate(root, names):
    outputs, reports = {}, []
    for name in names:
        path = root / name
        if not name.endswith('.py') or name == 'dev/move_matchers.py' or '_vendor/' in name or not path.is_file():
            continue
        text = path.read_text()
        try:
            rewritten, problems = rewrite(text)
        except SyntaxError as exc:
            reports.append(f'{name}: cannot parse: {exc}')
            continue
        reports.extend(f'{name}:{problem}' for problem in problems)
        if rewritten != text:
            outputs[path] = rewritten
    source, target = root / SOURCE, root / TARGET
    if source.exists() and target.exists():
        reports.append(f'{TARGET}: destination already exists while source still exists')
    if not source.exists() and not target.exists():
        reports.append(f'{SOURCE}: neither source nor destination exists')
    if reports:
        print('Unsupported uses (no files written):\n' + '\n'.join(reports))
        return 1
    for path, text in outputs.items():
        path.write_text(text)
    moved = source.exists()
    if moved:
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
    print(f'files rewritten: {len(outputs)}; files moved: {int(moved)}')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    root = parser.parse_args().root.resolve()
    tracked = subprocess.run(['git', 'ls-files', '-z'], cwd=root, capture_output=True, text=True, check=True)
    return migrate(root, tracked.stdout.rstrip('\0').split('\0'))


if __name__ == '__main__':
    raise SystemExit(main())
