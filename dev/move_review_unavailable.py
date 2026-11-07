"""Cut review's exception edge with an AST preflight; rerunnable with --root DIR."""
import argparse
import ast
from pathlib import Path

MOVES = (('tlwork.review.availability', 'tlkernel.reviewunavailable'),)


def import_groups(node):
    groups = {}
    for alias in node.names:
        module, name = node.module, alias.name
        if module == 'tlwork.api' and name == 'ReviewUnavailable':
            module = 'tlkernel.reviewunavailable'
        for old, new in MOVES:
            if module == old:
                module = new
            elif module == old.rpartition('.')[0] and name == old.rpartition('.')[2]:
                module, name = new.rpartition('.')[0], new.rpartition('.')[2]
                if not alias.asname:
                    name += ' as ' + alias.name
        value = name + (' as ' + alias.asname if alias.asname else '')
        groups.setdefault(module, []).append(value)
    return groups


def unsupported(tree):
    errors = []
    parents = {old.rpartition('.')[0] for old, _ in MOVES}
    for node in ast.walk(tree):
        if (isinstance(node, ast.ImportFrom) and node.module in parents | {old for old, _ in MOVES} | {'tlwork.api'}
                and any(a.name == '*' for a in node.names)):
            errors.append(f'{node.lineno}: unsupported wildcard import')
        if isinstance(node, ast.Attribute) and ast.unparse(node) in {'review.availability'}:
            errors.append(f'{node.lineno}: unsupported parent attribute binding')
    return errors


def rewrite(text):
    tree = ast.parse(text)
    edits, errors = [], unsupported(tree)
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
                a.name == old or a.name.startswith(old + '.') for a in node.names for old, _ in MOVES):
            errors.append(f'{node.lineno}: unsupported dotted import')
        if not isinstance(node, ast.ImportFrom):
            continue
        assert node.end_lineno is not None and node.end_col_offset is not None
        groups = import_groups(node)
        replacement = ('\n' + ' ' * node.col_offset).join(f'from {module} import {", ".join(names)}' for module, names in groups.items())
        original = ast.get_source_segment(text, node)
        if replacement != original and any(module != node.module for module in groups):
            if lines[node.lineno - 1][:node.col_offset].strip():
                errors.append(f'{node.lineno}: unsupported inline import')
            edits.append((offsets[node.lineno - 1] + node.col_offset,
                          offsets[node.end_lineno - 1] + node.end_col_offset, replacement))
    for start, end, value in sorted(edits, reverse=True):
        text = text[:start] + value + text[end:]
    ast.parse(text)
    return text, errors


def references(text):
    for old, new in MOVES:
        text = text.replace('packages/work/src/' + old.replace('.', '/') + '.py', 'packages/kernel/src/' + new.replace('.', '/') + '.py')
        text = text.replace(old, new)
    return text


def remove_export(text):
    """Remove the exception's import and __all__ entry from the old public surface."""
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    edits = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module in {old for old, _ in MOVES}:
            names = [a for a in node.names if a.name != 'ReviewUnavailable']
            if len(names) != len(node.names):
                node.names = names
                edits.append((node.lineno - 1, node.end_lineno, ast.unparse(node) + '\n' if names else ''))
        if (isinstance(node, ast.Assign) and isinstance(node.value, (ast.List, ast.Tuple))
                and any(isinstance(t, ast.Name) and t.id == '__all__' for t in node.targets)):
            for item in node.value.elts:
                if isinstance(item, ast.Constant) and item.value == 'ReviewUnavailable':
                    if lines[item.lineno - 1].strip() not in {'"ReviewUnavailable",', "'ReviewUnavailable',"}:
                        raise ValueError('unsupported inline __all__ entry')
                    edits.append((item.lineno - 1, item.end_lineno, ''))
    for start, end, value in sorted(edits, reverse=True):
        lines[start:end] = [value]
    return ''.join(lines)


def plan(root):
    outputs, errors, moves = {}, [], {}
    for old, new in MOVES:
        source = root / ('packages/work/src/' + old.replace('.', '/') + '.py')
        target = root / ('packages/kernel/src/' + new.replace('.', '/') + '.py')
        if source.exists() == target.exists():
            errors.append(f'expected exactly one of {source} and {target}')
        if source.exists():
            moves[source] = target
    for folder in ('src', 'packages', 'tests', 'dev', 'docs/design'):
        for path in sorted((root / folder).rglob('*')):
            if not path.is_file() or path.suffix not in {'.py', '.md'} or path.name == Path(__file__).name or '_vendor' in path.parts:
                continue
            text = path.read_text()
            prepared = remove_export(text) if path == root / 'packages/work/src/tlwork/api.py' else text
            new, problems = rewrite(prepared) if path.suffix == '.py' else (prepared, [])
            errors.extend(f'{path}: {p}' for p in problems)
            new = references(new)
            if new != text:
                outputs[path] = new
    return outputs, moves, errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    root = parser.parse_args().root.resolve()
    outputs, moves, errors = plan(root)
    print(f'preflight: {len(moves)} moves, {len(outputs)} rewrites, {len(errors)} unsupported forms')
    if errors:
        raise SystemExit('No files written:\n' + '\n'.join(errors))
    for path, text in outputs.items():
        path.write_text(text)
    for source, target in moves.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)


if __name__ == '__main__':
    main()
