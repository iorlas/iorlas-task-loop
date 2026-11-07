"""The look stage without an Engine (app/look/host.py): Judge, OwnerLook and Pictures built over a RunFacts and the fake ports, the run's
RunState behind a LookState, and the hand-offs as plain attributes. tests/look/test_look_host.py runs the same conformance probe on this
and on the Engine, so a member the stage reads cannot go missing from either."""
import contextlib
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import support.paths  # noqa: F401
from support.facts import fake_facts
from taskloop.app.look.judge import Judge
from taskloop.app.look.owner_look import OwnerLook
from taskloop.app.look.shots import Pictures
from taskloop.app.look.state import LookState
from tlkernel.asked import Asked, Updates
from tlkernel.checkpoint import RunState
from tlkernel.config import EngineConfig
from tlpipeline.api import Blocked, LeftoverQueue


class FakeLookPorts:
    """LookPorts over the fake run ports: what a call records, a worker answer queue, a stage that has no checks and no checkout."""

    leftover_sink: LeftoverQueue

    def __init__(self, workdir: Path, cfg: EngineConfig | None = None, bead: str = "t-1", wt: Path | None = None) -> None:
        self.facts, self.ports = fake_facts(workdir, bead, cfg, wt=wt)
        p = self.ports
        self.steps, self.log, self.store, self.checkpoints = p.steps, p.log, p.store, p.checkpoints
        self.budget = SimpleNamespace(labels=["claude", "codex"])
        self.cases = SimpleNamespace(cases_of=lambda cls: self.case_list.get(cls, []))
        self.case_list: dict[str, list[str]] = {}
        self.stage_checks = SimpleNamespace(stoppable=lambda *a, **kw: None)
        self.checkout = SimpleNamespace(changed_paths=lambda: self.changed)
        self.changed: list[str] = []
        self.waits = SimpleNamespace(locked=lambda what, path, holder=None: contextlib.nullcontext(path))
        self.comments: list[str] = []
        self.warned: list[str] = []
        self.answers: list[Asked] = []  # ai() returns these in order
        self.asked: list[tuple[str, str]] = []
        self.pictures: Pictures

    def ai(self, node: str, title: str, prompt: str, *a: object, **kw: object) -> Asked:
        self.asked.append((node, title))
        return self.answers.pop(0)

    def say(self, data: dict[str, Any], family: str = "claude") -> None:
        self.answers.append(Asked(data=data, family=family, updates=Updates()))

    def comment(self, text: str) -> None:
        self.comments.append(text)

    def warn(self, text: str) -> None:
        self.warned.append(text)

    def now(self) -> float:
        return self.ports.clock.now()

    def sh(self, cmd: Sequence[str], timeout: float = 0, check: bool = False, save: Path | None = None,
           env: Mapping[str, str] | None = None,
           pin: bool = False, what: str = "", cwd: Path | None = None, stop: threading.Event | None = None,
           *, network: bool = False) -> tuple[int, str]:
        return 0, ""


class FakeLookHand:
    """LookHost: the hand-offs as attributes a test reads and sets."""

    Blocked = Blocked

    def __init__(self) -> None:
        self.bead_parent, self.bead_title = "", "Add f"
        self.at_stage, self.last_flag, self.writer_family = 0, "", "claude"
        self.retry_after = 0.0
        self.leftovers: list[dict[str, str]] = []
        self.review = SimpleNamespace(unverified=[])
        self.artifact_repo, self.render_stale = "", False


class FakeLook:
    """The three look parts over one fake run."""

    def __init__(self, workdir: Path, cfg: EngineConfig | None = None, wt: Path | None = None) -> None:
        self.ports = FakeLookPorts(workdir, cfg, wt=wt)
        self.facts, self.hand, self.run = self.ports.facts, FakeLookHand(), RunState()
        self.ports.leftover_sink = LeftoverQueue(self.hand)
        self.state = LookState(lambda: self.run)
        git = self.ports.ports.git
        self.pictures = self.ports.pictures = Pictures(self.facts, self.ports, self.state, self.hand, git)
        self.owner_look = OwnerLook(self.facts, self.ports, self.state, self.hand, git)
        self.judge = Judge(self.facts, self.ports, self.state, self.hand)
