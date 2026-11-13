"""The id index: every doc and every referable row, link resolution, dangling findings with suggestions."""

import difflib
import re
from dataclasses import dataclass

from docscheck.docs import Doc, Link, body_links, walk_links, walk_rows
from docscheck.ontology import Kind
from docscheck.values import Finding

OWN_CHECK = frozenset({"case", "transition"})  # a repeated key is reported by their own rules, with more words
TASK = re.compile(r"^task/[a-z0-9][a-z0-9._-]*$")


@dataclass(frozen=True)
class Entry:
    id: str
    kind: str
    doc: str  # the doc owning it ("" for ids the repo owns)


def slugify(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._]+", "-", text).strip("-")[:48] or "x"


def row_id(kind: Kind, values: dict[str, object], doc_slug: str) -> str:
    keys = [slugify(str(values.get(name, ""))) for name in kind.keys]
    if kind.scope == "global":
        return f"{kind.name}/{keys[0]}"
    return f"{kind.name}/{doc_slug}." + ".".join(keys)


def build_index(docs: list[Doc], kinds: dict[str, Kind], repo_ids: dict[str, str]) -> tuple[dict[str, Entry], list[Finding]]:
    entries: dict[str, Entry] = {}
    found: list[Finding] = []

    def add(entry: Entry, where: str) -> None:
        if entry.id in entries and entry.kind in OWN_CHECK:
            return
        if entry.id in entries:
            found.append(Finding(entry.doc or where, "id", "duplicate-id", f"{entry.id} is also declared in {entries[entry.id].doc or 'the repo'}"))
        else:
            entries[entry.id] = entry

    for name in repo_ids:
        add(Entry(name, name.split("/")[0], ""), name)
    for doc in docs:
        add(Entry(doc.id, doc.kind, doc.id), doc.id)
        for row in walk_rows(kinds[doc.kind], kinds, doc.id, doc.data):
            inner = kinds[row.kind]
            if inner.keys and not inner.derived:
                add(Entry(row_id(inner, dict(row.values), doc.slug), row.kind, doc.id), doc.id)
    return entries, found


def suggest(target: str, entries: dict[str, Entry]) -> str:
    kind = target.split("/")[0]
    pool = [name for name, entry in entries.items() if entry.kind == kind] or list(entries)
    close = difflib.get_close_matches(target, pool, n=1, cutoff=0.6)
    return f"; nearest: {close[0]}" if close else ""


def resolve(link: Link, entries: dict[str, Entry]) -> Finding | None:
    if link.default is not None and link.target == link.default:
        return None
    kind = link.target.split("/")[0]
    if link.kinds and kind not in link.kinds:
        return Finding(link.doc, link.field, "wrong-kind", f"{link.target} is a {kind}; allowed: {'|'.join(link.kinds)}")
    if kind == "task":
        return None if TASK.match(link.target) else Finding(link.doc, link.field, "bad-task-id", link.target)
    if link.target in entries:
        return None
    return Finding(link.doc, link.field, "dangling-ref", link.target + suggest(link.target, entries))


def all_links(docs: list[Doc], kinds: dict[str, Kind]) -> list[Link]:
    links: list[Link] = []
    for doc in docs:
        links.extend(walk_links(kinds[doc.kind], kinds, doc.id, doc.data))
        links.extend(body_links(doc))
    return links


def check_links(links: list[Link], entries: dict[str, Entry]) -> list[Finding]:
    return [item for link in links if (item := resolve(link, entries)) is not None]


def edges(links: list[Link], entries: dict[str, Entry]) -> dict[str, set[str]]:
    """Doc id -> the docs it points to (through any link or wikilink); repo-owned and task ids are not docs."""
    graph: dict[str, set[str]] = {}
    for link in links:
        target = entries.get(link.target)
        if target is not None and target.doc and target.doc != link.doc:
            graph.setdefault(link.doc, set()).add(target.doc)
    return graph

