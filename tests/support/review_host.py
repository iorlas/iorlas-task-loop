"""The four review parts over frozen facts, fake capabilities and plain shared hand-offs, without an Engine."""
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import SimpleNamespace

from support.facts import fake_facts
from support.fakegit import FakeGit
from taskloop.adapters import links
from tlkernel.asked import Asked
from tlkernel.askspec import AskSpec
from tlkernel.config import EngineConfig
from tlkernel.gitfacts import GrepHit
from tlkernel.kinds import Kind
from tlkernel.stop import Stop
from tlpipeline.api import LeftoverQueue
from tlwork.review.link_check import LinkCheck
from tlwork.review.routing import Routing
from tlwork.review.settles import Settles
from tlwork.review.state import ReviewLive
from tlwork.review.verifier import Verifier


class ReviewGit(FakeGit):
    """An empty tracked tree; other reads can be scripted through FakeGit."""

    def grep(self, d: str, pattern: str, fixed: bool = False, word: bool = False) -> list[GrepHit]:
        self.seen("grep", pattern)
        return []


class ReviewStop(Stop):
    """A typed stop carrying the reason and kind the verifier reads."""

    def __init__(self, why: str, kind: Kind) -> None:
        super().__init__(why)
        self.why, self.kind = why, kind


class FakeReviewPorts:
    """Review's calls: in-memory steps and stores, queued answers and an empty checkout."""

    Blocked = ReviewStop

    leftover_sink: LeftoverQueue

    def __init__(self, workdir: Path, cfg: EngineConfig | None = None) -> None:
        self.facts, run = fake_facts(workdir, cfg=cfg)
        self.steps, self.log, self.stores, self.checkpoints = run.steps, run.log, run.stores, run.checkpoints
        self.budget = SimpleNamespace(labels=["claude", "codex"])
        self.diff = ""
        self.checkout = SimpleNamespace(tree_hash=lambda: "", task_diff=self.diff_text, changed_paths=lambda: [], base_sha=lambda: "")
        self.cases = SimpleNamespace(case_checks=lambda: [])
        self.briefs = SimpleNamespace(text=lambda: "")
        self.briefing = SimpleNamespace(where=lambda *a, **kw: "")
        self.judge = SimpleNamespace(is_look=lambda u: False, look_verify=lambda gaps: "",
                                     look_verdict=lambda u, v, a, why: (v, a, why))
        self.fixer = SimpleNamespace(fix=lambda *a, **kw: "accept")
        self.comments: list[str] = []
        self.warned: list[str] = []
        self.answers: list[Asked] = []
        self.asked: list[tuple[str, str]] = []

    def ai(self, node: str, title: str, prompt: str, *a: object, **kw: object) -> Asked:
        self.asked.append((node, title))
        return self.answers.pop(0)

    def comment(self, text: str) -> None:
        self.comments.append(text)

    def warn(self, text: str) -> None:
        self.warned.append(text)

    def diff_text(self) -> str:
        return self.diff

    def on_path(self, name: str) -> str | None:
        return None

    def blocked_for(self, why: str, kind: str, stop: object = None, spec: AskSpec | None = None, fix: bool = False) -> Stop:
        return ReviewStop(why, Kind[kind])

    def sh(self, cmd: Sequence[str], timeout: float = 0, check: bool = False, save: Path | None = None,
           env: Mapping[str, str] | None = None, pin: bool = False, what: str = "", cwd: Path | None = None,
           stop: threading.Event | None = None, *, network: bool = False) -> tuple[int, str]:
        return 0, ""


class FakeReview:
    """The same construction as RunHost, with shared hand-offs held by a plain object."""

    def __init__(self, workdir: Path, cfg: EngineConfig | None = None) -> None:
        self.ports = FakeReviewPorts(workdir, cfg)
        self.facts, self.live = self.ports.facts, ReviewLive()
        self.hand = SimpleNamespace(scope="", plan_data=None, last_run=None, fixes=0, leftovers=[], at_stage=0,
                                    last_flag="", writer_family="claude")
        self.ports.leftover_sink = LeftoverQueue(self.hand)
        self.git = ReviewGit()
        self.routing = self.hand.routing = Routing(self.facts, self.ports, self.live, self.hand, self.git)
        self.settles = self.hand.settles = Settles(self.facts, self.ports, self.live, self.hand, self.git)
        self.link_check = LinkCheck(self.facts, self.ports, self.live, self.hand, links)
        self.verifier = Verifier(self.facts, self.ports, self.live, self.hand)
