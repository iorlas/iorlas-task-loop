"""Documents: discovery by file pattern, frontmatter parse, schema validation, row and link walks."""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from any_frontmatter import FrontmatterError, read
from any_markdown import Markdown

from docscheck.ontology import Field, Kind
from docscheck.schema import validate_frontmatter
from docscheck.values import Finding, Json, as_list, as_map, plain


@dataclass(frozen=True)
class Doc:
    id: str
    kind: str
    slug: str
    path: Path
    data: dict[str, Json]
    body: str


@dataclass(frozen=True)
class Row:
    """An inline row: its kind, its values, and the owner doc and field path it sits at."""

    kind: str
    values: dict[str, Json]
    doc: str
    path: str


@dataclass(frozen=True)
class Link:
    """A reference in a doc: `field` (a path) points to `target`; `kinds` limits what it may be (empty: any kind)."""

    doc: str
    field: str
    target: str
    kinds: tuple[str, ...]
    default: str | None = None


def pattern_slug(pattern: str, rel: str) -> str | None:
    """The slug `rel` has under a file pattern like `system/area/{slug}.md`, or None when it does not match."""
    regex = re.escape(pattern).replace(r"\{slug\}", r"(?P<slug>[a-z0-9][a-z0-9-]*)")
    match = re.fullmatch(regex, rel)
    if match is None:
        return None
    return match.groupdict().get("slug") or Path(rel).stem


def _place(kinds: dict[str, Kind], rel: str) -> tuple[Kind, str] | None:
    for kind in kinds.values():
        if kind.file_pattern and (slug := pattern_slug(kind.file_pattern, rel)) is not None:
            return kind, slug
    return None


def load_docs(root: Path, kinds: dict[str, Kind]) -> tuple[list[Doc], list[Finding]]:
    docs: list[Doc] = []
    found: list[Finding] = []
    for path in sorted(root.rglob("*.md")):
        rel = path.relative_to(root).as_posix()
        placed = _place(kinds, rel)
        if placed is None:
            found.append(Finding(rel, "path", "unplaced", "no kind has a file pattern matching this path"))
            continue
        kind, slug = placed
        try:
            document = read(path)
        except FrontmatterError as error:
            found.append(Finding(f"{kind.name}/{slug}", "frontmatter", "unreadable", str(error)[:120]))
            continue
        data = as_map(plain(document.frontmatter))
        doc = Doc(f"{kind.name}/{slug}", kind.name, slug, path, data, document.body)
        docs.append(doc)
        found.extend(validate_frontmatter(doc.id, kind, kinds, data))
        if kind.body == "none" and document.body.strip():
            found.append(Finding(doc.id, "body", "body-not-allowed", "this kind has no body; put facts in fields"))
    return docs, found


def _inline_children(field: Field, value: Json) -> list[tuple[int, dict[str, Json]]]:
    return [(index, as_map(item)) for index, item in enumerate(as_list(value))] if field.type.base == "inline" else []


def walk_rows(kind: Kind, kinds: dict[str, Kind], doc: str, data: dict[str, Json], path: str = "") -> Iterator[Row]:
    """Every inline row under `data`, depth first, in file order."""
    for field in kind.fields:
        for index, child in _inline_children(field, data.get(field.name)):
            inner = kinds[field.type.targets[0]]
            where = f"{path}{field.name}[{index}]"
            yield Row(inner.name, child, doc, where)
            yield from walk_rows(inner, kinds, doc, child, where + ".")


def _field_links(field: Field, value: Json, doc: str, where: str) -> Iterator[Link]:
    if field.type.base != "link" or value is None:
        return
    items = as_list(value) if field.type.shape != "one" else [value]
    for index, item in enumerate(items):
        if isinstance(item, str):
            kinds = () if "any" in field.type.targets else field.type.targets
            yield Link(doc, f"{where}[{index}]" if field.type.shape != "one" else where, item, kinds, field.default)


def walk_links(kind: Kind, kinds: dict[str, Kind], doc: str, data: dict[str, Json], path: str = "") -> Iterator[Link]:
    """Every link field value, then every `[[kind/id]]` in a string value, under `data`."""
    for field in kind.fields:
        value = data.get(field.name)
        where = f"{path}{field.name}"
        yield from _field_links(field, value, doc, where)
        if field.type.base == "inline":
            for index, child in _inline_children(field, value):
                yield from walk_links(kinds[field.type.targets[0]], kinds, doc, child, f"{where}[{index}].")
        elif field.type.base == "string":
            for text in ([value] if field.type.shape == "one" else as_list(value)):
                yield from _wikilinks(doc, where, text)


def _wikilinks(doc: str, where: str, text: Json) -> Iterator[Link]:
    if isinstance(text, str) and "[[" in text:
        for link in Markdown(text).wikilinks:
            yield Link(doc, where, link.anchor, ())


def body_links(doc: Doc) -> Iterator[Link]:
    yield from _wikilinks(doc.id, "body", doc.body)


def walk_values(kind: Kind, kinds: dict[str, Kind], data: dict[str, Json], path: str = "") -> Iterator[tuple[str, Field, Json]]:
    """Every (path, field, value) under `data`, rows included; a list value is yielded whole, then its rows."""
    for field in kind.fields:
        value = data.get(field.name)
        if value is None:
            continue
        yield f"{path}{field.name}", field, value
        if field.type.base == "inline":
            for index, child in _inline_children(field, value):
                yield from walk_values(kinds[field.type.targets[0]], kinds, child, f"{path}{field.name}[{index}].")
