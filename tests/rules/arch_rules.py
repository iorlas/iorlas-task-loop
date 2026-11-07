"""Hard architecture rules over the owned Python tree, measured statically: no import cycle, and no module imports more than
MAX_FANOUT distinct project modules (lazy and TYPE_CHECKING imports count; the parent packages of an imported module do not,
`from a.b import c` is one module, not three). 40 is the cap the probe could meet by splitting modules by concern (the two
widest, app/launch/loop.py and skills/task-loop/tl.py, sit on it); past it a module does several jobs. Size is the per-file
caps of gate_rules.py. Nothing is stored."""

from importgraph import targets_of

from rules.gate_rules import ROOT, parsed, py_files

MAX_FANOUT = 40


def production_trees(root=ROOT):
    trees = {}
    for path in py_files(root, ("src", *(p.relative_to(root).as_posix() for p in sorted(root.glob("packages/*/src"))), "skills", "dev")):
        parts = path.relative_to(root).with_suffix("").parts
        if parts[0] == "src":
            parts = parts[1:]
        elif parts[0] == "packages" and parts[2:3] == ("src",):
            parts = parts[3:]
        if parts[-1] == "__init__":
            parts = parts[:-1]
        trees[".".join(parts)] = parsed(path)[1]
    return trees


def graph_of(trees):
    """All explicit imports, including lazy/TYPE_CHECKING imports and relative package imports."""
    packages = {name for name in trees if any(other.startswith(name + '.') for other in trees)}
    graph = {module: set() for module in trees}
    for module, tree in trees.items():
        for target in targets_of(module, tree, packages):
            # `from module import symbol` depends on module; `from package import module` on both.
            parts = target.split('.')
            for end in range(1, len(parts) + 1):
                name = '.'.join(parts[:end])
                if name in trees and (name != module or target == module):
                    graph[module].add(name)
    return graph


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


def imported_modules(targets):
    """The modules a module names in its imports: a package that is only the parent of another imported module is not counted."""
    return {name for name in targets if not any(other.startswith(name + '.') for other in targets)}


def fanout_problems(graph, cap=MAX_FANOUT):
    counted = {module: imported_modules(targets) for module, targets in graph.items()}
    return [f'{module} imports {len(targets)} project modules; the cap is {cap}: split it by concern'
            for module, targets in sorted(counted.items()) if len(targets) > cap]


def problems(root=ROOT):
    graph = graph_of(production_trees(root))
    cycles = [f'import cycle: {" -> ".join(component)}' for component in cyclic_components(graph)]
    return cycles + fanout_problems(graph)
