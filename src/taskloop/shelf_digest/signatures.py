"""Extract a deterministic public API from the exact shelf pins."""

import ast

from taskloop.shelf_digest.declarations import canonical_declaration, declaration_kind
from taskloop.shelf_digest.exports import Binding, PackageExports
from taskloop.shelf_digest.identities import Identities, PackageIdentity
from taskloop.shelf_digest.models import ExtractionError, Signature, SignatureFailure, SignatureFailureReason, SignatureKind
from taskloop.shelf_digest.source import ReadFailure, SourceOpener


def _signature(identity: PackageIdentity, public_name: str, binding: Binding) -> Signature:
    module, name = binding.module, binding.name
    if name is None:
        return Signature(identity, identity.commit, public_name, module.name, module.path, 1, module.end_line,
                         SignatureKind.MODULE, f"module {module.name}")
    nodes = module.declarations[name]
    decorators = [decorator.lineno for node in nodes if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                  for decorator in node.decorator_list]
    start = min([*(node.lineno for node in nodes), *decorators])
    return Signature(identity, identity.commit, public_name, f"{module.name}.{name}", module.path,
                     start, max(node.end_lineno or node.lineno for node in nodes), declaration_kind(nodes[0]),
                     canonical_declaration(nodes, name))


def _public_module(name: str) -> bool:
    return all(not part.startswith("_") for part in name.split("."))


def _collect(identity: PackageIdentity, package: PackageExports) -> tuple[Signature, ...]:
    signatures: dict[str, Signature] = {}

    def visit(module: str, prefix: str, trail: frozenset[str]) -> None:
        if module in trail:
            return
        for name in sorted(package.names[module]):
            binding = package.resolve(module, name)
            if binding is None:
                package.fail(SignatureFailureReason.UNRESOLVED_EXPORT, package.modules[module].path,
                             f"Cannot statically resolve public export {module}.{name} (missing, external, or cyclic binding)")
                return
            public_name = f"{prefix}.{name}"
            signatures[public_name] = _signature(identity, public_name, binding)
            if binding.name is None:
                visit(binding.module.name, public_name, trail | {module})

    for module in sorted(package.modules):
        if _public_module(module):
            visit(module, module, frozenset())
    return tuple(signatures[name] for name in sorted(signatures))


def extract_signatures(identities: Identities, opener: SourceOpener) -> tuple[Signature, ...] | SignatureFailure | ReadFailure:
    """Return all public records in identity/name order, or an explained failure; never execute source."""
    results: list[Signature] = []
    try:
        for identity in sorted(identities.packages, key=lambda item: (item.name, item.commit, item.subdirectory)):
            source = opener(identity.commit)
            if isinstance(source, ReadFailure):
                raise ExtractionError(source)
            results.extend(_collect(identity, PackageExports(source, identity.subdirectory)))
    except ExtractionError as error:
        return error.failure
    return tuple(results)
