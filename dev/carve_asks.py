"""Move asks into its workspace member; preflight first, rerun with --root DIR."""
import argparse
import ast
import shutil
from pathlib import Path

APP = 'taskloop' + '.app.asks'
DOMAINS = {'hold': 'hold', 'similar': 'similar', 'matchers': 'matchers'}


def parent_binding(node: ast.ImportFrom, domains: dict[str, str]) -> str:
    selected = {'asks'} if node.module == 'taskloop.app' else {'asks', 'timespec'}
    if node.module == 'taskloop.domain.asks':
        selected = set(domains)
    replacement = []
    remaining = [a for a in node.names if a.name not in selected]
    if remaining:
        replacement.append('from ' + str(node.module) + ' import ' + ', '.join(
            a.name + (' as ' + a.asname if a.asname else '') for a in remaining))
    for alias in node.names:
        if alias.name not in selected:
            continue
        if alias.name == 'asks':
            replacement.append('import tlasks as ' + (alias.asname or 'asks'))
        else:
            target = domains.get(alias.name, alias.name) if node.module == 'taskloop.domain.asks' else alias.name
            binding = alias.asname or alias.name
            replacement.append('from tlasks import ' + target + (' as ' + binding if target != binding else ''))
    return ('\n' + ' ' * node.col_offset).join(replacement)


def rewrite(text: str, domains: dict[str, str] = DOMAINS) -> tuple[str, list[str]]:
    errors = []
    lines = text.splitlines(keepends=True)
    edits = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import) and any(a.name.startswith((APP, 'taskloop.domain.asks', 'taskloop.domain.timespec'))
                                                 and not a.asname for a in node.names):
            errors.append(f'line {node.lineno}: unsupported unaliased asks import')
        if not isinstance(node, ast.ImportFrom):
            continue
        parent = node.module in {'taskloop.app', 'taskloop.domain', 'taskloop.domain.asks'}
        names = {'asks'} if node.module == 'taskloop.app' else {'asks', 'timespec'}
        if node.module == 'taskloop.domain.asks':
            names = set(DOMAINS)
        selected = [a for a in node.names if a.name in names] if parent else []
        if selected:
            if node.module == 'taskloop.domain' and any(a.name == 'asks' for a in selected) and domains != DOMAINS:
                errors.append(f'line {node.lineno}: domain asks package binding with renamed modules')
                continue
            if lines[node.lineno - 1][:node.col_offset].strip():
                errors.append(f'line {node.lineno}: unsupported inline parent binding')
                continue
            start = sum(len(line) for line in lines[:node.lineno - 1]) + node.col_offset
            end = sum(len(line) for line in lines[:node.end_lineno - 1]) + node.end_col_offset
            edits.append((start, end, parent_binding(node, domains)))
        in_stage = node.module and (node.module == APP or node.module.startswith(APP + '.') or
                                    node.module.startswith('taskloop.domain.asks') or node.module == 'taskloop.domain.timespec')
        if in_stage and any(a.name == '*' for a in node.names):
            errors.append(f'line {node.lineno}: unsupported asks star import')
    for start, end, replacement in sorted(edits, reverse=True):
        text = text[:start] + replacement + text[end:]
    text = text.replace(APP, 'tlasks')
    for name, target in domains.items():
        text = text.replace('taskloop.domain.asks.' + name, 'tlasks.' + target)
    text = text.replace('taskloop.domain.asks', 'tlasks')
    text = text.replace('taskloop.domain.timespec', 'tlasks.timespec')
    return text, errors


def domain_names(app: Path, target: Path) -> dict[str, str]:
    names = {p.stem for p in app.glob('*.py')}
    domains = {}
    for name in DOMAINS:
        dest = name
        if names:
            while dest in names or (target / (dest + '.py')).exists():
                dest = 'domain_' + dest
        else:
            while (target / ('domain_' + dest + '.py')).exists():
                dest = 'domain_' + dest
        if dest != name:
            print(f'domain name clash: {name} -> {dest}')
        domains[name] = dest
    return domains


def plan(root: Path) -> tuple[dict[Path, Path], list[tuple[Path, str]], list[str]]:
    app = root / 'src/taskloop/app/asks'
    target = root / 'packages/asks/src/tlasks'
    domains = domain_names(app, target)
    moves = {p: target / p.name for p in app.glob('*.py')}
    for name, dest in domains.items():
        source = root / 'src/taskloop/domain/asks' / (name + '.py')
        if source.exists():
            moves[source] = target / (dest + '.py')
        elif not (target / (dest + '.py')).exists():
            return moves, [], [f'missing source and target: {source}']
    source = root / 'src/taskloop/domain/timespec.py'
    if source.exists():
        moves[source] = target / 'timespec.py'
    elif not (target / 'timespec.py').exists():
        errors = ['missing timespec source and target']
        return moves, [], errors
    if (app / 'ruff.toml').exists():
        moves[app / 'ruff.toml'] = root / 'packages/asks/ruff.toml'
    errors = [f'both source and target exist: {p}, {q}' for p, q in moves.items() if q.exists()]
    if not (app / '__init__.py').exists() and not (target / '__init__.py').exists():
        errors.append('missing asks __init__.py')
    errors += [f'unexpected asks file: {p}' for p in app.rglob('*')
               if p.is_file() and p.suffix != '.py' and p.name != 'ruff.toml' and '__pycache__' not in p.parts]
    errors += [f'unexpected asks directory: {p}' for p in app.glob('*')
               if p.is_dir() and p.name != '__pycache__']
    domain = root / 'src/taskloop/domain/asks'
    errors += [f'unexpected domain asks file: {p}' for p in domain.rglob('*')
               if p.is_file() and p.name not in {name + '.py' for name in DOMAINS} | {'__init__.py'}
               and '__pycache__' not in p.parts]
    errors += [f'unexpected domain asks directory: {p}' for p in domain.glob('*')
               if p.is_dir() and p.name != '__pycache__']
    init = domain / '__init__.py'
    if init.exists() and any(not isinstance(n, ast.Expr) or not isinstance(n.value, ast.Constant)
                             or not isinstance(n.value.value, str) for n in ast.parse(init.read_text()).body):
        errors.append('domain asks __init__.py has code; cannot discard it')
    edits, rewrite_errors = rewrites(root, domains)
    return moves, edits, errors + rewrite_errors


def rewrites(root: Path, domains: dict[str, str]) -> tuple[list[tuple[Path, str]], list[str]]:
    errors = []
    edits = []
    for folder in ('src', 'packages', 'tests', 'dev', 'skills'):
        for path in sorted((root / folder).rglob('*.py')):
            if '_vendor' in path.parts or path.name == Path(__file__).name:
                continue
            text = path.read_text()
            try:
                new, unsupported = rewrite(text, domains)
            except SyntaxError as exc:
                errors.append(f"{path.relative_to(root)}: {exc}")
                continue
            errors.extend(f'{path.relative_to(root)}:{e}' for e in unsupported)
            if text != new:
                edits.append((path, new))
    return edits, errors


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
    domain = args.root.resolve() / "src/taskloop/domain/asks"
    if domain.exists():
        for cache in domain.rglob("__pycache__"):
            shutil.rmtree(cache)
        init = domain / "__init__.py"
        if init.exists():
            init.unlink()
        domain.rmdir()
    app = args.root.resolve() / "src/taskloop/app/asks"
    if app.exists():
        for cache in app.rglob("__pycache__"):
            shutil.rmtree(cache)
        app.rmdir()


if __name__ == '__main__':
    main()
