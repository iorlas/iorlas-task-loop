"""Move slot configuration rules and rewrite importers; rerunnable with --root DIR.

Not handled (fix by hand after a run): `mock.patch.object(mod.wslots, "<moved>")` and `mod.wslots.<moved>` through a module
attribute; they become `mod.wslots_config` (tests/loop/real/test_loop.py, tests/run/test_stage_preflight.py and
tests/track/test_closeguard.py were the three).

Unsupported uses are reported before any writes; finish with the pinned ruff sorter.
"""
import argparse
import ast
import subprocess
import tomllib
from pathlib import Path

OLD = 'taskloop.app.wire.slots'
NEW = 'taskloop.app.slots.config'
MOVED = frozenset({'profile', 'profile_source', 'load_profile', 'cfg_source', 'load_cfg', 'profile_slots',
                   'slot_source', 'slot_dirs', 'slot_dir', 'slot_excludes', 'exclude_local', 'prio_of'})
WIRE = Path('src/taskloop/app/wire/slots.py')
CONFIG = Path('src/taskloop/app/slots/config.py')
HEADER = '''"""Slot profile selection, directory rules and priority defaults (node: slots)."""
import os
import sys
from pathlib import Path
from typing import Any

from tlkernel import config
from tlkernel.bead import Bead
from tlkernel.config import EngineConfig, RepoProfile, SlotsConfig
from tlkernel.gitport import Git
from tlkernel.paths import TASK_EXCLUDE
from tlkernel.slots import NotARepo, SlotGitError
from tlkernel.slottable import WORKTREE, SlotSource

from taskloop.adapters import profile_at
from taskloop.adapters.ident import hostname
from taskloop.app.slots.env import DEFAULT_PRIO


'''


def replace(text, edits):
    for start, end, value in sorted(edits, reverse=True):
        text = text[:start] + value + text[end:]
    return text


def rewrite(text):
    tree = ast.parse(text)
    lines = text.splitlines(keepends=True)
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line))
    edits, reports, aliases = [], [], {}

    def edit(node, value):
        if isinstance(node, ast.ImportFrom) and '# noqa: E402' in lines[node.end_lineno - 1]:
            value = value.replace('\n', '  # noqa: E402\n')
        edits.append((offsets[node.lineno - 1] + node.col_offset,
                      offsets[node.end_lineno - 1] + node.end_col_offset, value))

    imports(tree, edit, aliases, reports)
    module_imports(tree, edit, aliases, reports)
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and node.value.startswith(OLD + '.') and node.value[len(OLD) + 1:] in MOVED):
            edit(node, repr(NEW + node.value[len(OLD):]))
    return replace(text, edits), reports


def imports(tree, edit, aliases, reports):
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == 'taskloop.app.wire':
            for a in node.names:
                if a.name == 'slots':
                    aliases[a.asname or a.name] = (node, a)
        if isinstance(node, ast.Import) and any(a.name == OLD for a in node.names):
            reports.append(f'{node.lineno}: unsupported import {ast.unparse(node)}')
        if isinstance(node, ast.ImportFrom) and node.module == OLD:
            if any(a.name == '*' for a in node.names):
                reports.append(f'{node.lineno}: star import')
                continue
            groups = [(OLD, [a for a in node.names if a.name not in MOVED]),
                      (NEW, [a for a in node.names if a.name in MOVED])]
            indent = ' ' * node.col_offset
            edit(node, ('\n' + indent).join('from ' + mod + ' import ' + ', '.join(ast.unparse(a) for a in names)
                                         for mod, names in groups if names))


def module_uses(tree, parents, alias, reports):
    uses = [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == alias]
    moved: list[ast.Name | ast.Attribute] = []
    stays: list[ast.Name | ast.Attribute] = []
    for n in uses:
        parent = parents.get(n)
        if (isinstance(parent, ast.Call) and isinstance(parent.func, ast.Attribute) and parent.func.attr == 'object'
                and len(parent.args) > 1 and parent.args[0] is n and isinstance(parent.args[1], ast.Constant)
                and isinstance(parent.args[1].value, str)):
            if parent.args[1].value in MOVED:
                moved.append(n)
            else:
                stays.append(n)
        elif not isinstance(parent, ast.Attribute) or parent.value is not n:
            reports.append(f'{n.lineno}: unsupported bare module {alias}')
        elif parent.attr in MOVED:
            moved.append(parent)
        else:
            stays.append(parent)
    return moved, stays


