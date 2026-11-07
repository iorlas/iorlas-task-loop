"""The run as its steps see it: the land, plan and machinery parts, and the two that need them all, the worker call and the close.
The Engine (engine.py) opens a run into this; the steps (stages.py, crash.py) are typed against it and never import the Engine."""
from functools import cached_property
from typing import Any

from taskloop.app.look.judge import Judge
from taskloop.app.look.owner_look import OwnerLook
from taskloop.app.look.shots import Pictures
from taskloop.app.pipeline import summaries
from taskloop.app.pipeline.closing import Closer
from taskloop.app.plan.briefs import Briefs
from taskloop.app.plan.cases import Cases
from taskloop.app.plan.planner import Planner
from taskloop.app.review.link_check import LinkCheck
from taskloop.app.review.routing import Routing
from taskloop.app.review.settles import Settles
from taskloop.app.review.verifier import Verifier
from taskloop.app.run.closer_ports import closer_over
from taskloop.app.run.parts_land import LandParts
from taskloop.app.run.parts_plan import PlanParts
from taskloop.app.run.parts_run import RunParts
from taskloop.app.workers import asked
from taskloop.app.workers.worker_call import Ops, WorkerCall
from taskloop.app.write.handoff import Handoff
from taskloop.contracts import plancheck
from taskloop.contracts.stagefacts import RunFacts
from taskloop.domain.lanes.matchers import read_only_command
from taskloop.domain.lanes.says import stop_say, stop_why
from taskloop.stores.runports import RunPorts


class RunHost(LandParts, PlanParts, RunParts):
    facts: RunFacts  # the Engine opens both (app/run/facts.py)
    ports: RunPorts
    done: list[str]  # RunState fields the tests assign
    accepted: list[int]
    stage_tree: str
    replan_first: bool

    @property
    def intake_per_day(self) -> int:  # the Engine's: CloserHost reads it
        raise NotImplementedError

    def on_path(self, name: str) -> str | None:
        raise NotImplementedError

    @cached_property
    def hand(self) -> Handoff:
        return Handoff(self, self.git)

    @cached_property
    def cases(self) -> Cases:
        return Cases(self.facts, self, self.plan_state, self.amend, self)

    @cached_property
    def briefs(self) -> Briefs:
        return Briefs(self.facts, self, self.plan_state, self.amend, self)

    @cached_property
    def planner(self) -> Planner:
        return Planner(self.facts, self, self.plan_state, self.amend, self)

    @cached_property
    def pictures(self) -> Pictures:
        return Pictures(self.facts, self, self.look, self, self.git)

    @cached_property
    def owner_look(self) -> OwnerLook:
        return OwnerLook(self.facts, self, self.look, self, self.git)

    @cached_property
    def judge(self) -> Judge:
        return Judge(self.facts, self, self.look, self)

    @cached_property
    def routing(self) -> Routing:
        return Routing(self.facts, self, self.review, self, self.git)

    @cached_property
    def settles(self) -> Settles:
        return Settles(self.facts, self, self.review, self, self.git)

    @cached_property
    def link_check(self) -> LinkCheck:
        return LinkCheck(self.facts, self, self.review, self)

    @cached_property
    def verifier(self) -> Verifier:
        return Verifier(self.facts, self, self.review, self)

    @cached_property
    def worker(self) -> WorkerCall:
        return WorkerCall(self, Ops(summaries.summarize, read_only_command, self.blocked_for, stop_why, stop_say, self.records.after_call))

    @cached_property
    def closer(self) -> Closer:
        return closer_over(self, self.worker.saved)

    def ai(self, node: str, title: str, prompt: str, *a: Any, **kw: Any):
        """One AI node, then the tree check: a worker that wrote core.worktree is caught before review or land. Before it, the
        owner's requests are taken (a safe point), and the notes taken since the last call end its prompt (and its delta)."""
        self.requests.at_step(kw.get("step") or node)
        notes = self.requests.prompt_tail()
        if notes:
            prompt += notes
            if kw.get("delta") is not None:
                kw["delta"] += notes
        got = self.worker.run(node, title, prompt, *a, **kw)
        asked.apply(self, got.updates)
        self.assert_tree(kw.get("step") or node, "after")
        plancheck.parse(got.data)
        return got
