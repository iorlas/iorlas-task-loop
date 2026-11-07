"""Move release into its workspace member; preflight first, rerun with --root DIR."""
import argparse
import ast
import shutil
from pathlib import Path

APP = 'taskloop' + '.app.release'


def rewrite(text: str) -> tuple[str, list[str]]:
    errors = []
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module == 'taskloop.app' and any(a.name in {'release', '*'} for a in node.names):
            errors.append(f'line {node.lineno}: unsupported app release parent binding')
        in_stage = node.module and (node.module == APP or node.module.startswith(APP + '.'))
        if in_stage and any(a.name == '*' for a in node.names):
            errors.append(f'line {node.lineno}: unsupported release star import')
    text = text.replace(APP, 'tlrelease')
    return text, errors


def plan(root: Path) -> tuple[dict[Path, Path], list[tuple[Path, str]], list[str]]:
    app = root / 'src/taskloop/app/release'
    target = root / 'packages/release/src/tlrelease'
    moves = {p: target / p.name for p in app.glob('*.py')}
    if (app / 'ruff.toml').exists():
        moves[app / 'ruff.toml'] = root / 'packages/release/ruff.toml'
    errors = [f'both source and target exist: {p}, {q}' for p, q in moves.items() if q.exists()]
    if not (app / '__init__.py').exists() and not (target / '__init__.py').exists():
        errors.append('missing release __init__.py')
    errors += [f'unexpected release file: {p}' for p in app.rglob('*')
               if p.is_file() and p.suffix != '.py' and p.name != 'ruff.toml' and '__pycache__' not in p.parts]
    errors += [f'unexpected release directory: {p}' for p in app.glob('*')
               if p.is_dir() and p.name != '__pycache__']
    edits = []
    for folder in ('src', 'packages', 'tests', 'docs', 'dev', 'skills'):
        for path in sorted((root / folder).rglob('*')):
            if not path.is_file() or path.suffix not in {'.py', '.md', '.toml'}:
                continue
            if '_vendor' in path.parts or path.name == Path(__file__).name:
                continue
            text = path.read_text()
            new, unsupported = rewrite(text) if path.suffix == '.py' else (text.replace(APP, 'tlrelease'), [])
            errors.extend(f'{path.relative_to(root)}:{e}' for e in unsupported)
            if text != new:
                edits.append((path, new))
    contract = root / '.importlinter'
    if contract.exists():
        text = contract.read_text()
        if APP in text:
            edits.append((contract, text.replace(APP, 'tlrelease')))
    return moves, edits, errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--preflight', action='store_true')
    args = parser.parse_args()
    moves, edits, errors = plan(args.root.resolve())
    print(f'preflight: {len(moves)} moves, {len(edits)} rewrites, {len(errors)} unsupported forms')
    if errors:
        raise SystemExit('No files written:\n' + '\n'.join(errors))
    if args.preflight:
        return
    for source, dest in moves.items():
        dest.parent.mkdir(parents=True, exist_ok=True)
        source.rename(dest)
    for path, text in edits:
        moves.get(path, path).write_text(text)
    app = args.root.resolve() / "src/taskloop/app/release"
    if app.exists():
        for cache in app.rglob("__pycache__"):
            shutil.rmtree(cache)
        app.rmdir()


if __name__ == '__main__':
    main()
