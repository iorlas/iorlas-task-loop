"""Complete pinned documentation, kept separately from canonical declarations."""

import ast
from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

from taskloop.shelf_digest.identities import Identities, PackageIdentity
from taskloop.shelf_digest.models import Signature, SignatureKind
from taskloop.shelf_digest.source import ReadFailure, Source, SourceOpener


class DocumentationKind(StrEnum):
    DOCUMENT = "document"
    MODULE = "module"
    DECLARATION = "declaration"


@dataclass(frozen=True)
class Documentation:
    identity: PackageIdentity
    commit: str
    path: str
    start_line: int
    end_line: int
    kind: DocumentationKind
    text: str
    public_name: str | None = None
    defining_name: str | None = None


@dataclass(frozen=True)
class DocumentationFailure:
    explanation: str


type DocumentedNode = ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef


def _docstring(
    identity: PackageIdentity, path: str, node: DocumentedNode, kind: DocumentationKind,
    public_name: str, defining_name: str,
) -> tuple[Documentation, ...]:
    if not node.body:
        return ()
    first = node.body[0]
    if not (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str)):
        return ()
    return (Documentation(identity, identity.commit, path, first.lineno, first.end_lineno or first.lineno,
                          kind, first.value.value, public_name, defining_name),)


def _declaration_docs(
    identity: PackageIdentity, path: str, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
    public_name: str, defining_name: str,
) -> tuple[Documentation, ...]:
    docs = list(_docstring(identity, path, node, DocumentationKind.DECLARATION, public_name, defining_name))
    if isinstance(node, ast.ClassDef):
        for member in node.body:
            if isinstance(member, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and (
                not member.name.startswith("_") or (member.name.startswith("__") and member.name.endswith("__"))
            ):
                docs.extend(_declaration_docs(identity, path, member, f"{public_name}.{member.name}",
                                              f"{defining_name}.{member.name}"))
    return tuple(docs)


def document_path(path: str, prefix: str) -> bool:
    relative = PurePosixPath(path.removeprefix(prefix))
    return (relative.name.lower().split(".")[0] == "readme" or relative.suffix.lower() in {".md", ".rst"}
            or ("docs" in relative.parts[:-1] and relative.suffix.lower() in {"", ".txt", ".text"}))


def _module_docs(
    identity: PackageIdentity, path: str, tree: ast.Module, signatures: tuple[Signature, ...],
) -> tuple[Documentation, ...]:
    relative = path.removeprefix(f"{identity.subdirectory}/src/").removesuffix(".py")
    module_name = relative.removesuffix("/__init__").replace("/", ".")
    docs = list(_docstring(identity, path, tree, DocumentationKind.MODULE, module_name, module_name))
    for signature in signatures:
        if signature.path != path:
            continue
        if signature.kind == SignatureKind.MODULE:
            docs.extend(_docstring(identity, path, tree, DocumentationKind.MODULE,
                                   signature.public_name, signature.defining_name))
        else:
            name = signature.defining_name.rsplit(".", 1)[-1]
            for node in tree.body:
                if (isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
                        and signature.start_line <= node.lineno <= signature.end_line):
                    docs.extend(_declaration_docs(identity, path, node, signature.public_name, signature.defining_name))
    return tuple(docs)


def _package_docs(
    identity: PackageIdentity, source: Source, signatures: tuple[Signature, ...],
) -> tuple[Documentation, ...] | DocumentationFailure | ReadFailure:
    entries = source.entries()
    if isinstance(entries, ReadFailure):
        return entries
    docs: list[Documentation] = []
    prefix = f"{identity.subdirectory}/"
    for entry in entries:
        path = entry.path
        if not path.startswith(prefix):
            continue
        document = document_path(path, prefix)
        module = path.startswith(f"{prefix}src/") and path.endswith(".py")
        if not document and not module:
            continue
        data = source.read(path)
        if isinstance(data, ReadFailure):
            return data
        try:
            if document:
                text = data.decode("utf-8")
                end_line = max(1, text.count("\n") + int(not text.endswith("\n")))
                docs.append(Documentation(identity, identity.commit, path, 1, end_line,
                                          DocumentationKind.DOCUMENT, text))
            if module:
                docs.extend(_module_docs(identity, path, ast.parse(data, filename=path, type_comments=True), signatures))
        except (SyntaxError, UnicodeError, ValueError) as error:
            return DocumentationFailure(f"{identity.name}: {path} at {identity.commit}: Cannot read documentation: {error}")
    return tuple(docs)


def documentation_order(item: Documentation) -> tuple[str, str, int, int, str, str, str]:
    return (item.identity.name, item.path, item.start_line, item.end_line,
            item.public_name or "", item.defining_name or "", item.kind.value)


def extract_documentation(
    identities: Identities, signatures: tuple[Signature, ...], opener: SourceOpener,
) -> tuple[Documentation, ...] | DocumentationFailure | ReadFailure:
    """Retain full text and exact source lines; listed unreadable files fail the whole collection."""
    docs: set[Documentation] = set()
    for identity in sorted(identities.packages, key=lambda item: item.name):
        source = opener(identity.commit)
        if isinstance(source, ReadFailure):
            return source
        package = _package_docs(identity, source, tuple(item for item in signatures if item.identity == identity))
        if isinstance(package, (DocumentationFailure, ReadFailure)):
            return package
        docs.update(package)
    return tuple(sorted(docs, key=documentation_order))
