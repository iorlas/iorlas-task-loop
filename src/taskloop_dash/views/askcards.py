"""The open ask or look of a bead as the v2 AskCard: whole, from the typed Ask and the look item. The agent's declared cause, the
blocking flag and its default, the ask-back thread, the repeat match and the staleness count all come from typed fields or the ledger."""

from taskloop.contracts.ask import Ask
from taskloop.contracts.dash import AskCard, AskOptionCard, Similar, ThreadMsg
from taskloop_dash.views.artifact_files import Item, plain, served, split_stage, url_of
from taskloop_dash.views.board import is_work, when
from taskloop_dash.views.world import LookItem, ProjectIn


def stale_of(a: Ask, p: ProjectIn) -> int:
    """Beads of the project that landed (closed) since the ask was made, the asking bead not counted."""
    return sum(1 for b in p.beads if b.id != a.bead and b.status == "closed" and is_work(b) and (when(b.closed_at) or 0.0) > a.t)


def url_of_id(artifact: str) -> str:
    """The URL that reads an artifact id (`<repo>/<bead>/<run>/<stage>-<attempt>/<name>`); "" for an id that is not one."""
    parts = artifact.split("/")
    staged = split_stage(parts[3]) if len(parts) == 5 else None
    if staged is None or not all(plain(x) for x in parts):
        return ""
    repo, bead, run, _, name = parts
    kind, _ = served(name)
    return url_of(repo, bead, Item(run=run, stage=staged[0], attempt=staged[1], name=name, kind=kind, caption="", role="after", t=0.0))


def ask_card(project: str, a: Ask, similar: Similar | None = None, stale: int = 0) -> AskCard:
    return AskCard(
        id=a.id, bead=a.bead, project=project, run=a.run, source="ask", question=a.decision, t=a.t, blocking=a.blocking, why=a.why,
        tried=list(a.tried),
        options=[AskOptionCard(label=o.label, consequence=o.consequence, recommended=o.recommended) for o in a.options],
        default=a.default, owner_cause=a.owner_cause, cause_by=a.cause_by,
        thread=[ThreadMsg(by=m.by, t=m.t, md=m.md) for m in a.thread], ask_backs=sum(1 for m in a.thread if m.by == "owner"),
        similar=similar, stale=stale, artifacts=[u for x in a.artifacts if (u := url_of_id(x))])


def look_card(project: str, item: LookItem, t: float) -> AskCard:
    return AskCard(id=f"{item.bead}-look", bead=item.bead, project=project, source="look", question=item.title or "your look", t=t,
                   artifacts=list(item.artifacts))
