"""Planner: the planner node. It asks for a plan (the prompt is PlanPrompt's, the send-back of a bad answer SendBack's), counts the run
against the re-plan cap, answers a question it may not ask with an Assumption, and turns the accepted answer into the run's plan.
The host (the engine) lends the run's state."""
import contextlib
import copy
from pathlib import Path
from typing import Any

from taskloop.app.plan import assume
from taskloop.app.plan.cap import ReplanCap
from taskloop.app.plan.prompt import PlanPrompt
from taskloop.app.plan.sendback import SendBack
from taskloop.contracts.answers import ASSUMPTION, IRREVERSIBLE
from taskloop.contracts.enums import AskClass
from taskloop.domain.asks import specs as askspecs
from taskloop.domain.matchers import clip
from taskloop.domain.plan.stored import stored
from taskloop.domain.prompts.common import DECIDED_TEXT
from taskloop.domain.prompts.plan import ASSUME_TEXT, PLAN_BRIEF_KB, PLAN_DECIDED_TEXT

REPLAN_TAIL = 12500  # characters of replan.md the planner reads


class Planner:
    def __init__(self, host: Any) -> None:
        self.e = host
        self.cap = ReplanCap(host)
        self.prompts = PlanPrompt(host)
        self.sendback = SendBack(host)

    # -- one planner answer
    def ask(self, prompt: str, step: str, title: str, mode: str = "plan") -> dict[str, Any]:
        """One planner answer, its checks validated before any write; the bad ones go back once."""
        e = self.e
        data, _ = e.ai("plan", title, prompt, step=step, mode=mode, at=(e.planned, 0, 0))
        if self.fits(data):  # checkpoint first: a SIGTERM during the send-back below resumes with this plan
            e.plan_data = copy.deepcopy(data)
            e.checkpoints.save(stage=0, rounds=0, n=0, feedback="", step="write")
        p = self.sendback.find(data)
        if p.any():  # asked once to rewrite them, like an invalid answer; not a counted re-plan
            why = self.sendback.text(p)
            e.steps.outcome("sent back", "it has no stages" if p.empty else
                            "its checks read the tracker, run gate-only commands or cannot run, or it leaves existing files unanchored")
            e.steps.move(step, "plan_sent_back", p.moved())
            data = self.sendback.rewrite(data, prompt, step, why)
            self.sendback.after_rewrite(data)
        self.sendback.warn_reruns(data)
        return data

    def fits(self, data: dict[str, Any]) -> bool:
        """A plan worth keeping through a stop: it has stages, asks nothing, and is not a split ask."""
        return bool(data["stages"] and not data["question"].strip() and (
            len(data["stages"]) <= int(self.e.cfg.max_stages) or self.cap.kept_whole()))

    def add_leftovers(self, data: dict[str, Any]) -> None:
        """The follow-up work the plan wants filed: filed at the close with the reviews' leftovers. Only a plan the run goes on with
        adds them, so a plan that asks the owner is not filed twice by the plan after the answer."""
        have = {lo["title"] for lo in self.e.leftovers}
        self.e.leftovers += [lo for lo in data["leftovers"] if lo["title"] not in have]

    # -- the run's plan
    def count(self, old: Any, again: bool, why: str) -> None:
        """The planner is about to run: against the cap, unless the owner's answer or edit of the bead caused it (tl-19i)."""
        e = self.e
        owner = (bool(old) and not again and (e.amend_why or "").startswith("bead changed: the owner answered")
                 and not (e.answered and e.answered.ask_class == AskClass.CAP_REACHED))  # a cap ask answered 'split' stays blocked
        if not owner and e.planned >= 1 + int(e.cfg.max_replans) + e.extra:
            raise self.cap.blocked()
        if not owner:
            e.planned += 1
        e.plan_log.append({"mode": "amend" if old else "plan", "counted": not owner,
                           "why": clip(e.amend_why or ("a re-plan: " + clip(why, 160) if again else "first plan"), 240)})
        if old and not again and not e.amend_text:
            e.amend_text = "The bead is the same as when the old plan was made."

    def plan(self, again: bool = False) -> dict[str, Any]:
        e = self.e
        old = e.old_plan or (e.plan_data if again and e.plan_data else None)
        e.amended = e.amended or bool(old)  # tl-bxk.10.24: work exists before this plan's first stage
        why = ""
        if again:
            with contextlib.suppress(OSError):
                why = (e.run_dir / "replan.md").read_text(encoding="utf-8")[-REPLAN_TAIL:]
        self.count(old, again, why)
        prompt = self.prompts.build(old, again, why)
        if len(prompt.encode("utf-8")) > PLAN_BRIEF_KB * 1024:
            e.warn(f"the planner's brief is {len(prompt.encode('utf-8')) / 1024:.0f} KB (over {PLAN_BRIEF_KB} KB)")
        step = "replan" if again else "plan"
        data = self.settle_question(self.ask(prompt, step, "amend" if old else "plan", "amend" if old else "plan"), prompt, step)
        return self.accept(data, again)

    def settle_question(self, data: dict[str, Any], prompt: str, step: str) -> dict[str, Any]:
        """A question an accepted requirement answers, or about a step that can be undone, is no ask: the planner plans again once."""
        e = self.e
        q = data["question"].strip()
        decided = data["decided"].strip() if q else ""
        if decided and not e.plan_decided:  # tl-bxk.10.3: no owner ask, the planner plans again
            e.plan_decided = True
            e.warn(f"the planner asked what an accepted requirement decides: {decided[:300]}")
            e.steps.outcome("sent back", "an accepted requirement decides its question")
            e.steps.move(step, "planner_decided", f"an accepted requirement decides it: {decided}")
            e.planned += 1  # a planner run like the others: the cap counts it
            e.plan_log.append({"mode": "plan", "why": "an accepted requirement decides its question"})
            data = self.ask(prompt + DECIDED_TEXT % (q, decided) + PLAN_DECIDED_TEXT, step, "plan to meet it", "checks_back")
        data = copy.deepcopy(data)  # the engine's own copy: cases are added to it as the task runs
        if data["question"].strip() and data.get("irreversible") not in IRREVERSIBLE:
            data = self.assume_question(data, prompt, step)
        return data

    def assume_question(self, data: dict[str, Any], prompt: str, step: str) -> dict[str, Any]:
        """tl-ntp: a question about anything that can be undone is an assumption, not an ask (82 item 1)."""
        e = self.e
        asked = data["question"].strip()
        data = assume.assume_question(data, e.log)
        if not data["stages"] and not data.get("leftovers") and not e.leftovers and not e.plan_assumed:
            e.plan_assumed = True
            e.warn(f"the planner asked a question about a step that can be undone, sent back: {asked[:300]}")
            e.steps.outcome("sent back", "its question is about a step that can be undone")
            e.steps.move(step, "planner_assumed", f"a question about a reversible step is an assumption: {asked[:200]}")
            e.planned += 1
            e.plan_log.append({"mode": "plan", "why": "its question is about a step that can be undone"})
            prior = data["assumptions"]
            data = copy.deepcopy(self.ask(prompt + ASSUME_TEXT % asked, step, "plan on assumptions", "checks_back"))
            data["assumptions"] = prior + data.get("assumptions", [])
            if data["question"].strip() and data.get("irreversible") not in IRREVERSIBLE:
                data = assume.assume_question(data, e.log)
        return data

    def accept(self, data: dict[str, Any], again: bool) -> dict[str, Any]:
        """The answer is the run's plan, or a stop: a question for the owner, a finished-work plan, a plan with no stages or too many."""
        e = self.e
        if self.fits(data):
            e.plan_data = data  # a SIGTERM from here on resumes with this plan (d5f.38 lost a finished 1.1M plan before its checkpoint)
            e.checkpoints.save(stage=0, rounds=0, n=0, feedback="", step="write")
        if e.verify_answer and not data["stages"] and not data["question"].strip():
            e.log.note("the planner finds the owner's answer asks for nothing more: landing")
            self.add_leftovers(data)
            return data
        e.plan_summary = data["summary"]
        for c in data.get("cases") or []:
            c.setdefault("by", "plan")
        e.plan_data = data
        if data["question"].strip():
            e.steps.outcome("asks", data["question"][:200])
            raise e.blocked_for("owner decision needed", "ASK_DECISION", spec=askspecs.open_question(data["question"], data.get("options")))
        n = len(data["stages"])
        e.steps.outcome(f"{n} stage{'' if n == 1 else 's'}", data["summary"][:200])
        assume.check_unresolved(data, Path(e.wt), e.log)
        if not data["stages"]:
            return self.finished_work(data, again)
        return self.finish(data)

    def finished_work(self, data: dict[str, Any], again: bool) -> dict[str, Any]:
        """tl-bxk.13.2: the work is done and only the filing is left: the engine files and closes. Never after a failed stage (a
        re-plan), and never over work no review accepted: that tree is not "done"."""
        e = self.e
        if (data["leftovers"] or e.leftovers) and not again and (e.done or not e.checkout.task_diff().strip()):
            e.log.note("the planner finds the work done and leaves only follow-up beads to file: closing")
            self.add_leftovers(data)
            e.plan_summary = data["summary"]
            stored(data)
            e.publish_plan()
            return data
        raise e.blocked_for("failed: the plan has no stages", "FAULT_PLAN")

    def finish(self, data: dict[str, Any]) -> dict[str, Any]:
        e = self.e
        big = int(e.cfg.max_stages)
        if len(data["stages"]) > big and not self.cap.kept_whole():
            why = f"ticket: the plan has {len(data['stages'])} stages (more than {big}): the bead may be too big for one task"
            raise e.blocked_for(why, "ASK_TICKET", spec=askspecs.too_big([st["goal"] for st in data["stages"]], big))
        for lo in e.routing.ledger_of(data).missing_leftovers(t for t, _ in e.routing.ledger().deferred()):
            data.setdefault("leftovers", []).append(lo)
            e.log.note("the ledger defers a criterion the leftovers did not list; listed: {}".format(lo["title"][:160]))
        self.add_leftovers(data)
        e.comment(self.summary(data))
        stored(data)
        e.publish_plan()
        e.briefs.export()
        e.checkpoints.save(stage=0, rounds=0, n=0, feedback="", step="write")
        return data

    @staticmethod
    def summary(data: dict[str, Any]) -> str:
        """The plan as the bead's comment says it."""
        lines = ["Plan (engine): " + data["summary"]]
        for n, s in enumerate(data["stages"]):
            hard = " (hard)" if s.get("hard") else ""
            lines.append(f"{n + 1}. {s['goal']}{hard} [files: {', '.join(s['files'])}] [checks: {'; '.join(s['checks'])}]")
        lines += [f"Risk: {r['what']} → {r['check']}" for r in data["risks"]]
        lines += [ASSUMPTION + a["text"] for a in data.get("assumptions") or []]
        return "\n".join(lines)
