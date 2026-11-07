"""Move slots into its workspace member; preflight first, rerun with --root DIR."""
import argparse
import ast
import shutil
from pathlib import Path

APP = 'taskloop' + '.app.slots'
DOMAINS = {'slot_liveness': 'liveness', 'slot_env': 'slot_env'}


def rewrite(text: str) -> tuple[str, list[str]]:
    errors = []
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.module == 'taskloop.app' and any(a.name == 'slots' for a in node.names):
            errors.append(f'line {node.lineno}: unsupported app slots parent binding')
        if node.module == 'taskloop.domain' and any(a.name in DOMAINS for a in node.names):
            errors.append(f'line {node.lineno}: unsupported domain slots parent binding')
        if node.module and (node.module == APP or node.module.startswith(APP + '.') or
                            node.module in {'taskloop.domain.' + name for name in DOMAINS}):
            if any(a.name == '*' for a in node.names):
                errors.append(f'line {node.lineno}: unsupported slots star import')
    text = text.replace(APP, 'tlslots')
    for name, target in DOMAINS.items():
        text = text.replace('taskloop.domain.' + name, 'tlslots.' + target)
    return text, errors


def plan(root: Path) -> tuple[dict[Path, Path], list[tuple[Path, str]], list[str]]:
    app = root / 'src/taskloop/app/slots'
    target = root / 'packages/slots/src/tlslots'
    moves = {p: target / p.name for p in app.glob('*.py')}
    for name, dest in DOMAINS.items():
        source = root / 'src/taskloop/domain' / (name + '.py')
        if source.exists():
            moves[source] = target / (dest + '.py')
        elif not (target / (dest + '.py')).exists():
            return moves, [], [f'missing source and target: {source}']
    if (app / 'ruff.toml').exists():
        moves[app / 'ruff.toml'] = root / 'packages/slots/ruff.toml'
    errors = [f'both source and target exist: {p}, {q}' for p, q in moves.items() if q.exists()]
    if not (app / '__init__.py').exists() and not (target / '__init__.py').exists():
        errors.append('missing slots __init__.py')
    errors += [f'unexpected slots file: {p}' for p in app.rglob('*')
               if p.is_file() and p.suffix != '.py' and p.name != 'ruff.toml' and '__pycache__' not in p.parts]
    errors += [f'unexpected slots directory: {p}' for p in app.glob('*')
               if p.is_dir() and p.name != '__pycache__']
    edits = []
    for folder in ('src', 'packages', 'tests', 'dev', 'skills'):
        for path in sorted((root / folder).rglob('*.py')):
            if '_vendor' in path.parts or path.name == Path(__file__).name:
                continue
            text = path.read_text()
            new, unsupported = rewrite(text)
            errors.extend(f'{path.relative_to(root)}:{e}' for e in unsupported)
            if text != new:
                edits.append((path, new))
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
    app = args.root.resolve() / "src/taskloop/app/slots"
    if app.exists():
        for cache in app.rglob("__pycache__"):
            shutil.rmtree(cache)
        app.rmdir()


if __name__ == '__main__':
    main()
