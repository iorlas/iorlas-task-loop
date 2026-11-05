"""Import SCCs and fan-out, measured statically over the owned Python tree. Size is the per-file caps of gate_rules.py; no total is kept."""
import ast

from rules.enumtotal import bindings, qualified
from rules.gate_rules import ROOT, parsed, py_files


def production_trees(root=ROOT):
    trees = {}
    for path in py_files(root, ("src", "skills", "dev")):
        parts = path.relative_to(root).with_suffix("").parts
        if parts[0] == "src":
            parts = parts[1:]
        if parts[-1] == "__init__":
            parts = parts[:-1]
        trees[".".join(parts)] = parsed(path)[1]
    return trees


def graph_of(trees):
    """All explicit imports, including lazy/TYPE_CHECKING imports and relative package imports."""
    packages = {name for name in trees if any(other.startswith(name + '.') for other in trees)}
    graph = {module: set() for module in trees}
    for module, tree in trees.items():
        names = bindings(module, tree, packages)
        for node in ast.walk(tree):
            targets = import_targets(module, node, names, packages)
            for target in targets:
                # `from module import symbol` depends on module; `from package import module` on both.
                parts = target.split('.')
                for end in range(1, len(parts) + 1):
                    name = '.'.join(parts[:end])
                    if name in trees and (name != module or target == module):
                        graph[module].add(name)
    return graph


def import_targets(module, node, names, packages):
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        return bindings(module, ast.Module(body=[node], type_ignores=[]), packages).values()
    if (isinstance(node, ast.Call) and qualified(node.func, names) in {'importlib.import_module', '__import__'}
            and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
        return [node.args[0].value]
    return ()


def cyclic_components(graph):
    """Tarjan SCCs; deterministic member lists, including explicit self-imports."""
    indexes, low, stack, active, components = {}, {}, [], set(), []

    def visit(node):
        indexes[node] = low[node] = len(indexes)
        stack.append(node)
        active.add(node)
        for target in sorted(graph[node]):
            if target not in indexes:
                visit(target)
                low[node] = min(low[node], low[target])
            elif target in active:
                low[node] = min(low[node], indexes[target])
        if low[node] == indexes[node]:
            component = []
            while True:
                target = stack.pop()
                active.remove(target)
                component.append(target)
                if target == node:
                    break
            if len(component) > 1 or node in graph[node]:
                components.append(tuple(sorted(component)))

    for node in sorted(graph):
        if node not in indexes:
            visit(node)
    return sorted(components)


def growth_problems(actual, recorded):
    problems = []
    for metric, value in actual.items():
        limit = recorded[metric]
        if value > limit:
            problems.append(f'{metric} grew: {value} > {limit}; the count may only shrink')
        elif value < limit:
            problems.append(f'{metric} shrank: lower rules_ratchet.json from {limit} to {value}')
    return problems


def metrics(root=ROOT):
    graph = graph_of(production_trees(root))
    return {
        'scc': len(cyclic_components(graph)),
        'fanout': max(map(len, graph.values()), default=0),
    }
