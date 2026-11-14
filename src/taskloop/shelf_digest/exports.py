"""Resolve package-local bindings in committed Python source without importing it."""

import ast
from dataclasses import dataclass, field
from typing import Never

from taskloop.shelf_digest.declarations import Declaration, declared_names, expression_name
from taskloop.shelf_digest.models import ExtractionError, SignatureFailure, SignatureFailureReason
from taskloop.shelf_digest.source import CommittedSource, ReadFailure


@dataclass
class Module:
    name: str
    path: str
    package: bool
    end_line: int
    declarations: dict[str, tuple[Declaration, ...]] = field(default_factory=dict)
    links: dict[str, str] = field(default_factory=dict)
    stars: list[tuple[str, int]] = field(default_factory=list)
    orders: dict[str, int] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    exports: tuple[str, ...] | None = None


@dataclass(frozen=True)
class Binding:
    module: Module
    name: str | None


def _strings(node: ast.expr | None, values: dict[str, tuple[str, ...]]) -> tuple[str, ...] | None:
    result: tuple[str, ...] | None = None
    if isinstance(node, (ast.List, ast.Tuple)) and all(
        isinstance(item, ast.Constant) and isinstance(item.value, str) for item in node.elts
    ):
        result = tuple(item.value for item in node.elts if isinstance(item, ast.Constant) and isinstance(item.value, str))
    elif isinstance(node, ast.Name):
        result = values.get(node.id)
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _strings(node.left, values), _strings(node.right, values)
        if left is not None and right is not None:
            result = left + right
    return result


def _import_target(module: Module, node: ast.ImportFrom) -> str:
    parts: list[str] = module.name.split(".") if module.package else module.name.split(".")[:-1]
    if node.level:
        if node.level > len(parts):
            return ""
        parts = parts[:len(parts) - node.level + 1]
    else:
        parts = []
    return ".".join([*parts, *([node.module] if node.module else [])])