def module_imports(tree, edit, aliases, reports):
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    for alias, (imp, imported) in aliases.items():
        moved, stays = module_uses(tree, parents, alias, reports)
        if not moved:
            continue
        config_alias = alias + '_config'
        if any(isinstance(n, ast.Name) and n.id == config_alias for n in ast.walk(tree)):
            reports.append(f'{imp.lineno}: alias collision {config_alias}')
        for attr in moved:
            edit(attr if isinstance(attr, ast.Name) else attr.value, config_alias)
        names = [a for a in imp.names if a is not imported or stays]
        replacement = ('from taskloop.app.wire import ' + ', '.join(ast.unparse(a) for a in names) + '\n' + ' ' * imp.col_offset
                       if names else '')
        replacement += f'from taskloop.app.slots import config as {config_alias}'
        edit(imp, replacement)


def move_storm(root, outputs):
    """Keep launch.loop below the fan-out cap after adding its config dependency."""
    loop = 'src/taskloop/app/launch/loop.py'
    ops = 'src/taskloop/app/launch/loop_ops.py'
    if not (root / loop).exists() or not (root / ops).exists():
        return
    text = outputs.get(loop, (root / loop).read_text())
    node = next((n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == 'storm'), None)
    if node is None:
        return
    lines = text.splitlines(keepends=True)
    block = ''.join(lines[node.lineno - 1:node.end_lineno])
    del lines[node.lineno - 1:(node.end_lineno or node.lineno) + 2]
    outputs[loop] = ''.join(lines).replace('storm=lambda: storm(', 'storm=lambda: ops.storm(')
    additions = ("from taskloop.adapters import storm as storm_file\n"
                 "from taskloop.adapters.repourl import repo_url\n"
                 "from taskloop.app.loop.env import Storm\n"
                 "from taskloop.domain import outcome as oc\n")
    original = outputs.get(ops, (root / ops).read_text())
    outputs[ops] = original.replace('import contextlib', additions + '\nimport contextlib', 1) + '\n\n' + block


def migrate(root, names):
    outputs, reports = {}, []
    for name in names:
        path = root / name
        if (not name.endswith('.py') or name == 'dev/split_wire_slots.py' or '_vendor/' in name or not path.is_file()):
            continue
        text = path.read_text()
        outputs[name], problems = rewrite(text)
        reports.extend(f'{name}:{p}' for p in problems)
    if reports:
        print('Unsupported uses (no files written):\n' + '\n'.join(reports))
        return 1
    source = (root / WIRE).read_text()
    functions = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name in MOVED]
    if functions:
        lines = source.splitlines(keepends=True)
        blocks = [''.join(lines[n.lineno - 1:n.end_lineno]) for n in functions]
        for n in reversed(functions):
            del lines[n.lineno - 1:(n.end_lineno or n.lineno) + 2]
        remaining = ''.join(lines)
        used = {n.id for n in ast.walk(ast.parse(remaining)) if isinstance(n, ast.Name)} & MOVED
        outputs[str(WIRE)] = remaining + '\n' if not remaining.endswith('\n') else remaining
        # Only names actually consumed by the composition root are imported there.
        outputs[str(WIRE)] = outputs[str(WIRE)].replace('import contextlib',
            'from taskloop.app.slots.config import ' + ', '.join(sorted(used)) + '\n\nimport contextlib', 1)
        outputs[str(CONFIG)] = HEADER + '\n\n\n'.join(blocks) + '\n'
    move_storm(root, outputs)
    changed = []
    for name, text in outputs.items():
        path = root / name
        if not path.exists() or path.read_text() != text:
            path.write_text(text)
            changed.append(name)
    print(f'files rewritten: {len(changed)}; functions moved: {len(functions)}')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    root = parser.parse_args().root.resolve()
    tracked = subprocess.run(['git', 'ls-files', '-z'], cwd=root, capture_output=True, text=True, check=True)
    status = migrate(root, tracked.stdout.rstrip('\0').split('\0'))
    if status:
        return status
    pin = tomllib.loads((root / 'mise.toml').read_text())['tools']['ruff']
    targets = [name for name in tracked.stdout.rstrip('\0').split('\0')
               if name.endswith('.py') and '_vendor/' not in name
               and (OLD in (root / name).read_text() or NEW in (root / name).read_text()
                    or 'from taskloop.app.slots import config' in (root / name).read_text())]
    command = ['uv', 'tool', 'run', f'ruff@{pin}', 'check', '--fix', '-q']
    cleanup = subprocess.run([*command, '--select', 'F401', str(WIRE),
                              'src/taskloop/app/launch/loop.py', 'src/taskloop/app/launch/loop_ops.py'], cwd=root, check=False)
    if cleanup.returncode:
        return cleanup.returncode
    return subprocess.run([*command, '--select', 'I', *targets, str(CONFIG), 'dev/split_wire_slots.py'],
                          cwd=root, check=False).returncode


if __name__ == '__main__':
    raise SystemExit(main())
