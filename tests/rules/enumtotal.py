"""Static enum vocabulary and dict-literal coverage; never imports the code being checked."""
import ast

from importgraph import bindings, qualified


def resolved(name, imports):
    """Follow reexports without importing modules, and stop on cyclic aliases."""
    seen = set()
    while name not in seen:
        seen.add(name)
        prefix, _, tail = name.rpartition('.')
        if name in imports:
            name = imports[name]
        elif prefix:
            target = resolved(prefix, {k: v for k, v in imports.items() if k not in seen})
            if target == prefix:
                break
            name = target + '.' + tail
        else:
            break
    return name


def enum_members(trees, scopes, imports):
    enums = {}
    for module, tree in trees.items():
        names = scopes[module]
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = {'enum.Enum', 'enum.StrEnum', 'enum.IntEnum', 'enum.Flag', 'enum.IntFlag'}
            if not any(resolved(qualified(base, names), imports) in bases
                       for base in node.bases):
                continue
            enums[module + '.' + node.name] = class_members(node)
    return enums


def class_members(node):
    members, values, ignored = {}, {}, set()
    for statement in node.body:
        targets = statement.targets if isinstance(statement, ast.Assign) else (
            [statement.target] if isinstance(statement, ast.AnnAssign) and statement.value is not None else [])
        for target in targets:
            if not isinstance(target, ast.Name):
                continue
            name, value = target.id, statement.value
            if name == '_ignore_':
                raw = ast.literal_eval(value)
                ignored.update(raw.replace(',', ' ').split() if isinstance(raw, str) else raw)
            elif name not in ignored and not (name.startswith('_') and name.endswith('_')):
                canonical = members.get(value.id, name) if isinstance(value, ast.Name) else name
                if isinstance(value, ast.Constant):
                    canonical = values.setdefault(value.value, name)
                members[name] = canonical
    return members


def constant_dicts(node):
    """Uppercase bindings outside functions, including constants wrapped in MappingProxyType."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(child, (ast.Assign, ast.AnnAssign)):
            targets = child.targets if isinstance(child, ast.Assign) else [child.target]
            value = child.value
            if value is not None and any(isinstance(target, ast.Name) and target.id.isupper() for target in targets):
                yield from (n for n in ast.walk(value) if isinstance(n, ast.Dict))
        yield from constant_dicts(child)


def enum_problems(trees):
    packages = {name for name in trees if any(other.startswith(name + '.') for other in trees)}
    scopes = {module: bindings(module, tree, packages) for module, tree in trees.items()}
    imports = {module + '.' + name: target for module, names in scopes.items()
               for name, target in names.items() if module + '.' + name != target}
    enums = enum_members(trees, scopes, imports)
    out = []
    for module, tree in trees.items():
        names = scopes[module]
        for node in constant_dicts(tree):
            covered = {}
            for key in node.keys:
                name, _, member = resolved(qualified(key, names), imports).rpartition('.')
                if name in enums and member in enums[name]:
                    covered.setdefault(name, set()).add(enums[name][member])
            for name, members in covered.items():
                missing = set(enums[name].values()) - members
                if missing:
                    out.append(f'{module}:{node.lineno}: {name} table missing {", ".join(sorted(missing))}')
    return out
