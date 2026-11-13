"""Named waivers: a finding allowed until its task closes. The list only shrinks: a waiver that matches nothing is a finding."""

from docscheck.docs import Doc, walk_rows
from docscheck.ontology import Kind
from docscheck.values import Finding, as_str


def waiver_map(docs: list[Doc], kinds: dict[str, Kind]) -> dict[str, str]:
    """Finding key -> task id."""
    found: dict[str, str] = {}
    for doc in docs:
        for row in walk_rows(kinds[doc.kind], kinds, doc.id, doc.data):
            if row.kind == "waiver":
                found[as_str(row.values.get("finding"))] = as_str(row.values.get("task"))
    return found


def apply(findings: list[Finding], waivers: dict[str, str], *, full: bool) -> tuple[list[Finding], list[tuple[Finding, str]]]:
    """(active findings, waived ones). On a full run an unused waiver becomes a finding."""
    active = [f for f in findings if f.key not in waivers]
    waived = [(f, waivers[f.key]) for f in findings if f.key in waivers]
    if full:
        used = {f.key for f, _ in waived}
        active += [Finding("waivers", key, "waiver-stale", f"no finding matches; remove it ({task})") for key, task in sorted(waivers.items()) if key not in used]
    return active, waived
