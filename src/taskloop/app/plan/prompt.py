"""The planner's prompt: the template, then what the run knows that changes the plan (an old plan and what changed, a failed one, the
rounds so far, the accepted stages, the owner's answer) and the rules the checks must follow."""
import json
from pathlib import Path
from typing import Any

from taskloop.contracts.argv import checks_to_wire
from taskloop.domain.checks import lint
from taskloop.domain.prompts.plan import PLAN_PROMPT, VISUAL_PLAN, VISUAL_STAGES

REPLAN_CALLS = 6  # the calls a replan may spend looking (study 63: the median replan used 4)


class PlanPrompt:
    def __init__(self, host: Any) -> None:
        self.e = host

    def notes(self) -> str:
        """engine.planner_notes: text, or "@path" of a repo file (read from the worktree), at most 2000 characters."""
        v = (self.e.cfg.planner_notes or "").strip()
        if v.startswith("@"):
            try:
                v = (Path(self.e.wt) / v[1:]).read_text(encoding="utf-8").strip()
            except OSError:
                self.e.warn(f"engine.planner_notes: {v} cannot be read")
                return ""
        return v[:2000]

    def change(self, old: Any, again: bool, why: str) -> str:
        """What the planner is told of an earlier plan or a failed one."""
        e = self.e
        if old:
            return ("\n\nAn earlier plan exists for this task. Return the plan with the smallest change that covers what "
                    "follows; keep accepted stages and their checks unless the change touches them; do not re-explore code "
                    "the old plan already names. Same output schema as a plan.\n<old_plan>\n"
                    f"{json.dumps(checks_to_wire(old), indent=1)}\n</old_plan>\n"
                    f"What changed:\n<change>\n{(e.amend_text or why).strip()}\n</change>")
        if again:
            return f"\n\nThe previous plan did not work. What failed:\n<failed>\n{why}\n</failed>\nPlan again."
        return ""

    def history(self, old: Any, again: bool) -> str:
        """The rounds before the last one (tl-bxk.13.6: replan.md holds the last round only), and what the tasks beside this one defer."""
        e = self.e
        out = ""
        hist = e.hand.rounds_text()
        if hist and (old or again):
            out += ("\n\nWhat the rounds on this task did so far (the writer's summary, then what was sent back). Do not "
                    f"plan a fix that already failed to hold:\n<rounds>\n{hist}</rounds>\n")
        return out + (self.digest() + e.routing.ledger().text() if old or again else "")

    def digest(self) -> str:
        """What a replan starts from beyond the old plan, the cause and the rounds: what the tree holds now, and a budget for looking."""
        e = self.e
        tree = e.checkout.tree_hash()
        stat = (e.git("diff", "--stat", e.checkout.base_sha(), tree) if tree else "").strip()
        return (f"\n\nThe tree now, against the task's base (git diff --stat):\n<tree>\n{stat or '(no file changed yet)'}\n</tree>\n"
                f"The old plan, the cause and the rounds above are your start: read at most {REPLAN_CALLS} files or run at most "
                f"{REPLAN_CALLS} commands before you answer.\n")

    def rules(self) -> list[str]:
        e = self.e
        rules = []
        wr = e.rules_text()
        if wr:
            rules.append("This repo's rules for workers (what runs where, known pitfalls of its tools); the checks you "
                         f"write must follow them:\n<worker_rules>\n{wr}\n</worker_rules>")
        notes = self.notes()
        if notes:
            rules.append("Facts about this factory and project that the plan must respect:\n" + notes)
        shared = e.shared_text()
        if shared:
            rules.append(shared.strip())
        if e.pictures.visual_cfg() and e.pictures.shot_methods():  # the classes mean "the engine renders": only with a shot table
            rules.append(VISUAL_PLAN % e.pictures.references_text())
            rules.append(VISUAL_STAGES % (", ".join(e.pictures.visual_cfg().include)[:300], e.pictures.shot_table()))
        rules.append("Proof files that a check reads or a reviewer looks at (screenshots, logs, probe output) go under "
                     f"{e.evidence_dir}: it is kept across runs, and nothing else under {e.task_dir} is.")
        gate, has = e.cfg.gate_text, bool(e.cfg.gate)
        rules.append("Checks run on the uncommitted working tree after each write. The engine runs the gate{} once, on "
                     "the rebased tree at land: never put {} in a stage's checks, and a criterion that names it is proven "
                     "by that land gate: write no case for it.".format((f" (`{gate}`)") if has else "", f"`{gate}`" if has else "it"))
        extra_gated = [(c, w) for c, w in lint.gate_only(e.cfg) if c != gate]
        if extra_gated:
            rules.append("These run only in the gate at land too, never in a check: " + "; ".join(
                f"`{c}`" + (f" ({w})" if w else "") for c, w in extra_gated) + ".")
        return rules

    def tail(self) -> str:
        """The owner's verify answer and the stages already accepted on this branch."""
        e, out = self.e, ""
        if e.verify_answer:
            out += (f"\n\nEvery stage was accepted, then the owner checked the work and answered:\n<answer>\n{e.verify_answer}\n</answer>\n"
                    "Plan only the work this answer asks for. If it asks for nothing more (it says the work is right), "
                    "return no stages: the engine then lands.")
        if e.done:
            out += ("\n\nThese stages are already accepted on this branch (reviewed, their work is in the tree): "
                    "do not plan them again; plan only what the task still needs.\n" + "".join(f"- {g}\n" for g in e.done))
        return out

    def build(self, old: Any, again: bool, why: str) -> str:
        e = self.e
        extra = self.change(old, again, why)
        e.old_plan, e.amend_text, e.amend_why = None, "", ""
        extra += self.history(old, again)
        rules = self.rules()
        extra += self.tail()
        where = e.where("plan")
        return PLAN_PROMPT.format(brief=e.briefs.text(), wt=e.wt) + extra + "\n\n" + "\n".join(rules) + ("\n\n" + where if where else "")
