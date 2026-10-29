"""The dashboard's `answer` port as the launcher wires it (src/taskloop/app/launch/dash_ports.py): the app-layer Intake over a given bd."""
import time
from collections.abc import Callable
from pathlib import Path

from taskloop.app.asks.intake import Intake
from taskloop.contracts.ask import Ask, AskAction
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import Beads
from taskloop.contracts.stores import AskStore
from taskloop_dash.env import Ports


def answering(store: Callable[[str], Beads], config: Path | str, by: str = "dash") -> Ports:
    def answer(repo: str, bead: str, action: AskAction, text: str, amend: bool) -> tuple[Ask | None, str]:
        return Intake(AskStore.at(ConfigDir(config)), ports.store(repo), time.time, by).answer(bead, action, text, amend)
    ports = Ports(store=store, answer=answer)
    return ports
