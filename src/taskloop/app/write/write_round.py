"""WriteRound: the writer's half of a round. The prompt (the whole one, or the delta of a resumed writer), the call, what the answer
means (a question, an accepted requirement that decides it, shots a visual stage owes) and the cases it adds."""
from typing import Any

from taskloop.app.write.state import AGAIN, REPLAN, StageState
from taskloop.domain.asks import specs as askspecs
from taskloop.domain.prompts.anchors import anchors_text
from taskloop.domain.prompts.common import DECIDED_TEXT, LATER_CASES, UNCHECKED_TEXT
from taskloop.domain.prompts.write import SHOTS_FIX, write_prompt

CASES_TAIL = ("\nThe plan's acceptance cases run on the last stage. If you find a case they miss, add it to new_cases (the "
              "criterion it proves, the check, why); never remove or weaken one.")
CASES_NOW = ("\nThe plan's acceptance cases run on this last stage. If you find a case they miss, add it to new_cases (the criterion it "
             "proves, the check, why); never remove or weaken one.")


class WriteRound:
    def __init__(self, host: Any) -> None:
        self.e = host

    def run(self, s: StageState) -> str:
        """The round's write. -> "" when the checks go on, else AGAIN or REPLAN."""
        e = self.e
        boundary = s.n == 1 and s.i > 0 and not s.state  # the first write of a later stage
        fresh = e.hand.drop_big(boundary)
        prompt, delta = self.prompts(s, boundary, fresh)
        s.w, s.wfam = e.ai("write", f"{s.name} write {s.n}", prompt, delta=delta, resume_key="writer", write=s.n,
                           visual=e.stage_visual(s.st), round=s.rounds + 1, at=(s.sk, s.rounds, s.n), **s.meta)
        self.record(s, fresh)
        s.wrote_unchecked = s.w.get("unchecked") or []  # the review decides what is still unproven after the checks
        flow = self.question(s)
        if flow:
            return flow
        self.shots_contract(s, prompt)
        e.add_cases(s.w.get("new_cases") or [])
        if e.shot_methods() and e.stage_visual(s.st):
            e.render_stale = True  # a write after the last render: its pictures show an older tree
        back = e.look_step(s.st, s.w, s.name, s.last)
        if back:  # the look judge found defects: the writer fixes them before the full checks run once
            s.feedback = back
            return AGAIN
        return ""

    def prompts(self, s: StageState, boundary: bool, fresh: str) -> tuple[str, str | None]:
        """(the whole prompt, the delta a resumed writer gets instead or None)."""
        e, st = self.e, s.st
        stage_checks = e.stage_checks_text(st["checks"], skip=s.failed_cmds)
        where_text = e.where("write", [c.cmd for c in e.cfg.checks] + st["checks"], s.failed_cmds, listed=st["checks"])
        tail = CASES_TAIL + ("" if s.last else LATER_CASES) + UNCHECKED_TEXT + e.look_write(st)
        gate = f" (`{e.cfg.gate_text}`)" if e.cfg.gate else ""
        prompt = write_prompt(e.rules_text(), brief=e.briefs.text(), plan=e.plan_text(s.i), n=s.i + 1, goal=st["goal"],
                              files=", ".join(st["files"]), anchors=anchors_text(st), checks=stage_checks, feedback=s.feedback,
                              evidence=e.evidence_dir, where=where_text, gate=gate) + tail
        if fresh:
            prompt += e.hand.accepted_text() if boundary else e.hand.so_far_text()
        dtail = ""  # what a resumed writer still needs that its first prompt did not say for this stage
        if s.last and not e.writer.get("last_stage"):  # the acceptance cases run now: it has not been told
            dtail += CASES_NOW
        if e.unchecked:
            dtail += UNCHECKED_TEXT
        delta = None if fresh else e.hand.delta(s.i + 1, st["goal"], ", ".join(st["files"]), anchors_text(st), stage_checks,
                                                where_text, s.feedback, dtail + e.look_write(st))
        if delta:  # the writer may have edited its copy: the engine's brief goes back before it reads it again
            e.brief_file.write_text(e.briefs.text(), encoding="utf-8")
        else:  # a whole prompt (a first write, a fresh writer): what the tasks beside this one are doing (tl-bxk.13.8)
            prompt += e.shared_text() + e.deferred_text()
        return prompt, delta

    def record(self, s: StageState, fresh: str) -> None:
        """The writer's thread, its summary and its flakes, as the later rounds read them."""
        e, w = self.e, s.w
        e.writer_family = s.wfam
        e.writer["last_stage"] = s.last
        wr = e.sessions[-1] if e.sessions else {}
        e.write_rounds.append({"write": s.n, "round": s.rounds + 1, "node_id": wr.get("node_id"), "ref": wr.get("ref"),
                               "resumed": "yes" if wr.get("resume") else "no", "input_tokens": (wr.get("tokens") or {}).get("in"),
                               "turns": wr.get("turns"), "prompt_chars": wr.get("prompt_chars"), "context_k": wr.get("context_k"),
                               "fresh": fresh})
        e.writer_said += "\n" + w["summary"]
        e.add_flakes(w.get("flakes") or [])
        e.last_summary = w["summary"]

    def question(self, s: StageState) -> str:
        """A question an accepted requirement decides is a fix round, not an ask (lifesim-d5f.58); any other is the owner's."""
        e, w = self.e, s.w
        if not w["question"].strip():
            return ""
        if not w["decided"].strip():
            e.steps.outcome("asks", w["question"][:200])
            raise e.blocked_for("owner decision needed", "ASK_DECISION", spec=askspecs.open_question(w["question"], w.get("options")))
        s.rounds += 1
        e.stats["rounds"] += 1
        e.stuck_why = f"the writer asked what an accepted requirement decides: {w['decided']}"
        e.warn(f"{s.name}: {e.stuck_why[:300]}")
        if s.rounds >= int(e.cfg.max_rounds):
            (e.run_dir / "replan.md").write_text(e.stuck_why + "\n\nThe question: " + w["question"])
            e.steps.move("replan", "rounds_used", f"{s.rounds} rounds used: {e.stuck_why}")
            return REPLAN
        e.steps.move("write", "writer_decided", f"an accepted requirement decides it: {w['decided']}")
        s.feedback = DECIDED_TEXT % (w["question"], w["decided"])
        return AGAIN

    def shots_contract(self, s: StageState, prompt: str) -> None:
        """tl-tno: a visual write that named no shots and gave no reason is asked once more, with the table, before any check or review
        runs (the review's 'asked for no shots' finding burned lifesim-d5f.39's re-plan cap)."""
        e, w = self.e, s.w
        if not (e.look_ready(s.st) and not s.fix and not s.shots_fixed and not (w.get("shots") or [])
                and not (w.get("logic_only") or "").strip()):
            return
        s.shots_fixed = True
        tip = SHOTS_FIX % e.shot_table()
        e.steps.move("write", "shots_contract", "a visual write named no shots and gave no reason: asked once more")
        w2, wfam = e.ai("write", f"{s.name} shots contract", prompt + tip, delta=tip, resume_key="writer", write=s.n, visual=True,
                        round=s.rounds + 1, at=(s.sk, s.rounds, s.n + 500), **s.meta)
        e.stats["writes"] += 1
        s.wfam = e.writer_family = wfam
        e.writer["last_stage"] = s.last
        e.writer_said += "\n" + w2["summary"]
        e.last_summary = w2["summary"]
        if w2["question"].strip():
            e.steps.outcome("asks", w2["question"][:200])
            raise e.blocked_for("owner decision needed", "ASK_DECISION", spec=askspecs.open_question(w2["question"], w2.get("options")))
        both = {k: (w.get(k) or []) + (w2.get(k) or []) for k in ("new_cases", "unchecked", "bad_checks")}
        s.w = dict(w2, summary=w["summary"] + "\n" + w2["summary"], **both)
