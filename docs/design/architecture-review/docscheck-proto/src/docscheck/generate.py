"""Derived output, deterministic: per-tier index and the cross-doc graph. Nothing here is a source of truth."""

from docscheck.docs import Doc, Link
from docscheck.index import Entry
from docscheck.values import as_str

TIER = {"area": "system", "external": "system", "lifecycle": "system", "workflow": "system", "persona": "system",
        "adr": "adr", "runbook": "runbook", "glossary": "glossary", "waivers": "waivers"}
SUMMARY = {"area": "read_when", "adr": "statement", "runbook": "when", "workflow": "goal", "lifecycle": "source", "external": "port",
           "persona": "nature"}


def index_text(docs: list[Doc]) -> str:
    lines: list[str] = []
    for tier in sorted({TIER[doc.kind] for doc in docs}):
        lines.append(f"## {tier}")
        for doc in sorted(docs, key=lambda item: item.id):
            if TIER[doc.kind] == tier:
                lines.append(f"- {doc.id}: {as_str(doc.data.get(SUMMARY.get(doc.kind, '')))}")
    return "\n".join(lines)


def graph_text(links: list[Link], entries: dict[str, Entry]) -> str:
    seen: set[str] = set()
    for link in links:
        target = entries.get(link.target)
        if target is not None and target.doc != link.doc:
            seen.add(f"{link.doc} -> {target.doc or link.target}")
    return "\n".join(sorted(seen))
