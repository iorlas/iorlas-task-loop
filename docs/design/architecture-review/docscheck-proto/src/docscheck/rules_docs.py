"""Checks that need only the docs: banned words, case tables, lifecycle graph, workflow events."""

import re

from docscheck.docs import Doc, walk_rows, walk_values
from docscheck.ontology import Kind
from docscheck.values import Finding, Json, as_list, as_map, as_str

BANNED = re.compile(
    r"\b(must|should|shall|may|might|could|can|usually|typically|generally|normally|prefer(?:red|ably)?|ideally|optional(?:ly)?|"
    r"where possible|if possible|try to|except|unless)\b", re.I,
)
REQUIRED_EVENTS = ("process-death", "restart")


def _texts(value: Json) -> list[str]:
    return [value] if isinstance(value, str) else [item for item in as_list(value) if isinstance(item, str)]


def banned_words(doc: Doc, kinds: dict[str, Kind]) -> list[Finding]:
    found: list[Finding] = []
    for path, field, value in walk_values(kinds[doc.kind], kinds, doc.data):
        if field.rigid and field.type.base == "string":
            for text in _texts(value):
                hit = BANNED.search(re.sub(r"\[\[[^\]]*\]\]", "", text))
                if hit:
                    found.append(Finding(doc.id, path, "hedge-word", f"{hit.group(0)!r}: a rule is true or false; scope it or move it to the tracker"))
    return found


def case_tables(doc: Doc, kinds: dict[str, Kind]) -> list[Finding]:
    declared: dict[str, list[str]] = {}
    cases: list[tuple[str, str, str]] = []
    for row in walk_rows(kinds[doc.kind], kinds, doc.id, doc.data):
        if row.kind == "case_table":
            declared[as_str(row.values.get("name"))] = [as_str(s) for s in as_list(row.values.get("states"))]
        if row.kind == "case":
            cases.append((as_str(row.values.get("table")), as_str(row.values.get("state")), row.path))
    found: list[Finding] = []
    for table, _state, path in cases:
        if table not in declared:
            found.append(Finding(doc.id, path, "case-table-undeclared", f"table {table!r} has no case_tables entry"))
    for table, states in declared.items():
        rows = [(state, path) for name, state, path in cases if name == table]
        seen = [state for state, _ in rows]
        for state in states:
            if seen.count(state) == 0:
                found.append(Finding(doc.id, f"case_tables[{table}]", "case-missing", f"table {table!r} has no case for state {state!r}"))
        for state, path in rows:
            if state not in states:
                found.append(Finding(doc.id, path, "case-unknown-state", f"{state!r} is not a declared state of table {table!r}"))
            if seen.count(state) > 1:
                found.append(Finding(doc.id, path, "case-duplicate", f"table {table!r} has more than one case for state {state!r}"))
    return found


def _reachable(initial: str, edges: list[tuple[str, str]]) -> set[str]:
    seen, queue = {initial}, [initial]
    while queue:
        here = queue.pop()
        for start, end in edges:
            if start == here and end not in seen:
                seen.add(end)
                queue.append(end)
    return seen


def lifecycle(doc: Doc) -> list[Finding]:
    data = doc.data
    states = [as_str(s) for s in as_list(data.get("states"))]
    events = {as_str(e) for e in as_list(data.get("events"))}
    terminal = {as_str(s) for s in as_list(data.get("terminal"))}
    initial = as_str(data.get("initial"))
    rows = [as_map(r) for r in as_list(data.get("transitions"))]
    found: list[Finding] = []

    def bad(field: str, code: str, message: str) -> None:
        found.append(Finding(doc.id, field, code, message))

    if len(set(states)) != len(states):
        bad("states", "state-duplicate", "a state is listed twice")
    for state in [initial, *terminal]:
        if state not in states:
            bad("initial" if state == initial else "terminal", "state-undeclared", f"{state!r} is not in states")
    for event in REQUIRED_EVENTS:
        if event not in events:
            bad("events", "event-required", f"a lifecycle declares {event!r}")
    pairs: list[tuple[str, str]] = []
    for index, row in enumerate(rows):
        start, event, end = as_str(row.get("from")), as_str(row.get("event")), as_str(row.get("to"))
        where = f"transitions[{index}]"
        for state in (start, end):
            if state not in states:
                bad(where, "state-undeclared", f"{state!r} is not in states")
        if event not in events:
            bad(where, "event-undeclared", f"{event!r} is not in events")
        if (start, event) in pairs:
            bad(where, "transition-duplicate", f"state {start!r} has two rows for event {event!r}")
        pairs.append((start, event))
    edges = [(as_str(r.get("from")), as_str(r.get("to"))) for r in rows if r.get("from") != r.get("to")]
    for state in states:
        if state not in terminal and not any(start == state for start, _ in edges):
            bad("transitions", "no-exit", f"non-terminal state {state!r} has no transition to another state")
        if state not in _reachable(initial, edges):
            bad("states", "unreachable", f"state {state!r} is not reachable from {initial!r}")
        if state not in terminal:
            for event in REQUIRED_EVENTS:
                if (state, event) not in pairs:
                    bad("transitions", "transition-missing", f"state {state!r} has no row for event {event!r}")
    return found


def workflow(doc: Doc, lifecycles: dict[str, Doc]) -> list[Finding]:
    members = {as_str(a) for key in ("actors", "areas", "externals") for a in as_list(doc.data.get(key))}
    found: list[Finding] = []
    for index, raw in enumerate(as_list(doc.data.get("steps"))):
        row = as_map(raw)
        where = f"steps[{index}]"
        causes, event, actor = as_str(row.get("causes")), as_str(row.get("event")), as_str(row.get("actor"))
        if actor not in members:
            found.append(Finding(doc.id, where, "actor-not-declared", f"{actor} is not in actors, areas or externals"))
        if bool(causes) != bool(event):
            found.append(Finding(doc.id, where, "causes-event-pair", "causes and event are given together"))
        target = lifecycles.get(causes)
        if causes and target is None:
            continue  # a dangling link is reported by the index
        if target is not None and event not in {as_str(e) for e in as_list(target.data.get("events"))}:
            found.append(Finding(doc.id, where, "event-undeclared", f"{causes} declares no event {event!r}"))
    return found
