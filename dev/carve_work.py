"""Carve work slices by rename, after an AST preflight; rerunnable with --root DIR."""
import argparse
import ast
import re
from pathlib import Path

# Source, destination: slice 2 can add plan here.
SLICES = (
    ('taskloop.app.review', 'tlwork.review'),
    ('taskloop.domain.review', 'tlwork.review'),
    ('taskloop.domain.work', 'tlwork.work'),
    ('taskloop.domain.prompts', 'tlwork.prompts'),
)


def parent_edits(text: str) -> tuple[list[tuple[str, str]], list[str]]:
    edits, errors = [], []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                moved = any(alias.name == old or alias.name.startswith(old + '.') for old, _ in SLICES)
                if moved and not alias.asname:
                    errors.append(f'line {node.lineno}: unsupported unaliased dotted import')
        if not isinstance(node, ast.ImportFrom):
            continue
        for old, new in SLICES:
            parent, _, child = old.rpartition('.')
            if node.module != parent or not any(a.name == child for a in node.names):
                continue
            if len(node.names) != 1:
                errors.append(f'line {node.lineno}: unsupported mixed parent binding')
                continue
            alias = node.names[0]
            value = f'from {new.rpartition(".")[0]} import {new.rpartition(".")[2]}'
            value += f' as {alias.asname}' if alias.asname else ''
            edits.append((ast.get_source_segment(text, node) or '', value))
    return edits, errors


def rewrite(text: str, python: bool = True) -> tuple[str, list[str]]:
    edits, errors = parent_edits(text) if python else ([], [])
    for old, new in edits:
        text = text.replace(old, new)
    for old, new in SLICES:
        text = re.sub(re.escape(old) + r'\b', new, text)
        text = text.replace('src/' + old.replace('.', '/'), 'packages/work/src/' + new.replace('.', '/'))
    return text, errors


def source_files(root: Path):
    for folder in ('src', 'packages', 'tests', 'dev', 'skills', 'docs/design'):
        for path in sorted((root / folder).rglob('*')):
            if (path.is_file() and path.suffix in {'.py', '.md', '.toml'}
                    and '_vendor' not in path.parts and path.name != Path(__file__).name):
                yield path


def plan(root: Path) -> tuple[dict[Path, Path], list[tuple[Path, str]], list[str]]:
    moves, edits, errors = {}, [], []
    for old, new in SLICES:
        source = root / 'src' / old.replace('.', '/')
        target = root / 'packages/work/src' / new.replace('.', '/')
        for path in source.rglob('*'):
            if not path.is_file() or '__pycache__' in path.parts or any(p.startswith('.') for p in path.relative_to(source).parts):
                continue
            if path.suffix != '.py' and path.name != 'ruff.toml':
                errors.append(f'unexpected source file: {path}')
                continue
            dest = target / path.relative_to(source)
            if old == 'taskloop.domain.review' and path.name == '__init__.py':
                dest = root / 'packages/work/src/tlwork/__init__.py'
            if path.name == 'ruff.toml':
                dest = root / 'packages/work/ruff.toml'
            if dest.exists() or dest in moves.values():
                errors.append(f'destination collision: {dest}')
            moves[path] = dest
    for path in source_files(root):
        text = path.read_text()
        new, unsupported = rewrite(text, path.suffix == '.py')
        errors.extend(f'{path}: {e}' for e in unsupported)
        if new != text:
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
    for source, dest in moves.items():
        dest.parent.mkdir(parents=True, exist_ok=True)
        source.rename(dest)
    for path, text in edits:
        moves.get(path, path).write_text(text)
    config = root / 'packages/work/ruff.toml'
    if config.exists():
        config.write_text(config.read_text().replace('extend = "../ruff.toml"', 'extend = "../../ruff.toml"'))


if __name__ == '__main__':
    main()
