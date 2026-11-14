"""Canonical declarations without executable bodies or docstrings."""

import ast
from copy import deepcopy

from taskloop.shelf_digest.models import SignatureKind

type Declaration = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Assign | ast.AnnAssign | ast.TypeAlias


def declared_names(node: ast.stmt) -> tuple[str, ...]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return (node.name,)
    if isinstance(node, ast.TypeAlias):
        return (node.name.id,)
    targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
    return tuple(name for target in targets for name in _target_names(target))


def _target_names(target: ast.expr) -> tuple[str, ...]:
    if isinstance(target, ast.Name):
        return (target.id,)
    if isinstance(target, (ast.Tuple, ast.List)):
        return tuple(name for item in target.elts for name in _target_names(item))
    if isinstance(target, ast.Starred):
        return _target_names(target.value)
    return ()


def declaration_kind(node: Declaration) -> SignatureKind:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return SignatureKind.FUNCTION
    if isinstance(node, ast.ClassDef):
        return SignatureKind.CLASS
    if isinstance(node, ast.TypeAlias) or (
        isinstance(node, ast.AnnAssign) and ast.unparse(node.annotation).split(".")[-1] == "TypeAlias"
    ):
        return SignatureKind.TYPE_ALIAS
    return SignatureKind.CONSTANT


def _public_member(name: str) -> bool:
    return not name.startswith("_") or (name.startswith("__") and name.endswith("__"))


def _skeleton(node: Declaration) -> Declaration:
    result = deepcopy(node)
    if isinstance(result, (ast.FunctionDef, ast.AsyncFunctionDef)):
        result.body = [ast.Expr(value=ast.Constant(value=Ellipsis))]
    elif isinstance(result, ast.ClassDef):
        result.body = [
            _skeleton(member) for member in result.body
            if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign, ast.TypeAlias))
            and any(_public_member(name) for name in declared_names(member))
        ] or [ast.Expr(value=ast.Constant(value=Ellipsis))]
    return result


def canonical_declaration(nodes: tuple[Declaration, ...], name: str) -> str:
    """Keep overloads, decorators, type parameters, fields and defaults in source order."""
    declarations: list[str] = []
    for node in nodes:
        skeleton = _skeleton(node)
        if isinstance(skeleton, ast.Assign) and all(isinstance(target, ast.Name) for target in skeleton.targets):
            skeleton.targets = [ast.Name(id=name, ctx=ast.Store())]
        declarations.append(ast.unparse(ast.fix_missing_locations(skeleton)))
    return "\n".join(declarations)


def expression_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = expression_name(node.value)
        return f"{parent}.{node.attr}" if parent is not None else None
    return None
