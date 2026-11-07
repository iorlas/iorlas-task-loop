"""Plan parts over facts, fake capabilities and plain shared hand-offs, without an Engine."""
from pathlib import Path
from types import SimpleNamespace

from support.facts import FakeChecker, MemCheckpoints, fake_facts
from support.fake_beads import FakeBeads
from support.fakegit import FakeGit
from taskloop.adapters.check_probe import PathProbe
from taskloop.app.pipeline.leftover_queue import LeftoverQueue
from taskloop.app.plan.amend import AmendState
from taskloop.app.plan.briefs import Briefs
from taskloop.app.plan.cases import Cases
from taskloop.app.plan.planner import Planner
from taskloop.app.plan.state import PlanState
from taskloop.domain.work.ledger import Ledger
from tlkernel.asked import Asked
from tlkernel.askspec import AskSpec
from tlkernel.config import EngineConfig
from tlkernel.gitfacts import TreeEntry
from tlkernel.plancheck import PlanData
from tlkernel.stop import Stop


class PlanGit(FakeGit):
    """An empty ADR tree; other reads must be scripted."""

    def ls_tree(self, d: str, rev: str, *paths: str, recursive: bool = False) -> list[TreeEntry]:
        self.seen("ls_tree", rev, *paths)
        return []


class PlanChecker(FakeChecker):
    round = 0


class PlanProbe(PathProbe):
    """Command lookup with no PATH or process dependency."""

    def has_command(self, word: str) -> bool:
        return word in {"test", "echo", "true"}

    def recipes(self) -> set[str] | None:
        return None


class FakePlanPorts:
    """Queued planner answers, memory stores and empty collaborators."""

    routing: SimpleNamespace
    cases: Cases
    briefs: Briefs
    leftover_sink: LeftoverQueue

    def __init__(self, workdir: Path, cfg: EngineConfig | None = None) -> None:
        self.facts, run = fake_facts(workdir, cfg=cfg)
        assert isinstance(run.checkpoints, MemCheckpoints)
        assert isinstance(run.store, FakeBeads)
        self.steps, self.log, self.stores, self.checkpoints = run.steps, run.log, run.stores, run.checkpoints
        self.store, self.clock, self.git = run.store, run.clock, PlanGit()
        self.checker = PlanChecker()
        self.checkout = SimpleNamespace(tree_hash=lambda: "", task_diff=lambda: "", base_sha=lambda: "base")
        self.ask_flow = SimpleNamespace(repo=lambda: "repo", raise_soft=lambda *a, **kw: None)
        self.pictures = SimpleNamespace(visual_cfg=lambda: None, shot_methods=lambda: [], shot_table=lambda: "")
        self.briefing = SimpleNamespace(where=lambda *a, **kw: "")
        self.hand = SimpleNamespace(rounds_text=lambda: "")
        self.shared = SimpleNamespace(shared_text=lambda: "")
        self.comments: list[str] = []
        self.warned: list[str] = []
        self.assumptions: list[str] = []
        self.answers: list[Asked] = []
        self.asked: list[tuple[str, str, str]] = []
        self.published = 0

    def ai(self, node: str, title: str, prompt: str, *a: object, **kw: object) -> Asked:
        self.asked.append((node, title, prompt))
        return self.answers.pop(0)

    def comment(self, text: str) -> None:
        self.comments.append(text)

    def warn(self, text: str) -> None:
        self.warned.append(text)

    def assumed(self, text: str) -> None:
        self.assumptions.append(text)

    def now(self) -> float:
        return self.clock.now()

    def publish_plan(self) -> None:
        self.published += 1

    def shell_probe(self) -> PathProbe:
        return PlanProbe(self.facts.wt, {}, self.now)

    def blocked_for(self, why: str, kind: str, stop: object = None, spec: AskSpec | None = None, fix: bool = False) -> Stop:
        return Stop(why)

    def move_host(self, needs: list[str], why: str) -> Stop:
        return Stop(why)


class FakePlan:
    """The RunHost builders with PlanState, AmendState and a plain hand."""

    def __init__(self, workdir: Path, cfg: EngineConfig | None = None) -> None:
        self.ports = FakePlanPorts(workdir, cfg)
        self.facts, self.plan_state, self.amend = self.ports.facts, PlanState(), AmendState()
        self.hand = SimpleNamespace(scope="", answered=None, verify_answer="", landed_sha="", planner_ref="", kind="",
                                    plan_data=None, plan_summary="", plan_log=[], planned=0, extra=0, done=[], leftovers=[],
                                    brief_hash="", snap=None)
        self.ports.leftover_sink = LeftoverQueue(self.hand)
        self.ports.routing = SimpleNamespace(ledger=self.ledger, ledger_of=Ledger)
        self.cases = self.ports.cases = Cases(self.facts, self.ports, self.plan_state, self.amend, self.hand)
        self.briefs = self.ports.briefs = Briefs(self.facts, self.ports, self.plan_state, self.amend, self.hand)
        self.planner = Planner(self.facts, self.ports, self.plan_state, self.amend, self.hand)
        self.cap = self.planner.cap

    def ledger(self) -> Ledger:
        data: PlanData | None = self.hand.plan_data
        return Ledger(data, self.hand.leftovers)