class PackageExports:
    def __init__(self, source: CommittedSource, subdirectory: str) -> None:
        self.source = source
        self.modules: dict[str, Module] = {}
        entries = source.entries()
        if isinstance(entries, ReadFailure):
            raise ExtractionError(entries)
        prefix = f"{subdirectory}/src/"
        paths = [entry.path for entry in entries if entry.path.startswith(prefix) and entry.path.endswith(".py")]
        for path in paths:
            parts = path.removeprefix(prefix).removesuffix(".py").split("/")
            package = parts[-1] == "__init__"
            name = ".".join(parts[:-1] if package else parts)
            if not name or any(not part.isidentifier() for part in name.split(".")):
                self.fail(SignatureFailureReason.INVALID_SOURCE, path, "Invalid Python module path")
            self.modules[name] = self._parse(name, path, package)
        if not self.modules:
            self.fail(SignatureFailureReason.NO_MODULE, prefix, "No Python modules in the pinned package")
        self.names = self._export_names()
        self._link_aliases()

    def fail(self, reason: SignatureFailureReason, path: str, detail: str) -> Never:
        raise ExtractionError(SignatureFailure(reason, f"{path} at {self.source.commit}: {detail}"))

    def _parse(self, name: str, path: str, package: bool) -> Module:
        data = self.source.read(path)
        if isinstance(data, ReadFailure):
            raise ExtractionError(data)
        try:
            tree = ast.parse(data, filename=path, type_comments=True)
        except (SyntaxError, UnicodeError, ValueError) as error:
            self.fail(SignatureFailureReason.INVALID_SOURCE, path, str(error))
        module = Module(name, path, package, max((node.end_lineno or node.lineno for node in tree.body), default=1))
        values: dict[str, tuple[str, ...]] = {}
        for node in tree.body:
            self._statement(module, node, values, module.aliases)
        return module

    def _link_aliases(self) -> None:
        for module in self.modules.values():
            for alias, target in module.aliases.items():
                first, _, rest = target.partition(".")
                if first in module.links:
                    module.links[alias] = module.links[first] + (f".{rest}" if rest else "")
                elif first in module.declarations or any(first in self.names.get(star, ()) for star, _ in module.stars):
                    module.links[alias] = f"{module.name}.{target}"

    def _statement(self, module: Module, node: ast.stmt, values: dict[str, tuple[str, ...]], aliases: dict[str, str]) -> None:
        if isinstance(node, (ast.ImportFrom, ast.Import)):
            self._imports(module, node)
            for name, order in module.orders.items():
                if order == node.lineno:
                    aliases.pop(name, None)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign, ast.TypeAlias)):
            self._declare(module, node, values, aliases)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and node.target.id == "__all__":
            extra = _strings(node.value, values)
            if module.exports is None or extra is None or not isinstance(node.op, ast.Add):
                self.fail(SignatureFailureReason.UNSUPPORTED_EXPORT, module.path, "Unsupported __all__ update")
            module.exports += extra
        elif any(isinstance(child, ast.Name) and child.id == "__all__" for child in ast.walk(node)):
            self.fail(SignatureFailureReason.UNSUPPORTED_EXPORT, module.path, "Dynamic __all__ declaration or mutation")
        if module.exports is not None:
            values["__all__"] = module.exports

    def _imports(self, module: Module, node: ast.ImportFrom | ast.Import) -> None:
        if isinstance(node, ast.ImportFrom):
            target = _import_target(module, node)
            for item in node.names:
                if item.name == "*":
                    module.stars.append((target, node.lineno))
                else:
                    module.links[item.asname or item.name] = f"{target}.{item.name}"
                    module.orders[item.asname or item.name] = node.lineno
        else:
            for item in node.names:
                module.links[item.asname or item.name.split(".")[0]] = item.name if item.asname else item.name.split(".")[0]
                module.orders[item.asname or item.name.split(".")[0]] = node.lineno

    def _declare(self, module: Module, node: Declaration, values: dict[str, tuple[str, ...]], aliases: dict[str, str]) -> None:
        for name in declared_names(node):
            if name == "__all__":
                exported = _strings(node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None, values)
                if exported is None:
                    self.fail(SignatureFailureReason.UNSUPPORTED_EXPORT, module.path, "__all__ is not a static string sequence")
                module.exports = exported
            else:
                self._save_declaration(module, name, node, aliases)
                sequence = _strings(node.value, values) if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
                values.pop(name, None)
                if sequence is not None:
                    values[name] = sequence

    def _save_declaration(self, module: Module, name: str, node: Declaration, aliases: dict[str, str]) -> None:
        previous = module.declarations.get(name, ())
        functions = isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and all(
            isinstance(old, (ast.FunctionDef, ast.AsyncFunctionDef)) for old in previous
        )
        module.declarations[name] = (*previous, node) if functions else (node,)
        module.orders[name] = node.lineno
        module.links.pop(name, None)
        aliases.pop(name, None)
        if isinstance(node, ast.Assign):
            target = expression_name(node.value)
            if target is not None:
                aliases[name] = target

    def _local(self, target: str) -> bool:
        return target.partition(".")[0] in {name.partition(".")[0] for name in self.modules}

    def _export_names(self) -> dict[str, set[str]]:
        for module in self.modules.values():
            for target, _ in module.stars:
                if self._local(target) and target not in self.modules:
                    self.fail(SignatureFailureReason.UNRESOLVED_EXPORT, module.path, f"Missing star re-export module {target}")
        names = {
            module.name: set(module.exports) if module.exports is not None else {
                name for name in {*module.declarations, *(name for name, target in module.links.items() if self._local(target))}
                if not name.startswith("_")
            }
            for module in self.modules.values()
        }
        changed = True
        while changed:
            changed = False
            for module in self.modules.values():
                if module.exports is None:
                    before = len(names[module.name])
                    for target, _ in module.stars:
                        names[module.name].update(names.get(target, ()))
                    changed = changed or before != len(names[module.name])
        return names

    def resolve(self, module: str, name: str, trail: frozenset[tuple[str, str]] = frozenset()) -> Binding | None:
        key = (module, name)
        if key in trail:
            return None
        trail = trail | {key}
        current = self.modules[module]
        result: Binding | None = None
        for target, order in reversed(current.stars):
            if order >= current.orders.get(name, 0) and target in self.names and name in self.names[target]:
                result = self.resolve(target, name, trail)
                if result is not None:
                    return result
        if name in current.links:
            result = self._target(current.links[name], trail)
        elif name in current.declarations:
            result = Binding(current, name)
        elif f"{module}.{name}" in self.modules:
            result = Binding(self.modules[f"{module}.{name}"], None)
        return result

    def _target(self, target: str, trail: frozenset[tuple[str, str]]) -> Binding | None:
        parts = target.split(".")
        for index in range(len(parts) - 1, 0, -1):
            module = ".".join(parts[:index])
            if module in self.modules:
                binding: Binding | None = Binding(self.modules[module], None)
                for name in parts[index:]:
                    if binding is None or binding.name is not None:
                        return None
                    binding = self.resolve(binding.module.name, name, trail)
                if binding is not None:
                    return binding
                break
        return Binding(self.modules[target], None) if target in self.modules else None
