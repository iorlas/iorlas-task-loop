"""Move gate into its workspace member; preflight first, rerun with --root DIR.

Filesystem renames preserve git history without changing the index. Tests stay put.
"""
import argparse
import ast
import re
import shutil
from pathlib import Path

APP = 'taskloop' + '.app.checks'
DOMAIN = 'taskloop' + '.domain.checks'


def rewrite(text: str) -> tuple[str, list[str]]:
    lines = text.splitlines(keepends=True)
    edits, errors = [], []
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module == 'taskloop.domain' and any(a.name == 'checks' for a in node.names):
            errors.append(f'line {node.lineno}: from taskloop.domain import checks requires explicit binding review')
        if node.module == 'taskloop.app' and any(a.name == 'checks' for a in node.names):
            errors.append(f'line {node.lineno}: unsupported app checks parent binding')
        if node.module != APP:
            continue
        assert node.end_lineno is not None and node.end_col_offset is not None
        if any(a.name == '*' for a in node.names):
            errors.append(f'line {node.lineno}: unsupported checks star import')
        groups: dict[str, list[str]] = {}
        for alias in node.names:
            parent = APP if alias.name == 'step' else 'tlgate'
            groups.setdefault(parent, []).append(alias.name + (f' as {alias.asname}' if alias.asname else ''))
        prefix = lines[node.lineno - 1][:node.col_offset]
        suffix = lines[node.end_lineno - 1][node.end_col_offset:].rstrip('\n')
        if prefix.strip() or (suffix.strip() and not suffix.lstrip().startswith('#')):
            errors.append(f'line {node.lineno}: unsupported inline import')
        value = ('\n' + prefix).join(f"from {parent} import {', '.join(names)}{suffix}" for parent, names in groups.items())
        start = sum(map(len, lines[:node.lineno - 1])) + node.col_offset
        end = sum(map(len, lines[:node.end_lineno - 1])) + len(lines[node.end_lineno - 1].rstrip('\n'))
        edits.append((start, end, value))
    for start, end, value in sorted(edits, reverse=True):
        text = text[:start] + value + text[end:]
    text = text.replace(DOMAIN, 'tlgate.domain')
    text = re.sub(re.escape(APP) + r'\.(?!step\b)(\w+)', r'tlgate.\1', text)
    return text, errors


def plan(root: Path) -> tuple[dict[Path, Path], list[tuple[Path, str]], list[str]]:
    app = root / 'src/taskloop/app/checks'
    target = root / 'packages/gate/src/tlgate'
    moves = {p: target / p.name for p in app.glob('*.py') if p.name not in {'step.py', '__init__.py'}}
    domain = root / 'src/taskloop/domain/checks'
    moves.update({p: target / 'domain' / p.relative_to(domain) for p in domain.rglob('*.py')})
    if (app / 'ruff.toml').exists():
        moves[app / 'ruff.toml'] = root / 'packages/gate/ruff.toml'
    errors = [f'unexpected domain file: {p}' for p in domain.rglob('*')
              if p.is_file() and p.suffix != '.py' and '__pycache__' not in p.parts]
    errors += [f'both source and target exist: {p}, {q}' for p, q in moves.items() if q.exists()]
    if not (app / 'step.py').is_file() or not (app / '__init__.py').is_file():
        errors.append('missing shell checks step.py or __init__.py')
    edits = []
    for folder in ('src', 'packages', 'tests', 'dev', 'skills'):
        for path in sorted((root / folder).rglob('*.py')):
            if '_vendor' in path.parts or path.name == Path(__file__).name:
                continue
            text = path.read_text()
            if APP not in text and DOMAIN not in text and 'from taskloop.domain import' not in text:
                continue
            new, unsupported = rewrite(text)
            errors.extend(f'{path.relative_to(root)}:{e}' for e in unsupported)
            if text != new:
                edits.append((path, new))
    return moves, edits, errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    root = parser.parse_args().root.resolve()
    moves, edits, errors = plan(root)
    print(f'preflight: {len(moves)} moves, {len(edits)} rewrites, {len(errors)} unsupported forms')
    if errors:
        raise SystemExit('No files written:\n' + '\n'.join(errors))
    target = root / 'packages/gate/src/tlgate'
    target.mkdir(parents=True, exist_ok=True)
    init = target / '__init__.py'
    if not init.exists():
        init.write_text((root / 'src/taskloop/app/checks/__init__.py').read_text())
    for source, dest in moves.items():
        dest.parent.mkdir(parents=True, exist_ok=True)
        source.rename(dest)
    for path, text in edits:
        moves.get(path, path).write_text(text)
    ruff = root / 'packages/gate/ruff.toml'
    ruff.write_text(ruff.read_text().replace('extend = "../ruff.toml"', 'extend = "../kernel/ruff.toml"'))
    domain = root / 'src/taskloop/domain/checks'
    if domain.exists():
        for folder in sorted(domain.rglob('*'), reverse=True):
            if folder.is_dir() and folder.name == '__pycache__':
                shutil.rmtree(folder)
            elif folder.is_dir() and folder.exists():
                folder.rmdir()
        domain.rmdir()


if __name__ == '__main__':
    main()
