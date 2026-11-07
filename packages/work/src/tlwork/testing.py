"""Recording work-stage hosts, assembled only from package code and memory primitives.

FakePlan (ports, hand, probe, git, memory ADRs/checkpoints) serves plan/brief,
plan/plan_ports, plan/plan_noop and plan/replan_digest. FakeLook (ports, hand,
downscale, checkout, repo key) serves look/look_ports and look/pictures_keep.
FakeReview (ports, hand, links, checkout, fixer) serves review/review_ports.
FakeWrite (combined ports and host, queued checks, round handoff) serves
write/requested_checks, write/round_result and write/trustroots.

No new fake is needed for review/findings, matchers, review_live;
plan/amend_state, anchors, answer_boundary, comment_trust, linked_ids,
plan_state, planner_argv, restart_section; write/new_file_kind, write_state;
or domain/test_work_matchers, test_work_skip, test_work_visual: these use
kernel/testkit data or test pure rules/state directly. Brief rendering uses
kernel.planbrief directly, with MemBeads available for tracker reads.

Private testing_* helpers live beside this module, outside the stage packages.
They are not closure seeds; a production import would still count them.
"""
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path

from tlkernel.asked import Asked
from tlkernel.askspec import AskSpec
from tlkernel.checkpoint import RunState, WriterSession
from tlkernel.checks import CheckRun
from tlkernel.config import EngineConfig
from tlkernel.kinds import Kind
from tlkernel.plancheck import PlanData
from tlkernel.stop import Stop
from tlkernel.wire import Open
from tltestkit.fake_clock import FakeClock
from tltestkit.membeads import MemBeads

from tlwork.look.host import PictureBook
from tlwork.look.judge import Judge
from tlwork.look.owner_look import OwnerLook
from tlwork.look.shots import Pictures
from tlwork.look.state import LookState
from tlwork.plan.amend import AmendState
from tlwork.plan.briefs import Briefs
from tlwork.plan.cases import Cases
from tlwork.plan.planner import Planner
from tlwork.plan.state import PlanState
from tlwork.review.link_check import LinkCheck
from tlwork.review.routing import Routing
from tlwork.review.settles import Settles
from tlwork.review.state import ReviewLive
from tlwork.review.verifier import Verifier
from tlwork.testing_git import FakeWorkGit
from tlwork.testing_memory import FakeCheckout, FakeChecks, FakeLeftovers, FakeLog, FakeSteps, FakeWorkStores, MemCheckpoints, fake_facts
from tlwork.testing_parts import (
    FakeAskFlow,
    FakeBriefing,
    FakeBudget,
    FakeCases,
    FakeDownscale,
    FakeFixer,
    FakeJudge,
    FakeLinks,
    FakeLookHand,
    FakePictures,
    FakePlanHand,
    FakeProbe,
    FakeRepoHolder,
    FakeReviewHand,
    FakeRouting,
    FakeText,
    FakeWaits,
    WorkStop,
)
from tlwork.testing_write import FakeNewFiles, FakeWriteHooks, FakeWriteLook, FakeWriterChecks, NoProcesses
from tlwork.write.briefing import Briefing
from tlwork.write.host import AmendFlag
from tlwork.write.state import WriteState


