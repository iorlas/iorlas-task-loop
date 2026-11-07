"""The look judge and what the pictures say to the writer, the reviewer and the verifier: a visual write's render rounds, the judge's
findings, a look item's verdict."""
import shutil
from pathlib import Path
from typing import Any

from tlkernel import workswitch as switch
from tlkernel.checkpoint import Defect
from tlkernel.plancheck import StageData
from tlkernel.stagefacts import RunFacts

from taskloop.adapters import looks
from taskloop.app.look.host import LookHost, LookPorts
from taskloop.app.look.prompts import LOOK_FEEDBACK, LOOK_WRITE_TABLE
from taskloop.app.look.state import LookState
from taskloop.domain.work.matchers import Wording
from taskloop.domain.work.skip import SkipKind

NOT_VISUAL = "\nlook: empty when nothing here is visual.\n"


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


class Judge:
    def __init__(self, facts: RunFacts, ports: LookPorts, state: LookState, hand: LookHost) -> None:
        self.facts, self.ports, self.state, self.hand = facts, ports, state, hand

    def judge_shots(self, names: list[str], rnd: int, summary: str, last: bool = True,
                    family: str | None = None) -> tuple[list[Defect], str]:
        """The look judge's findings: a fresh call from another family, in a folder with only the shrunk pictures, the
        references and the 'before' pictures. -> (defects [{item, where, why}], its summary)."""
        hand, facts, ports = self.hand, self.facts, self.ports
        if switch.mode(facts.cfg.review, ports.budget.labels) == "off":  # no reviewer-role call: the owner sees the skip on the bead
            ports.steps.begin("look", f"round {rnd}: look judge skipped ({SkipKind.REVIEW_OFF})")
            ports.steps.outcome("skipped", SkipKind.REVIEW_OFF)
            ports.comment("Look (engine): the look judge was skipped because review is off; the pictures are not judged")
            return [], "(look judge skipped: review is off)"
        base = facts.run_dir / "looks" / f"r{rnd}"
        befores: list[str] = []
        for i, (f, m) in enumerate(ports.pictures.before_pictures(), 1):
            shutil.copy2(f, base / f"before-{i}-{m.name}")
            befores.append(f"before-{i}-{m.name}")
        # the plan's look items are for the last stage (like the cases); an earlier stage is judged on the general checks only
        prompt = looks.judge_prompt(ports.cases.cases_of("look-objective") if last else [], names, befores, summary)
        try:
            d = ports.ai("look", f"round {rnd}: {plural(len(names), 'picture')}", prompt,
                         writer_family=hand.writer_family if family is None else family, cwd=str(base), round=rnd,
                         at=(hand.at_stage, rnd, 0)).data
        except hand.Blocked as b:
            return self.unjudged(b, rnd)
        note = "[same family as the writer: no other lane was free] " if hand.last_flag == "same_family" else ""
        found = [Defect(item=f.get("item", ""), why=f.get("why", ""), where=f.get("where", ""))
                 for f in d["findings"] if f["verdict"] == "defect"]
        return found, note + d["summary"]

    def unjudged(self, b: Any, rnd: int) -> tuple[list[Defect], str]:
        """No lane for the judge: the pictures go unjudged to the owner-look bead; a look judge never parks the bead."""
        hand, ports, state = self.hand, self.ports, self.state
        st = getattr(b, "stop", None)
        if not b.why.startswith("paused: no lane") or (st is not None and st.permanence == "needs_owner" and st.reason != "no_lane"):
            raise b  # the network (the step resumes), a crash, a login or credit pause: not this node's to swallow
        hand.retry_after = 0.0  # the run goes on: discard the pause retry time
        ports.steps.outcome("skipped", "no lane")
        ports.warn(f"the look judge had no lane, the pictures are not judged: {b.why[:200]}")
        state.unjudged[f"look judge, round {rnd}"] = "no lane: " + b.why[:160]
        return [], "(not judged: no lane for the look judge)"

    def look_step(self, st: StageData, w: Any, name: str, last: bool = True, *, checks: bool = True,
                  family: str | None = None) -> str:
        """After a visual write: the cheap checks, the shots the writer asked for, the look judge (`family`: the writer's, not yet handed
        on). -> the feedback that sends the writer back with the defects (text and picture paths), or "" to go on to the full checks.
        At most engine.look_rounds render rounds per stage; a defect that comes back is a leftover with the pictures, not another write."""
        facts, ports, state = self.facts, self.ports, self.state
        if not ports.pictures.look_ready(st) or state.done >= facts.cfg.look_rounds or facts.dry:
            return ""
        reqs = [r for r in w.get("shots") or [] if isinstance(r, dict)]
        if not reqs:
            return ""
        if checks and ports.stage_checks.stoppable(StageData(files=st["files"], checks=[]), name, groups=("static",)).failed:
            return ""  # the full checks show it to the writer; no render over a red static check
        state.done += 1
        rnd = state.done
        names, errs = ports.pictures.render_shots(reqs, rnd)
        defects = [Defect(item="render", why=msg) for msg in errs]
        summary = ""
        if names:
            found, summary = self.judge_shots(names, rnd, w.get("summary", ""), last, family)
            defects += found
        if summary:
            state.notes = [summary.strip()]
        ports.pictures.persist_look()
        fresh = defects
        out_of_rounds = state.done >= facts.cfg.look_rounds
        if out_of_rounds:  # the rounds are capped: what is left is a follow-up, not another write
            for d in defects:
                self.look_leftover(d, names)
        if not fresh or out_of_rounds:
            return ""
        ports.steps.move("write", "look_defects", f"{plural(len(fresh), 'defect')} from the look judge, round {rnd}")
        lines = [f"- {d.item}{(' (' + d.where + ')') if d.where else ''}: {d.why}" for d in fresh]
        return LOOK_FEEDBACK % ("\n".join(lines), "\n".join(f"{facts.evidence_dir}/{n}" for n in names))

    def look_leftover(self, d: Defect, names: list[str]) -> None:
        hand, facts, ports = self.hand, self.facts, self.ports
        title = f"Look: {d.why}"[:120]
        if ports.leftover_sink.add_titled({"title": title, "why": (
                f"The look judge found this on {hand.bead_title or facts.bead} ({d.item}); it came back after a fix or the render rounds "
                f"were used up. Pictures: {', '.join(names) or 'none'}. Defect: {d.where} {d.why}")}):
            ports.checkpoints.keep_pending("look")
            ports.log.note(f"look defect filed as a follow-up: {d.why[:200]}")

    def look_write(self, st: StageData) -> str:
        facts, ports = self.facts, self.ports
        if not ports.pictures.stage_visual(st):
            return ""
        if ports.pictures.shot_methods():
            return LOOK_WRITE_TABLE % (looks.MAX_REQUESTS, looks.table_text(ports.pictures.shot_methods()))
        return ("\nThis stage changes how something looks (it touches visual paths). Save a screenshot of every changed "
                f"screen or state in {facts.evidence_dir}/ with a descriptive name (screen-state.png), and name them in the summary. "
                "If the change is clearly logic-only and nothing on screen differs, put a one-line reason in logic_only; "
                "otherwise leave logic_only empty.")

    def look_review(self, st: StageData, w: Any, fix: bool = False) -> str:
        facts, ports, state = self.facts, self.ports, self.state
        if fix or not ports.pictures.stage_visual(st):
            return ""
        shots = ports.pictures.shots()
        text = "\nThis stage changes how something looks. "
        if ports.pictures.shot_methods():  # tl-bxk.13.15: the engine rendered the pictures and a look judge read them
            seen = ", ".join(f"{facts.evidence_dir}/{x}" for x in shots) or "none were made"
            notes = (": " + " ".join(state.notes)[:900]) if state.notes else ""
            text += (f"The engine rendered the pictures ({seen}) and a look judge, a fresh call from another family, read them{notes}. "
                     "Judge from its words against the task's done-when; open a picture only if you doubt them. A mismatch "
                     "is a finding; put your judgement in one paragraph in look.")
        elif shots:
            text += (f"Screenshots the writer saved: {', '.join(f'{facts.evidence_dir}/{s}' for s in shots)}. Open every one and judge it "
                     "against the task's done-when and any linked decision or reference image, honestly: put what you see, and whether "
                     "it matches, in one paragraph in look; a mismatch is a finding.")
        else:
            text += "The writer saved no screenshots. "
        if (w.get("logic_only") or "").strip():
            text += (f"\nThe writer says this change is logic-only: \"{w['logic_only'].strip()}\". Accept it only if nothing on screen "
                     "can differ; if not, give a medium finding.")
        return text + NOT_VISUAL

    def look_judged(self, review: Any, st: StageData, w: Any, fix: bool) -> None:
        """No screenshot and no logic-only reason on a visual stage is a warning; the reviewer's look is kept."""
        facts, ports, state = self.facts, self.ports, self.state
        if fix or not ports.pictures.stage_visual(st):
            return
        if (review.get("look") or "").strip() and ports.pictures.shots():
            state.notes = [review["look"].strip()]  # the last round's judgement only
        if not ports.pictures.shots() and not (w.get("logic_only") or "").strip():  # a warning, never a send-back (tl-7y6.7.24)
            what = ("asked for no shots (name the shot methods to render in `shots`, or say in logic_only why nothing on screen differs)"
                    if ports.pictures.shot_methods() else f"saved no screenshot of any changed screen or state in {facts.evidence_dir}/")
            ports.warn(f"this stage changes visual paths but {what}")

    def look_verify(self, gaps: Any) -> str:
        facts, ports = self.facts, self.ports
        looked = [n for n, u in enumerate(gaps, 1) if self.is_look(u)]
        if not looked:
            return ""
        seen = ", ".join(f"{facts.evidence_dir}/{s}" for s in ports.pictures.shots()) or "none saved"
        return (f"\nItems {', '.join(map(str, looked))} are about how it looks. They are never open: judge them from the screenshots "
                f"({seen}), against the task's done-when and any linked decision or reference image. Open each one. settled when it "
                "matches (evidence names the screenshot and what you saw); wrong when it does not (why says what differs).\n")

    def look_verdict(self, u: Any, v: str, a: Any, why: str) -> tuple[str, Any, str]:
        """A look item is settled only on evidence that names a screenshot file. Otherwise it goes back to the writer
        once, noted as not judged (a later verify that settles it clears the note); the second time the run moves on.
        The owner-look bead carries the note. The owner is never asked."""
        facts, ports, state = self.facts, self.ports, self.state
        shots, ev = ports.pictures.shots(), a.get("evidence") or ""
        if v == "settled" and any(sh in ev or Path(sh).name in ev for sh in shots):
            state.unjudged.pop(u["what"], None)
            return v, a, why
        if v == "wrong":
            return v, a, why
        if v == "settled":
            why = "settled, but its evidence names no screenshot file"
        reason = why or ("no screenshot saved" if not shots else "no verdict")
        state.unjudged[u["what"]] = f"agent could not judge: {reason}"
        if u["what"] not in state.retried:
            state.retried.add(u["what"])
            if shots:
                named = ", ".join(shots)
                say = f"judge it from the screenshots ({named}): open each one and name the file you judged. "
                return "wrong", a, (say + (why or "")).strip()
            return "wrong", a, f"no screenshot to judge the look from: save them in {facts.evidence_dir}/"
        ports.warn("a look item is still not judged; the owner is not asked, it waits in the owner-look bead")
        return "settled", dict(a, evidence="agent could not judge: " + reason), reason

    def is_look(self, u: Any) -> bool:
        return bool(self.ports.pictures.visual_cfg()) and Wording.is_look(u["what"])
