"""The imports of one Python module, read from its syntax tree and never by importing it: the one reader of import statements that the
architecture ratchets (tests/rules/arch_ratchets.py) and the test selection (dev/affected.py) share. Standard library only."""
import ast


def bindings(module, tree, packages=(), nodes=None):
    """Resolve import aliases and local definitions to qualified names."""
    names = {}
    for node in ast.walk(tree) if nodes is None else nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                names[alias.asname or alias.name.split('.')[0]] = alias.name if alias.asname else alias.name.split('.')[0]
        elif isinstance(node, ast.ImportFrom):
            package = module.split('.') if module in packages else module.split('.')[:-1]
            prefix = '.'.join(package[:len(package) - node.level + 1]) if node.level else ''
            origin = '.'.join(filter(None, (prefix, node.module)))
            for alias in node.names:
                names[alias.asname or alias.name] = origin + '.' + alias.name
        elif isinstance(node, ast.ClassDef):
            names[node.name] = module + '.' + node.name
    return names


def qualified(node, names):
    if isinstance(node, ast.Name):
        return names.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        return qualified(node.value, names) + '.' + node.attr
    return ''


def import_targets(module, node, names, packages):
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return bindings(module, ast.Module(body=[node], type_ignores=[]), packages).values()
    if (isinstance(node, ast.Call) and qualified(node.func, names) in {'importlib.import_module', '__import__'}
            and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
        return [node.args[0].value]
    return ()


def targets_of(module, tree, packages=(), nodes=None):
    """Every dotted name `module` imports, lazy, TYPE_CHECKING and relative imports included (`packages`: the names that are packages)."""
    names = bindings(module, tree, packages, nodes)
    return [target for node in (ast.walk(tree) if nodes is None else nodes) for target in import_targets(module, node, names, packages)]