class FakeWorkPorts:
    """Common recording capabilities. An unscripted AI or shell call fails closed."""
    Blocked = WorkStop

    def __init__(self, workdir: Path, cfg: EngineConfig | None = None, *, wt: Path | None = None,
                 run_id: str = "FAKERUN0000") -> None:
        self.facts = fake_facts(workdir, cfg, wt=wt, run_id=run_id)
        self.clock, self.store = FakeClock(), MemBeads()
        self.log, self.steps, self.stores = FakeLog(), FakeSteps(), FakeWorkStores()
        self.checkpoints = MemCheckpoints(self.facts.bead, self.facts.run_id, self.now)
        self.checkout, self.git = FakeCheckout(), FakeWorkGit()
        self.stage_checks = FakeChecks()
        self.budget = FakeBudget()
        self.comments: list[str] = []
        self.warned: list[str] = []
        self.answers: list[Asked] = []
        self.asked: list[tuple[str, str, str, tuple[object, ...], dict[str, object]]] = []
        self.commands: list[tuple[tuple[str, ...], dict[str, object]]] = []
        self.shell_answers: list[tuple[int, str]] = []

    def ai(self, node: str, title: str, prompt: str, *a: object, **kw: object) -> Asked:
        self.asked.append((node, title, prompt, a, kw))
        assert self.answers, f"{node}: no AI answer queued"
        return self.answers.pop(0)

    def comment(self, text: str) -> None:
        self.comments.append(text)

    def warn(self, text: str) -> None:
        self.warned.append(text)

    def now(self) -> float:
        return self.clock.now()

    def blocked_for(self, why: str, kind: str, stop: object = None, spec: AskSpec | None = None, fix: bool = False) -> Stop:
        return WorkStop(why, Kind[kind], spec)

    def sh(self, cmd: Sequence[str], timeout: float = 0, check: bool = False, save: Path | None = None,
           env: Mapping[str, str] | None = None, pin: bool = False, what: str = "", cwd: Path | None = None,
           stop: threading.Event | None = None, *, network: bool = False) -> tuple[int, str]:
        self.commands.append((tuple(cmd), {"timeout": timeout, "check": check, "save": save, "env": env, "pin": pin, "what": what,
                                               "cwd": cwd, "stop": stop, "network": network}))
        assert self.shell_answers, "no shell answer queued"
        answer = self.shell_answers.pop(0)
        if save is not None:
            save.write_text(answer[1])
        if check and answer[0]:
            raise AssertionError(f"command failed: {cmd}: {answer}")
        return answer


class FakePlanPorts(FakeWorkPorts):
    cases: Cases
    briefs: Briefs

    def __init__(self, workdir: Path, cfg: EngineConfig | None = None, hand: FakePlanHand | None = None) -> None:
        super().__init__(workdir, cfg)
        self.briefing = FakeBriefing()
        self.routing = FakeRouting(hand or FakePlanHand())
        self.leftover_sink = FakeLeftovers(self.routing.hand.leftovers)
        self.ask_flow, self.pictures = FakeAskFlow(), FakePictures()
        self.hand, self.shared = FakeText(), FakeText()
        self.probe = FakeProbe()
        self.checker = FakeChecks()
        self.assumptions: list[str] = []
        self.published = 0

    def assumed(self, text: str) -> None:
        self.assumptions.append(text)

    def publish_plan(self) -> None:
        self.published += 1

    def shell_probe(self) -> FakeProbe:
        return self.probe

    def move_host(self, needs: list[str], why: str) -> Stop:
        return Stop(why)


class FakePlan:
    def __init__(self, workdir: Path, cfg: EngineConfig | None = None) -> None:
        self.hand = FakePlanHand()
        self.ports = FakePlanPorts(workdir, cfg, self.hand)
        self.facts, self.plan_state, self.amend = self.ports.facts, PlanState(), AmendState()
        self.cases = self.ports.cases = Cases(self.facts, self.ports, self.plan_state, self.amend, self.hand)
        self.briefs = self.ports.briefs = Briefs(self.facts, self.ports, self.plan_state, self.amend, self.hand)
        self.planner = Planner(self.facts, self.ports, self.plan_state, self.amend, self.hand)
        self.cap = self.planner.cap


class FakeLookPorts(FakeWorkPorts):
    pictures: PictureBook

    def __init__(self, workdir: Path, cfg: EngineConfig | None = None, *, wt: Path | None = None,
                 run_id: str = "FAKERUN0000") -> None:
        super().__init__(workdir, cfg, wt=wt, run_id=run_id)
        self.cases, self.waits = FakeCases(), FakeWaits()
        self.downscale, self.ports = FakeDownscale(), FakeRepoHolder()
        self.leftover_sink = FakeLeftovers([])


