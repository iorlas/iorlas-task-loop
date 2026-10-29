"""The dashboard's owner ports as the launcher wires them (src/taskloop/app/launch/dash_ports.py): the app-layer Intake over a given bd."""
import time
from collections.abc import Callable
from pathlib import Path

from taskloop.app.launch.dash_ports import owner_intake, owner_writes
from taskloop.contracts.adrs import AdrStore
from taskloop.contracts.ask import Ask, AskAction
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.ports import Beads
from taskloop.contracts.stores import AskStore
from taskloop_dash.env import Ports


def answering(store: Callable[[str], Beads], config: Path | str, by: str = "dash", clock: Callable[[], float] = time.time,
              factory: Callable[[], Beads | None] | None = None) -> Ports:
    def store_now(repo: str) -> Beads:  # late: a test may swap ports.store after this
        return ports.store(repo)

    def adrs(repo: str) -> AdrStore:
        return AdrStore.at(ConfigDir(config), repo)

    intake = owner_intake(AskStore.at(ConfigDir(config)), store_now, clock, by, adrs, factory)

    def answer(repo: str, bead: str, action: AskAction, text: str, amend: bool) -> tuple[Ask | None, str]:
        return intake(repo).answer(bead, action, text, amend)
    ports = Ports(store=store, answer=answer, **owner_writes(intake, ConfigDir(config)))
    return ports
