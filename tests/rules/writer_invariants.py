"""AST ownership of typed stores and the two deliberately raw JSON publications."""
import ast
from typing import Final

from importgraph import bindings, qualified

# State authority, rather than a budget of write sites. Reads are unrestricted.
WRITERS: Final = {
    'PinStore': {'taskloop.app.release.pins'},
    'HostResourcesStore': {'taskloop.app.wire.setup_apply'},
    'StatusStore': {'taskloop.app.wire.lanes'},
    'StatusTriedStore': {'taskloop.app.wire.lanes'},
    'ReposStore': {'taskloop.app.track.trail', 'taskloop.contracts.stores'},
    'ReleaseResultStore': {'taskloop.app.release.flow'},
    'ReflectStateStore': {'taskloop.app.report.reflect'},
    'ParkStore': {'taskloop.app.asks.parks', 'taskloop.app.loop.take', 'taskloop.app.run.stages', 'taskloop.contracts.parks'},
    'TraceStore': {'taskloop.app.run.records', 'taskloop.contracts.finish_projection'},
    'BadVersionStore': {'taskloop.app.loop.versions'},
    'HandoffMirrorStore': {'taskloop.app.write.handoff'},
    'ReexecNoteStore': {'taskloop.app.release.reexec', 'taskloop.app.run.reload'},
    'NetPauseStore': {'taskloop.app.release.reexec', 'taskloop.app.run.reload'},
    'RunCountersStore': {'taskloop.app.run.reload'},
    'EngineLockStore': {'taskloop.app.slots.engine_lock'},
    'RunManifestStore': {'taskloop.contracts.runrows'},
}
PATH_STORES: Final = {
    'pin': 'PinStore', 'status': 'StatusStore', 'status_tried': 'StatusTriedStore', 'repos': 'ReposStore',
    'release_result': 'ReleaseResultStore', 'reflect_state': 'ReflectStateStore',
    'park': 'ParkStore', 'traces': 'TraceStore',
    'bad_versions': 'BadVersionStore',
    'handoff': 'HandoffMirrorStore', 'reexec_note': 'ReexecNoteStore',
    'net_pause': 'NetPauseStore', 'pause': 'RunCountersStore', 'reexec': 'RunCountersStore',
}
MUTATIONS: Final = {'write', 'put', 'append', 'delete', 'add', 'update', 'replace', 'clear', 'drop'}


def json_store_identity(node, names):
    path = node.args[0]
    if isinstance(path, ast.Call) and isinstance(path.func, ast.Attribute) and path.func.attr in PATH_STORES:
        return PATH_STORES[path.func.attr]
    if len(node.args) > 1:
        return qualified(node.args[1], names).rsplit('.', 1)[-1] + 'Store'
    return 'JsonStore'


def store_identity(node, names, factories):
    """Follow constructors, aliases, factories and DocMap.of without executing code."""
    if isinstance(node, ast.Call):
        name = qualified(node.func, names)
        short = name.rsplit('.', 1)[-1]
        if short.endswith('Store') and short not in {'JsonStore', 'JsonlStore'} and name.startswith('taskloop.contracts.'):
            return short
        if short in {'JsonStore', 'JsonlStore'} and node.args:
            return json_store_identity(node, names)
        if name in factories:
            return factories[name]
        if isinstance(node.func, ast.Attribute) and node.func.attr == 'of':
            return store_identity(node.func.value, names, factories)
    identity = names.get(ast.unparse(node), '') if node is not None else ''
    return identity if identity.endswith('Store') and '.' not in identity else ''


def raw_json_allowed(module, receiver):
    """Only these wire copies have hand-written JSON destinations; state uses stores."""
    if not isinstance(receiver, ast.BinOp) or not isinstance(receiver.op, ast.Div):
        return False
    left, right = receiver.left, receiver.right
    if not isinstance(left, ast.Attribute) or left.attr != 'run_dir':
        return False
    if module == 'taskloop.app.run.parts_plan':
        return isinstance(right, ast.Name) and right.id == 'PLAN_FILE'
    if module == 'taskloop.app.run.worker_call' and isinstance(right, ast.JoinedStr):
        return (len(right.values) == 4 and isinstance(right.values[0], ast.FormattedValue)
                and isinstance(right.values[1], ast.Constant) and right.values[1].value == '-'
                and isinstance(right.values[2], ast.FormattedValue)
                and isinstance(right.values[3], ast.Constant) and right.values[3].value == '.json')
    return False


