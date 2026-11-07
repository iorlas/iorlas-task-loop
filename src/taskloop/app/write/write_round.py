"""WriteRound: the writer's half of a round. The prompt (the whole one, or the delta of a resumed writer), the call, what the answer
means (a question, an accepted requirement that decides it, shots a visual stage owes) and the cases it adds."""

from tlgate.domain import planref
from tlkernel import askspecs

from taskloop.app.write import show_check
from taskloop.app.write.host import WriteHost
from taskloop.app.write.prepare import PREPARED, Prepare
from taskloop.app.write.prompts import SHOTS_FIX, write_prompt
from taskloop.app.write.state import AGAIN, REPLAN, RoundResult, StageState, carrying
from taskloop.domain.prompts.anchors import anchors_text
from taskloop.domain.prompts.common import DECIDED_TEXT, LATER_CASES, UNCHECKED_TEXT

CASES_TAIL = ("\nThe plan's acceptance cases run on the last stage. If you find a case they miss, add it to new_cases (the "
              "criterion it proves, the check, why); never remove or weaken one.")
CASES_NOW = ("\nThe plan's acceptance cases run on this last stage. If you find a case they miss, add it to new_cases (the criterion it "
             "proves, the check, why); never remove or weaken one.")


class WriteRound:
    def __init__(self, host: WriteHost) -> None:
        self.e = host

    def run(self, s: StageState, *, look: bool = True) -> RoundResult:
        """The round's write. -> a result whose flow is "" when the checks go on, else AGAIN or REPLAN."""
        out = RoundResult()
        with carrying(out):
            out.flow = self.go(s, out, look)
        return out

    def go(self, s: StageState, out: RoundResult, look: bool) -> str:
        e = self.e
        boundary = s.n == 1 and s.i > 0 and not s.state  # the first write of a later stage
        prompt, delta = self.prompts(s, boundary)
        got = e.ai("write", f"{s.name} write {s.n}", prompt, delta=delta, boundary=boundary, resume_key="writer", write=s.n,
                           visual=e.pictures.stage_visual(s.st), round=s.rounds + 1,
                           at=(s.sk, s.rounds, s.n + (10000 if s.prepare_retried else 0)), **s.meta)
        s.w, s.wfam = got.data, got.family
        self.record(s, out)
        if Prepare(e).retry(s, str(s.w.get("bad_checks", [])) + str(s.w.get("problem", ""))):
            return PREPARED
        s.wrote_unchecked = s.w.get("unchecked") or []  # the review decides what is still unproven after the checks
        flow = self.question(s, out)
        if flow:
            return flow
        self.shots_contract(s, prompt, out)
        e.cases.add_cases(s.w.get("new_cases") or [])
        if e.pictures.shot_methods() and e.pictures.stage_visual(s.st):
            e.pictures.mark_stale()  # a write after the last render: its pictures show an older tree
        back = self.show_contract(s)
        if back:  # a show item lacks its artifacts: the writer registers them before any check runs
            return back
        back = e.judge.look_step(s.st, s.w, s.name, s.last, family=s.wfam) if look else ""
        if back:  # the look judge found defects: the writer fixes them before the full checks run once
            s.feedback = back
            return AGAIN
        return ""

    def prompts(self, s: StageState, boundary: bool) -> tuple[str, str | None]:
        """(the whole prompt, the delta a resumed writer gets instead or None)."""
        e, st = self.e, s.st
        listed = planref.commands(st["checks"], e.cfg)
        stage_checks = e.briefing.stage_checks_text(listed, skip=s.failed_cmds)
        where_text = e.briefing.where("write", [c.cmd for c in e.cfg.stage_checks] + listed, s.failed_cmds, listed=listed)
        tail = CASES_TAIL + ("" if s.last else LATER_CASES) + UNCHECKED_TEXT + e.judge.look_write(st)
        gate = f" (`{e.cfg.gate_text}`)" if e.cfg.gate_checks else ""
        prompt = write_prompt(e.cases.rules_text(), brief=e.briefs.text(), plan=e.cases.plan_text(s.i), n=s.i + 1, goal=st["goal"],
                              files=", ".join(st["files"]), anchors=anchors_text(st), checks=stage_checks, feedback=s.feedback,
                              evidence=e.evidence_dir, where=where_text, gate=gate) + tail
        dtail = ""  # what a resumed writer still needs that its first prompt did not say for this stage
        if s.last and not e.writer.last_stage:  # the acceptance cases run now: it has not been told
            dtail += CASES_NOW
        if e.review.unchecked:
            dtail += UNCHECKED_TEXT
        delta = e.hand.delta(s.i + 1, st["goal"], ", ".join(st["files"]), anchors_text(st), stage_checks,
                                                where_text, s.feedback, dtail + e.judge.look_write(st))
        if delta is not None:
            prompt += e.hand.accepted_text() if boundary else e.hand.so_far_text()
        if delta is not None:  # the writer may have edited its copy: the engine's brief goes back before it reads it again
            e.brief_file.write_text(e.briefs.text(), encoding="utf-8")
        else:  # a whole prompt (a first write, a fresh writer): what the tasks beside this one are doing (tl-bxk.13.8)
            prompt += e.shared.shared_text() + e.routing.ledger().text()
        return prompt, delta

    def record(self, s: StageState, out: RoundResult) -> None:
        """The writer's thread, its summary and its flakes, as the later rounds read them."""
        e, w = self.e, s.w
        out.family, out.last_stage = s.wfam, s.last
        wr = e.sessions[-1] if e.sessions else {}
        out.write_rows += ({"write": s.n, "round": s.rounds + 1, "node_id": wr.get("node_id"), "ref": wr.get("ref"),
                            "resumed": "yes" if wr.get("resume") else "no", "input_tokens": (wr.get("tokens") or {}).get("in"),
                            "turns": wr.get("turns"), "prompt_chars": wr.get("prompt_chars"), "context_k": wr.get("context_k")},)
        e.shared.add_flakes(w.get("flakes") or [])
        out.summary = w["summary"]

    def question(self, s: StageState, out: RoundResult) -> str:
        """A question an accepted requirement decides is a fix round, not an ask; any other is the owner's."""
        e, w = self.e, s.w
        if not w["question"].strip():
            return ""
        if not w["decided"].strip():
            e.steps.outcome("asks", w["question"][:200])
            spec = askspecs.open_question(w["question"], w.get("options"), w.get("owner_cause"))
            raise e.blocked_for("owner decision needed", "ASK_DECISION", spec=spec)
        s.rounds += 1
        out.rounds += 1
        stuck = out.stuck_why = f"the writer asked what an accepted requirement decides: {w['decided']}"
        e.warn(f"{s.name}: {stuck[:300]}")
        if s.rounds >= e.cfg.max_rounds:
            (e.run_dir / "replan.md").write_text(stuck + "\n\nThe question: " + w["question"])
            e.steps.move("replan", "rounds_used", f"{s.rounds} rounds used: {stuck}")
            return REPLAN
        e.steps.move("write", "writer_decided", f"an accepted requirement decides it: {w['decided']}")
        s.feedback = DECIDED_TEXT % (w["question"], w["decided"])
        return AGAIN

    def show_contract(self, s: StageState) -> str:
        """tl-jvpm.25: a show item whose artifacts are not in the store for this write is a retry reason, once (AGAIN, no counted round);
        a second miss is a warning and the run goes on. It never parks."""
        e = self.e
        if not s.last or s.fix:
            return ""
        miss = show_check.missing((e.plan_data or {}).get("cases") or [], e.home.artifact_store(),
                                  show_check.slot_of(e.ports.repo.key(), e.bead, e.run_id, s.n))
        if not miss:
            return ""
        if s.show_fixed:
            e.warn(f"{s.name}: show items still unmet after the retry: {'; '.join(miss)[:300]}")
            return ""
        s.show_fixed = True
        e.steps.move("write", "show_missing", f"{len(miss)} show item(s) lack their artifacts: the writer is asked once more")
        s.feedback = show_check.SHOW_BACK % "\n".join("- " + m for m in miss)
        return AGAIN

    def shots_contract(self, s: StageState, prompt: str, out: RoundResult) -> None:
        """tl-tno: a visual write that named no shots and gave no reason is asked once more, with the table, before any check or review
        runs (the review's 'asked for no shots' finding burned a bead's re-plan cap)."""
        e, w = self.e, s.w
        if not (e.pictures.look_ready(s.st) and not s.fix and not s.shots_fixed and not (w.get("shots") or [])
                and not (w.get("logic_only") or "").strip()):
            return
        s.shots_fixed = True
        tip = SHOTS_FIX % e.pictures.shot_table()
        e.steps.move("write", "shots_contract", "a visual write named no shots and gave no reason: asked once more")
        got = e.ai("write", f"{s.name} shots contract", prompt + tip, delta=tip, resume_key="writer", write=s.n, visual=True,
                        round=s.rounds + 1, at=(s.sk, s.rounds, s.n + 500), **s.meta)
        w2 = got.data
        out.writes += 1
        s.wfam = out.family = got.family
        out.last_stage = s.last
        out.summary = w2["summary"]
        if w2["question"].strip():
            e.steps.outcome("asks", w2["question"][:200])
            spec = askspecs.open_question(w2["question"], w2.get("options"), w2.get("owner_cause"))
            raise e.blocked_for("owner decision needed", "ASK_DECISION", spec=spec)
        both = {k: (w.get(k) or []) + (w2.get(k) or []) for k in ("new_cases", "unchecked", "bad_checks")}
        s.w = dict(w2, summary=w["summary"] + "\n" + w2["summary"], **both)
