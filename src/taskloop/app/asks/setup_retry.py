"""One automatic retry of a missing-setup ask per bead and installed release."""
import json

from tlkernel.ask import AskAnswer
from tlkernel.askenums import AskStatus
from tlkernel.askstore import AskStore
from tlkernel.beadsport import BeadPatch, Beads
from tlkernel.config import EngineConfig
from tlkernel.ids import BeadId

from taskloop.app.asks import release

RETRIED = "setup_retry_versions"


def remaining_versions(text: str, version: str) -> list[str] | None:
    """Fail closed on malformed retry budgets; keep every release so a rollback cannot reset one."""
    try:
        raw = json.loads(text)
    except ValueError:
        return None
    if not isinstance(raw, list):
        return None
    versions = [v for v in raw if isinstance(v, str)]
    return versions if len(versions) == len(raw) and version not in versions else None


def retry_setup(asks: AskStore, store: Beads, bead: BeadId, version: str, now: float,
                cfg: EngineConfig, *, starting: bool = False) -> bool:
    """Answer only missing-setup asks: at engine start, or once the failing gate check uses the slot.

    Reserve the release in bead metadata before answering, so replacing an ask or restarting the loop cannot reset the budget.
    The normal typed answer wakes the park; restore only the pick label that parking actually removed.
    """
    ask = asks.get(bead)
    if (not version or ask is None or ask.answer is not None or ask.consumed is not None
            or ask.status not in (AskStatus.OPEN, AskStatus.PARKED) or "is not set up" not in ask.why.lower()):
        return False
    words = ask.why.replace("`", " ").replace(":", " ").replace(",", " ").split()
    if not starting and not any(c.run_in == "slot" and c.id in words for c in cfg.gate_checks):
        return False
    shown = store.show(bead)
    if shown is None or shown.status == "closed":
        return False
    versions = remaining_versions(shown.metadata.get(RETRIED, "[]"), version)
    if versions is None:
        return False
    store.update(bead, BeadPatch(set_metadata={RETRIED: json.dumps([*versions, version])}))
    _, why = asks.answer(bead, ask.id, AskAnswer(action="rerun", text="retry", t=now, by=f"engine:{version}"))
    if why:
        return False
    release.requeue(store, bead, shown, cfg)
    return True
