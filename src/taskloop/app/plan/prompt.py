"""The planner's prompt: the template, then what the run knows that changes the plan (an old plan and what changed, a failed one, the
rounds so far, the accepted stages, the owner's answer) and the rules the checks must follow."""
import json
from pathlib import Path

from tlkernel import plancheck
from tlkernel.gitport import Git
from tlkernel.plancheck import PlanData
from tlkernel.stagefacts import RunFacts

from taskloop.app.plan.amend import AmendState
from taskloop.app.plan.decisions import Decisions
from taskloop.app.plan.host import PlanHand, PlanPorts
from taskloop.app.plan.probe import AcProbe
from taskloop.app.plan.prompts import PLAN_PROMPT, SHOW_PLAN, VISUAL_PLAN, VISUAL_STAGES
from taskloop.app.plan.state import PlanState
from taskloop.domain.checks import lint
from taskloop.domain.checks.names import norm

REPLAN_CALLS = 6  # the calls a replan may spend looking (study 63: the median replan used 4)


class PlanPrompt:
    def __init__(self, facts: RunFacts, ports: PlanPorts, plan_state: PlanState, amend: AmendState,
                 hand: PlanHand, git: Git) -> None:
        self.facts, self.ports, self.plan_state, self.amend, self.hand = facts, ports, plan_state, amend, hand
        self.git = git
        self.decisions = Decisions(facts, ports, plan_state, amend, hand)
        self.probe = AcProbe(facts, ports, plan_state, amend, hand)

    def notes(self) -> str:
        """engine.planner_notes: text, or "@path" of a repo file (read from the worktree), at most 2000 characters."""
        v = (self.facts.cfg.planner_notes or "").strip()
        if v.startswith("@"):
            try:
                v = (Path(self.facts.wt) / v[1:]).read_text(encoding="utf-8").strip()
            except OSError:
                self.ports.warn(f"engine.planner_notes: {v} cannot be read")
                return ""
        return v[:2000]

    def change(self, old: PlanData | None, again: bool, why: str) -> str:
        """What the planner is told of an earlier plan or a failed one."""
        if old:
            return ("\n\nAn earlier plan exists for this task. Return the plan with the smallest change that covers what "
                    "follows; keep accepted stages and their checks unless the change touches them; do not re-explore code "
                    "the old plan already names. Same output schema as a plan.\n<old_plan>\n"
                    f"{json.dumps(plancheck.to_wire(old), indent=1)}\n</old_plan>\n"
                    f"What changed:\n<change>\n{(self.amend.text or why).strip()}\n</change>")
        if again:
            return f"\n\nThe previous plan did not work. What failed:\n<failed>\n{why}\n</failed>\nPlan again."
        return ""

    def history(self, old: PlanData | None, again: bool) -> str:
        """The rounds before the last one (tl-bxk.13.6: replan.md holds the last round only), and what the tasks beside this one defer."""
        out = ""
        hist = self.ports.hand.rounds_text()
        if hist and (old or again):
            out += ("\n\nWhat the rounds on this task did so far (the writer's summary, then what was sent back). Do not "
                    f"plan a fix that already failed to hold:\n<rounds>\n{hist}</rounds>\n")
        return out + (self.digest() + self.ports.routing.ledger().text() if old or again else "")

    def digest(self) -> str:
        """What a replan starts from beyond the old plan, the cause and the rounds: what the tree holds now, and a budget for looking."""
        tree = self.ports.checkout.tree_hash()
        stat = (self.git.diff(self.facts.wt, self.ports.checkout.base_sha(), tree, stat=True) if tree else "").strip()
        return (f"\n\nThe tree now, against the task's base (git diff --stat):\n<tree>\n{stat or '(no file changed yet)'}\n</tree>\n"
                f"The old plan, the cause and the rounds above are your start: read at most {REPLAN_CALLS} files or run at most "
                f"{REPLAN_CALLS} commands before you answer.\n")

    def rules(self) -> list[str]:
        rules = []
        wr = self.ports.cases.rules_text()
        if wr:
            rules.append("This repo's rules for workers (what runs where, known pitfalls of its tools); the checks you "
                         f"write must follow them:\n<worker_rules>\n{wr}\n</worker_rules>")
        notes = self.notes()
        if notes:
            rules.append("Facts about this factory and project that the plan must respect:\n" + notes)
        adrs = self.decisions.text()
        if adrs:
            rules.append(adrs)
        shared = self.ports.shared.shared_text()
        if shared:
            rules.append(shared.strip())
        visual_cfg = self.ports.pictures.visual_cfg()
        if visual_cfg and self.ports.pictures.shot_methods():  # the classes mean "the engine renders": only with a shot table
            rules.append(VISUAL_PLAN)
            rules.append(VISUAL_STAGES % (", ".join(visual_cfg.include)[:300], self.ports.pictures.shot_table()))
        rules.append(SHOW_PLAN)
        rules.append("Proof files that a check reads or a reviewer looks at (screenshots, logs, probe output) go under "
                     f"{self.facts.evidence_dir}: it is kept across runs, and nothing else under {self.facts.task_dir} is.")
        repo = self.facts.cfg.stage_checks
        if repo:
            rules.append("The repo's own checks (id: command), run every round by the engine; never write their command as a check:\n"
                         + "\n".join(f"- {k.id}: `{k.cmd}`" for k in repo))
        gate, has = self.facts.cfg.gate_text, bool(self.facts.cfg.gate_checks)
        rules.append("Checks run on the uncommitted working tree after each write. The engine runs the gate{} once, on "
                     "the rebased tree at land: never put {} in a stage's checks, and a criterion that names it is proven "
                     "by that land gate: write no case for it.".format((f" (`{gate}`)") if has else "", f"`{gate}`" if has else "it"))
        rules.extend(self.extra_gates())
        return rules

    def extra_gates(self) -> list[str]:
        """Name every gate-only command beyond the gate command already named in the preceding rule."""
        gate = norm(self.facts.cfg.gate_text)
        extra_gated = [(c, w) for c, w in lint.gate_only(self.facts.cfg) if c != gate]
        if extra_gated:
            return ["These run only in the gate at land too, never in a check: "
                    + "; ".join(f"`{c}`" + (f" ({w})" if w != lint.GATE_WHY else "") for c, w in extra_gated) + "."]
        return []

    def tail(self) -> str:
        """The owner's verify answer and the stages already accepted on this branch."""
        out = ""
        if self.hand.verify_answer:
            out += ("\n\nEvery stage was accepted, then the owner checked the work and answered:\n"
                    f"<answer>\n{self.hand.verify_answer}\n</answer>\n"
                    "Plan only the work this answer asks for. If it asks for nothing more (it says the work is right), "
                    "return no stages: the engine then lands.")
        if self.hand.done:
            out += ("\n\nThese stages are already accepted on this branch (reviewed, their work is in the tree): "
                    "do not plan them again; plan only what the task still needs.\n" + "".join(f"- {g}\n" for g in self.hand.done))
        return out

    def build(self, old: PlanData | None, again: bool, why: str) -> str:
        extra = self.change(old, again, why)
        self.amend.old_plan, self.amend.text, self.amend.why = None, "", ""
        extra += self.history(old, again)
        if not old and not again:
            extra += self.probe.text()  # tl-9un.1: what the acceptance names that cannot work, before the first plan
        rules = self.rules()
        extra += self.tail()
        where = self.ports.briefing.where("plan")
        return (PLAN_PROMPT.format(brief=self.ports.briefs.text(), wt=self.facts.wt) + extra + "\n\n" + "\n".join(rules)
                + ("\n\n" + where if where else ""))
