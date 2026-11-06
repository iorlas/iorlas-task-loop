"""The poller of PR-mode lands: an open PR_OPEN ask whose PR the owner merged (or closed) is answered by the engine, so the bead runs
again and the land reads the PR. Nothing here merges anything: it only looks."""
from collections.abc import Callable

from taskloop.app.asks import release
from taskloop.contracts.ask import AskAnswer
from taskloop.contracts.beadsport import BdFailure, Beads
from taskloop.contracts.config import EngineConfig
from taskloop.contracts.enums import AskClass
from taskloop.contracts.forge import OPEN, Pr, pr_waited_on
from taskloop.contracts.ids import BeadId
from taskloop.contracts.stores import AskStore


def wake_decided(asks: AskStore, store: Beads, view: Callable[[int], Pr | None], repo: str, now: float, cfg: EngineConfig) -> list[BeadId]:
    """Answer each unanswered PR_OPEN ask of this repo whose PR is no longer open. -> the beads woken."""
    woken: list[BeadId] = []
    for ask in asks.live():
        if ask.ask_class != AskClass.PR_OPEN or ask.repo != repo or ask.answer is not None:
            continue
        try:
            shown = store.show(ask.bead)
            number = pr_waited_on(shown.metadata) if shown else 0
            pr = view(number) if number else None
            if shown is None or shown.status == "closed" or pr is None or pr.state == OPEN:
                continue
            _, why = asks.answer(ask.bead, ask.id, AskAnswer(action="rerun", text=pr.state.lower(), t=now, by="engine:pr"))
            if why:
                continue
            release.requeue(store, ask.bead, shown, cfg)
        except BdFailure:
            continue
        woken.append(ask.bead)
    return woken