class Writes(ast.NodeVisitor):
    def __init__(self, module, names, factories):
        self.module, self.names, self.factories = module, names.copy(), factories
        self.problems = []
        self.json_values = set()

    def visit_ClassDef(self, node):
        child = Writes(self.module, self.names, self.factories)
        for method in node.body:
            if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and method.name == '__init__':
                for statement in method.body:
                    child.visit(statement)
        for statement in node.body:
            if getattr(statement, 'name', '') != '__init__':
                child.visit(statement)
        self.problems.extend(child.problems)

    def visit_FunctionDef(self, node):
        child = Writes(self.module, self.names, self.factories)
        child.json_values = self.json_values.copy()
        for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            child.names.pop(arg.arg, None)
        for statement in node.body:
            child.visit(statement)
        self.problems.extend(child.problems)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Assign(self, node):
        identity = store_identity(node.value, self.names, self.factories)
        if isinstance(node.value, ast.Attribute) and node.value.attr in MUTATIONS:
            self.check_store(node.value.value, node.lineno)
        for target in node.targets:
            self.names[ast.unparse(target)] = identity or qualified(node.value, self.names)
            if self.is_json(node.value):
                self.json_values.add(ast.unparse(target))
            else:
                self.json_values.discard(ast.unparse(target))
        self.generic_visit(node)

    def visit_AnnAssign(self, node):
        if node.value is not None:
            self.visit_Assign(ast.copy_location(ast.Assign(targets=[node.target], value=node.value), node))

    def check_store(self, receiver, line):
        store = store_identity(receiver, self.names, self.factories)
        if store and self.module not in WRITERS.get(store, ()):
            self.problems.append(f'{self.module}:{line}: {store} writes belong to {sorted(WRITERS.get(store, ())) or "unregistered owner"}')

    def is_json(self, node):
        return any((isinstance(n, ast.Call) and qualified(n.func, self.names) in {'json.dumps', 'msgspec.json.encode'})
                   or (isinstance(n, (ast.Name, ast.Attribute)) and ast.unparse(n) in self.json_values) for n in ast.walk(node))

    def visit_Call(self, node):
        fn = node.func
        if isinstance(fn, ast.Attribute) and fn.attr in MUTATIONS:
            self.check_store(fn.value, node.lineno)
        if self.module.startswith('taskloop.app.'):
            name = qualified(fn, self.names)
            if name == 'os.replace':
                self.problems.append(f'{self.module}:{node.lineno}: state replacement belongs to the atomic store')
            if isinstance(fn, ast.Attribute) and fn.attr == 'events' and self.module != 'taskloop.app.track.trail':
                self.problems.append(f'{self.module}:{node.lineno}: events belong to track.trail')
            if isinstance(fn, ast.Attribute) and fn.attr == 'write_text':
                json_call = any(self.is_json(arg) for arg in node.args)
                if json_call and not raw_json_allowed(self.module, fn.value):
                    self.problems.append(f'{self.module}:{node.lineno}: JSON state belongs to its store writer')
        self.generic_visit(node)


def local_factories(module, tree, external):
    names = bindings(module, tree)
    factories = dict(external)
    functions = [node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for _ in range(len(functions) + 1):
        before = factories.copy()
        for function in functions:
            local = names.copy()
            for node in ast.walk(function):
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        local[ast.unparse(target)] = store_identity(node.value, local, factories)
                elif isinstance(node, ast.Return) and node.value is not None:
                    identity = store_identity(node.value, local, factories)
                    if identity:
                        factories[function.name] = identity
                        factories['self.' + function.name] = identity
        if factories == before:
            break
    return factories


def writer_problems(module, tree, external=()):
    names = bindings(module, tree)
    factories = local_factories(module, tree, external)
    visitor = Writes(module, names, factories)
    visitor.visit(tree)
    return visitor.problems


def writer_tree_problems(trees):
    """Resolve store factories across module imports before checking mutation capabilities."""
    external = {}
    for _ in range(len(trees) + 1):
        before = external.copy()
        for module, tree in trees.items():
            found = local_factories(module, tree, external)
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in found:
                    external[module + '.' + node.name] = found[node.name]
        if external == before:
            break
    return [problem for module, tree in trees.items() for problem in writer_problems(module, tree, external)]