class FakeLook:
    def __init__(self, workdir: Path, cfg: EngineConfig | None = None, *, wt: Path | None = None,
                 run_id: str = "FAKERUN0000") -> None:
        self.ports = FakeLookPorts(workdir, cfg, wt=wt, run_id=run_id)
        self.facts, self.hand, self.run = self.ports.facts, FakeLookHand(), RunState()
        self.ports.leftover_sink = FakeLeftovers(self.hand.leftovers)
        self.state = LookState(lambda: self.run)
        self.pictures = Pictures(self.facts, self.ports, self.state, self.hand, self.ports.git)
        self.ports.pictures = self.pictures
        self.owner_look = OwnerLook(self.facts, self.ports, self.state, self.hand, self.ports.git)
        self.judge = Judge(self.facts, self.ports, self.state, self.hand)


class FakeReviewPorts(FakeWorkPorts):
    def __init__(self, workdir: Path, cfg: EngineConfig | None = None) -> None:
        super().__init__(workdir, cfg)
        self.briefing = FakeBriefing()
        self.cases, self.briefs = FakeCases(), FakeText()
        self.judge, self.fixer = FakeJudge(), FakeFixer()
        self.leftover_sink = FakeLeftovers([])
        self.executables: dict[str, str] = {}

    def diff_text(self) -> str:
        return self.checkout.task_diff()

    def on_path(self, name: str) -> str | None:
        return self.executables.get(name)


class ReviewHandoff(FakeReviewHand):
    routing: Routing
    settles: Settles


class FakeReview:
    def __init__(self, workdir: Path, cfg: EngineConfig | None = None) -> None:
        self.ports = FakeReviewPorts(workdir, cfg)
        self.facts, self.live, self.hand = self.ports.facts, ReviewLive(), ReviewHandoff()
        self.ports.leftover_sink = FakeLeftovers(self.hand.leftovers)
        self.git, self.links = self.ports.git, FakeLinks()
        self.routing = self.hand.routing = Routing(self.facts, self.ports, self.live, self.hand, self.git)
        self.settles = self.hand.settles = Settles(self.facts, self.ports, self.live, self.hand, self.git)
        self.link_check = LinkCheck(self.facts, self.ports, self.live, self.hand, self.links)
        self.verifier = Verifier(self.facts, self.ports, self.live, self.hand)


class FakeWrite(FakeWorkPorts):
    """The write capabilities exercised by the package-pure request/result/trust tests.

    Other host members are inert defaults; the process port refuses every call.
    """
    def __init__(self, workdir: Path, cfg: EngineConfig | None = None) -> None:
        super().__init__(workdir, cfg)
        f = self.facts
        self.cfg, self.wt, self.bead, self.run_dir = f.cfg, f.wt, f.bead, f.run_dir
        self.run_id, self.home = f.run_id, f.home
        self.evidence_dir, self.brief_file = f.evidence_dir, f.brief_file
        self.hand = FakeText()
        self.plan_hand = FakePlanHand()
        self.routing = FakeRouting(self.plan_hand)
        self.cases, self.shared = FakeCases(), FakeText()
        self.pictures, self.judge = FakePictures(), FakeJudge()
        self.review = FakeLookHand().review
        self.writer, self.write = WriterSession(), WriteState()
        self.checker = FakeWriterChecks(self.cfg)
        self.briefs = FakeText()
        self.briefing = Briefing(self)
        self.ports = FakeRepoHolder()
        self.newfiles = FakeNewFiles()
        self.ask_flow = self.link_check = self.reload = FakeWriteHooks()
        self.look = FakeWriteLook()
        self.amend: AmendFlag = AmendState()
        self.spawner = NoProcesses()
        self.bead_env: dict[str, str] = {}
        self.branch = ""
        self.at_stage = 0
        self.accepted_new: list[str] = []
        self.plan_data: PlanData | None = None
        self.done: list[str] = []
        self.scope = self.last_flag = self.artifact_repo = ""
        self.render_stale = False
        self.sessions: list[Open] = []
        self.last_run: CheckRun | None = None
        self.stuck_why, self.stage_tree = "", ""
        self.writer_family: str | None = "claude"
        self.stats = {"tests_added": 0, "tests_removed": 0, "rounds": 0, "writes": 0, "reviews": 0}
        self.leftovers: list[dict[str, str]] = []
        self.leftover_sink = FakeLeftovers(self.leftovers)
