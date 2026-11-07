"""The run as its steps see it: the land, plan and machinery parts, and the two that need them all, the worker call and the close.
The Engine (engine.py) opens a run into this; the steps (stages.py, crash.py) are typed against it and never import the Engine."""
from functools import cached_property
from typing import Any

from taskloop.app.look.judge import Judge
from taskloop.app.look.owner_look import OwnerLook
from taskloop.app.look.shots import Pictures
from taskloop.app.run import summaries
from taskloop.app.run.closer import Closer, closer_over
from taskloop.app.run.parts_land import LandParts
from taskloop.app.run.parts_plan import PlanParts
from taskloop.app.run.parts_run import RunParts
from taskloop.app.workers import asked
from taskloop.app.workers.worker_call import Ops, WorkerCall
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
