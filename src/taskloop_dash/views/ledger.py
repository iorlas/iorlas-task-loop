"""The ask ledger, the decisions in force and the repeat match of a card, as the page's records (dash-spec 5.1, 7.2).

One LedgerRow per ask: folded from its rows in the ledger (raise, answer, cause, outcome...), so the newest row says the cause and the
outcome. An ask that ended unanswered (closed, withdrawn, or replaced by a newer one) is not a row: the ledger lists asks that wait or
that were answered. A row is open only while its ask is the bead's live ask."""
import os
from collections.abc import Sequence

from taskloop.contracts.ask import Ask
from taskloop.contracts.dash import AdrRow, LedgerRow, Similar
from taskloop.contracts.ledger import LedgerEntry
from taskloop_dash.views.world import ProjectIn, World

LEDGER_MAX = 500
PRUNE_AFTER_S = 30 * 86400  # a decision no plan cited for 30 days is offered for pruning (dash-spec 7.2)


def project_of(repo: str) -> str:
    """A project is a registered repo named by its folder."""
    return os.path.basename(repo.rstrip("/"))


def by_ask(rows: Sequence[LedgerEntry]) -> dict[str, list[LedgerEntry]]:
    out: dict[str, list[LedgerEntry]] = {}
    for r in rows:
        out.setdefault(r.ask, []).append(r)
    return out


def row_of(rs: list[LedgerEntry], live: Ask | None) -> LedgerRow | None:
    raised = next((r for r in rs if r.event == "raise"), None)
    if raised is None:
        return None
    answered = next((r for r in reversed(rs) if r.event == "answer"), None)
    last = rs[-1]
    if answered is None and not (live is not None and live.id == raised.ask):
        return None
    status = "answered" if answered else "open" if last.blocking else "open_soft"
    return LedgerRow(t=raised.t, ask=raised.ask, bead=raised.bead, project=project_of(raised.repo), question=raised.question, status=status,
                     answer=answered.answer if answered else "", outcome=last.outcome, outcome_ref=last.outcome_ref, cause=last.cause)


def ledger_rows(w: World, shown: set[tuple[str, str]]) -> list[LedgerRow]:
    """Newest first, at most LEDGER_MAX; an open row only for a bead the snapshot shows (`shown`: (project, bead))."""
    out: list[LedgerRow] = []
    for rs in by_ask(w.ledger).values():
        row = row_of(rs, w.asks.get(rs[0].bead))
        if row is not None and (row.status == "answered" or (row.project, row.bead) in shown):
            out.append(row)
    return sorted(out, key=lambda r: -r.t)[:LEDGER_MAX]


def adr_rows(w: World) -> list[AdrRow]:
    return [AdrRow(id=a.adr.id, project=p.id, text=a.adr.text, t=a.adr.t, reuses=a.reuses, last_used=a.last_used,
                   prune=a.reuses == 0 and w.now - a.adr.t > PRUNE_AFTER_S)
            for p in w.projects for a in p.adrs]


def similar_of(a: Ask, p: ProjectIn, w: World) -> Similar | None:
    """The first match of the ask's repeat key that can still be shown: a decision in force of the repo, else a past answered ask."""
    for ref in a.similar:
        if ref.kind == "adr":
            found = next((x.adr for x in p.adrs if x.adr.id == ref.id), None)
            if found is not None:
                return Similar(bead=found.bead, question=found.question, answer=found.text, t=found.t)
            continue
        rs = [r for r in w.ledger if r.ask == ref.id]
        raised = next((r for r in rs if r.event == "raise"), None)
        answered = next((r for r in reversed(rs) if r.event == "answer"), None)
        if raised is not None and answered is not None:
            return Similar(bead=raised.bead, question=raised.question, answer=answered.answer, t=raised.t)
    return None
