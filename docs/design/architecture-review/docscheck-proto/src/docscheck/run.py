"""One check run: load, index, resolve, apply the rules to the docs in scope, apply waivers."""

from dataclasses import dataclass, field
from pathlib import Path

from docscheck.changed import Scope
from docscheck.code_read import repo_check_ids
from docscheck.docs import Doc, Link, load_docs, walk_rows
from docscheck.index import Entry, all_links, build_index, check_links
from docscheck.ontology import Kind, load_kinds
from docscheck.rules_code import lifecycle_source, limits, markers, probes, references, weak
from docscheck.rules_docs import banned_words, case_tables, lifecycle, workflow
from docscheck.values import Finding
from docscheck.waivers import apply, waiver_map


@dataclass(frozen=True)
class Config:
    docs: Path
    ontology: Path
    repo: Path | None = None


@dataclass
class World:
    kinds: dict[str, Kind]
    docs: list[Doc]
    entries: dict[str, Entry]
    links: list[Link]
    findings: list[Finding] = field(default_factory=list)


@dataclass(frozen=True)
class Report:
    findings: list[Finding]
    waived: list[tuple[Finding, str]]
    checked: int
    total: int
    rules: int
    unchecked: int


def load_world(config: Config) -> World:
    kinds, found = load_kinds(config.ontology)
    docs, more = load_docs(config.docs, kinds)
    repo_ids = repo_check_ids(config.repo) if config.repo else {}
    entries, dups = build_index(docs, kinds, repo_ids)
    links = all_links(docs, kinds)
    return World(kinds, docs, entries, links, [*found, *more, *dups])


def _per_doc(doc: Doc, world: World, repo: Path | None, lifecycles: dict[str, Doc]) -> list[Finding]:
    found = [*banned_words(doc, world.kinds), *case_tables(doc, world.kinds)]
    if doc.kind == "lifecycle":
        found += lifecycle(doc)
    if doc.kind == "workflow":
        found += workflow(doc, lifecycles)
    if repo is not None:
        found += references(doc, world.kinds, repo) + limits(doc, world.kinds, repo) + probes(doc, world.kinds, repo)
        if doc.kind == "lifecycle":
            found += lifecycle_source(doc, repo)
    return found


def run_check(config: Config, world: World, scope: Scope) -> Report:
    lifecycles = {doc.id: doc for doc in world.docs if doc.kind == "lifecycle"}
    chosen = [doc for doc in world.docs if scope.full or doc.id in scope.doc_ids]
    found = [f for f in world.findings if scope.full or f.doc in scope.doc_ids]
    found += [f for f in check_links(world.links, world.entries) if scope.full or f.doc in scope.doc_ids]
    for doc in chosen:
        found += _per_doc(doc, world, config.repo, lifecycles)
    if scope.full and config.repo is not None:
        found += markers(world.entries, config.repo)
    counts = [weak(doc, world.kinds) for doc in world.docs if doc.kind in {"area", "external"}]
    active, waived = apply(sorted(set(found)), waiver_map(world.docs, world.kinds), full=scope.full)
    return Report(active, waived, len(chosen), len(world.docs), sum(a for a, _ in counts), sum(b for _, b in counts))


def count_rows(world: World, kind: str) -> int:
    return sum(1 for doc in world.docs for row in walk_rows(world.kinds[doc.kind], world.kinds, doc.id, doc.data) if row.kind == kind)
