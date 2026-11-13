"""Which docs a change touches: the changed docs, the docs depending on changed repo files, and whatever references those."""

from dataclasses import dataclass
from pathlib import Path

from any_path_glob import Glob

from docscheck.docs import Doc, Link, walk_values
from docscheck.ontology import Kind
from docscheck.values import as_list


@dataclass(frozen=True)
class Scope:
    full: bool
    doc_ids: frozenset[str]


def repo_dependencies(doc: Doc, kinds: dict[str, Kind]) -> tuple[list[str], list[str]]:
    """(exact repo paths, globs) a doc's fields name."""
    paths: list[str] = []
    globs: list[str] = []
    for _, field, value in walk_values(kinds[doc.kind], kinds, doc.data):
        items = [value] if isinstance(value, str) else [v for v in as_list(value) if isinstance(v, str)]
        for item in items if field.type.base == "string" else []:
            if field.glob:
                globs.append(item)
            if field.path or field.symbol:
                paths.append(item.split("::")[0])
    return paths, globs


def reverse_closure(direct: set[str], links: list[Link], owner: dict[str, str]) -> set[str]:
    """`direct` plus the docs pointing at any of them (one hop: a reference is checked where it is written)."""
    result = set(direct)
    for link in links:
        if owner.get(link.target) in direct:
            result.add(link.doc)
    return result


def scope_of(changed: list[Path], docs: list[Doc], kinds: dict[str, Kind], links: list[Link], owner: dict[str, str],
             docs_root: Path, repo: Path | None, always_full: list[Path], check_sources: dict[str, str]) -> Scope:
    """`always_full`: folders whose change (the ontology, the checker's own source) re-checks everything."""
    if any(path.is_relative_to(folder) for path in changed for folder in always_full):
        return Scope(True, frozenset(doc.id for doc in docs))
    direct = {doc.id for doc in docs if doc.path in changed}
    if repo is not None:
        rels = {path.relative_to(repo).as_posix() for path in changed if path.is_relative_to(repo)}
        sources = {source.split("::")[0] for source in check_sources.values()}
        for doc in docs:
            paths, globs = repo_dependencies(doc, kinds)
            hit = rels & set(paths) or any(Glob(g).matches(rel) for g in globs for rel in rels)
            tests = {check_sources.get(link.target, "").split("::")[0] for link in links if link.doc == doc.id}
            if hit or (rels & tests & sources):
                direct.add(doc.id)
    return Scope(False, frozenset(reverse_closure(direct, links, owner)))
