"""The run as its steps see it: the land, plan and machinery parts, and the two that need them all, the worker call and the close.
The Engine (engine.py) opens a run into this; the steps (stages.py, crash.py) are typed against it and never import the Engine."""
from collections.abc import Callable
from functools import cached_property

from tlkernel import plancheck
from tlkernel.asked import Asked
from tlkernel.stagefacts import RunFacts
from tlpipeline.api import Closer, LeftoverQueue, summaries
from tlwork.api import Briefs, Cases, Handoff, Judge, LinkCheck, OwnerLook, Pictures, Planner, Routing, Settles, Verifier

from taskloop.adapters import links, looks
from taskloop.app.run.closer_ports import closer_over
from taskloop.app.run.parts_land import LandParts
from taskloop.app.run.parts_plan import PlanParts
from taskloop.app.run.parts_run import RunParts
from taskloop.app.workers import asked
from taskloop.app.workers.worker_call import Ops, WorkerCall
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
    def intake_per_day(self) -> int:  # the Engine's: DecideHost reads it
        raise NotImplementedError

    def on_path(self, name: str) -> str | None:
        raise NotImplementedError

    @cached_property
    def leftover_sink(self) -> LeftoverQueue:
        return LeftoverQueue(self)

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
        return LinkCheck(self.facts, self, self.review, self, links)

    @cached_property
    def verifier(self) -> Verifier:
        return Verifier(self.facts, self, self.review, self)

    @cached_property
    def worker(self) -> WorkerCall:
        return WorkerCall(self, Ops(summaries.summarize, read_only_command, self.blocked_for, stop_why, stop_say, self.records.after_call))

    @cached_property
    def closer(self) -> Closer:
        return closer_over(self, self.worker.saved)

    downscale = staticmethod(looks.downscale)

    def ai(self, node: str, title: str, prompt: str, *a: object, **kw: object) -> Asked:
        """One AI node, then the tree check: a worker that wrote core.worktree is caught before review or land. Before it, the
        owner's requests are taken (a safe point), and the notes taken since the last call end its prompt (and its delta)."""
        step = kw.get("step")
        step = step if isinstance(step, str) and step else node
        self.requests.at_step(step)
        notes = self.requests.prompt_tail()
        if notes:
            prompt += notes
            delta = kw.get("delta")
            if isinstance(delta, str):
                kw["delta"] = delta + notes
        run: Callable[..., Asked] = self.worker.run
        got = run(node, title, prompt, *a, **kw)
        asked.apply(self, got.updates)
        self.assert_tree(step, "after")
        plancheck.parse(got.data)
        return got
