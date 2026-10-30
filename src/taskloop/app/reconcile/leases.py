"""`release_dead`: the lease rules of the reconcile diff on their own, for the loop's step and the run entry: observe the claims of one
repo, plan with the same `strays` rule, give back what is dead. No branch, tree or git is looked at."""
from taskloop.app.reconcile.apply import act_lease
from taskloop.app.reconcile.observe import lease_of, slot_facts
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ports import BdFailure, BeadQuery, Beads
from taskloop.domain.reconcile.diff import lease_actions
from taskloop.domain.reconcile.facts import FreeSlot, ReleaseClaim, RepoView


def release_dead(repo: str, store: Beads, live: dict[BeadId, str], host: str, now: float) -> list[str]:
    """Give back every claim and slot of an engine actor that no run is on and whose lease ended (or never was, or whose holder went on).
    `live`: the runs running now (app/run/running.py). -> one line per claim given back; a claim that moved since the look stays."""
    try:
        held = store.find(BeadQuery())
        view = RepoView(repo, repo.rstrip("/").rsplit("/", 1)[-1], (), leases=tuple(ls for b in held if (ls := lease_of(b, live))),
                        slots=slot_facts([b for b in held if "slot" in b.labels], host, live))
    except BdFailure:
        return []
    return ["released " + a.line for a in lease_actions(view, now) if isinstance(a, ReleaseClaim | FreeSlot) and not act_lease(a, store)]
