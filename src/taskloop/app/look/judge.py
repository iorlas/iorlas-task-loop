"""The look judge and what the pictures say to the writer, the reviewer and the verifier: a visual write's render rounds, the judge's
findings, a look item's verdict."""
import shutil
from pathlib import Path
from typing import Any

from taskloop.adapters import looks
from taskloop.domain.look.matchers import image_names
from taskloop.domain.prompts.write import LOOK_FEEDBACK, LOOK_WRITE_TABLE
from taskloop.domain.review.matchers import Wording

NOT_VISUAL = "\nlook: empty when nothing here is visual.\n"


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


class Judge:
    def __init__(self, host: Any) -> None:
        self.e = host

    def judge_shots(self, names: list[str], rnd: int, summary: str, last: bool = True) -> tuple[list[dict[str, str]], str]:
        """The look judge's findings: a fresh call from another family, in a folder with only the shrunk pictures, the
        references and the 'before' pictures. -> (defects [{item, where, why}], its summary)."""
        e = self.e
        base = e.run_dir / "looks" / f"r{rnd}"
        shown: list[str] = []
        for r in [r for r in image_names(e.briefs.text()) if (Path(e.wt) / r).is_file()]:
            shutil.copy2(Path(e.wt) / r, base / f"ref-{Path(r).name}")
            shown.append(f"ref-{Path(r).name}")
        pairs: list[tuple[str, str]] = []
        for n in names:
            b = e.pictures.before_shot(n)
            if b:
                shutil.copy2(b, base / f"before-{n}")
                pairs.append((n, f"before-{n}"))
        # the plan's look items are for the last stage (like the cases); an earlier stage is judged on the general checks only
        prompt = looks.judge_prompt(e.cases.cases_of("look-objective") if last else [], names, shown, pairs, summary)
        try:
            d, _ = e.ai("look", f"round {rnd}: {plural(len(names), 'picture')}", prompt,
                        writer_family=e.writer_family, cwd=str(base), round=rnd, at=(e.at_stage, rnd, 0))
        except e.Blocked as b:
            return self.unjudged(b, rnd)
        note = "[same family as the writer: no other lane was free] " if e.last_flag == "same_family" else ""
        return [f for f in d["findings"] if f["verdict"] == "defect"], note + d["summary"]

    def unjudged(self, b: Any, rnd: int) -> tuple[list[dict[str, str]], str]:
        """No lane for the judge: the pictures go unjudged to the owner-look bead; a look judge never parks the bead."""
        e = self.e
        st = getattr(b, "stop", None)
        if not b.why.startswith("paused: no lane") or (st is not None and st.permanence == "needs_owner" and st.reason != "no_lane"):
            raise b  # the network (the step resumes), a crash, a login or credit pause: not this node's to swallow
        e.retry_after, e.pause_role, e.pause_lane = 0.0, "", ""  # the run goes on: _ai had noted a pause for the loop
        e.steps.outcome("skipped", "no lane")
        e.warn(f"the look judge had no lane, the pictures are not judged: {b.why[:200]}")
        e.look_unjudged[f"look judge, round {rnd}"] = "no lane: " + b.why[:160]
        return [], "(not judged: no lane for the look judge)"

    def look_step(self, st: Any, w: Any, name: str, last: bool = True) -> str:
        """After a visual write: the cheap checks, the shots the writer asked for, the look judge. -> the feedback that sends the
        writer back with the defects (text and picture paths), or "" to go on to the full checks. At most engine.look_rounds
        render rounds per stage; a defect that comes back is a leftover with the pictures, not another write."""
        e = self.e
        if not e.pictures.look_ready(st) or e.look_done >= int(e.cfg.look_rounds) or e.dry:
            return ""
        reqs = [r for r in w.get("shots") or [] if isinstance(r, dict)]
        if not reqs:
            return ""
        if e.stoppable_checks(dict(st, checks=[]), name, groups=("static",)).failed:
            return ""  # the full checks show it to the writer; no render over a red static check
        e.look_done += 1
        rnd = e.look_done
        names, errs = e.pictures.render_shots(reqs, rnd)
        defects = [{"item": "render", "where": "", "why": msg} for msg in errs]
        summary = ""
        if names:
            found, summary = self.judge_shots(names, rnd, w.get("summary", ""), last)
            defects += found
        if summary:
            e.look_notes = [summary.strip()]
        e.pictures.persist_look()
        prev, e.look_prev = e.look_prev, defects
        again = [d for d in defects if any(looks.same_defect(d["why"] + " " + d["where"], p["why"] + " " + p["where"]) for p in prev)]
        fresh = [d for d in defects if d not in again]
        out_of_rounds = e.look_done >= int(e.cfg.look_rounds)
        for d in again + (fresh if out_of_rounds else []):  # tl-bxk.13.15.5: the same defect twice is not the writer's to fix again
            self.look_leftover(d, names)
        if not fresh or out_of_rounds:
            return ""
        e.steps.move("write", "look_defects", f"{plural(len(fresh), 'defect')} from the look judge, round {rnd}")
        lines = [f"- {d['item']}{(' (' + d['where'] + ')') if d['where'] else ''}: {d['why']}" for d in fresh]
        return LOOK_FEEDBACK % ("\n".join(lines), "\n".join(f"{e.evidence_dir}/{n}" for n in names))

    def look_leftover(self, d: dict[str, str], names: list[str]) -> None:
        e = self.e
        title = f"Look: {d['why']}"[:120]
        if title not in {lo["title"] for lo in e.leftovers}:
            e.leftovers.append({"title": title, "why": (
                f"The look judge found this on {e.bead_title or e.bead} ({d['item']}); it came back after a fix or the render rounds were "
                f"used up. Pictures: {', '.join(names) or 'none'}. Defect: {d['where']} {d['why']}")})
            e.log.note(f"look defect filed as a follow-up: {d['why'][:200]}")

    def look_write(self, st: Any) -> str:
        e = self.e
        if not e.pictures.stage_visual(st):
            return ""
        if e.pictures.shot_methods():
            return LOOK_WRITE_TABLE % (looks.MAX_REQUESTS, looks.table_text(e.pictures.shot_methods()))
        return ("\nThis stage changes how something looks (it touches visual paths). Save a screenshot of every changed "
                f"screen or state in {e.evidence_dir}/ with a descriptive name (screen-state.png), and name them in the summary. If the "
                "change is clearly logic-only and nothing on screen differs, put a one-line reason in logic_only; "
                "otherwise leave logic_only empty.")

    def look_review(self, st: Any, w: Any, fix: bool = False) -> str:
        e = self.e
        if fix or not e.pictures.stage_visual(st):
            return ""
        shots = e.pictures.shots()
        text = "\nThis stage changes how something looks. "
        if e.pictures.shot_methods():  # tl-bxk.13.15: the engine rendered the pictures and a look judge read them
            seen = ", ".join(f"{e.evidence_dir}/{x}" for x in shots) or "none were made"
            notes = (": " + " ".join(e.look_notes)[:900]) if e.look_notes else ""
            text += (f"The engine rendered the pictures ({seen}) and a look judge, a fresh call from another family, read them{notes}. "
                     "Judge from its words against the task's done-when; open a picture only if you doubt them. A mismatch "
                     "is a finding; put your judgement in one paragraph in look.")
        elif shots:
            text += (f"Screenshots the writer saved: {', '.join(f'{e.evidence_dir}/{s}' for s in shots)}. Open every one and judge it "
                     "against the task's done-when and any linked decision or reference image, honestly: put what you see, and whether "
                     "it matches, in one paragraph in look; a mismatch is a finding.")
        else:
            text += "The writer saved no screenshots. "
        if (w.get("logic_only") or "").strip():
            text += (f"\nThe writer says this change is logic-only: \"{w['logic_only'].strip()}\". Accept it only if nothing on screen "
                     "can differ; if not, give a medium finding.")
        return text + NOT_VISUAL

    def look_judged(self, review: Any, st: Any, w: Any, fix: bool) -> None:
        """No screenshot and no logic-only reason on a visual stage is a warning; the reviewer's look is kept."""
        e = self.e
        if fix or not e.pictures.stage_visual(st):
            return
        if (review.get("look") or "").strip() and e.pictures.shots():
            e.look_notes = [review["look"].strip()]  # the last round's judgement only
        if not e.pictures.shots() and not (w.get("logic_only") or "").strip():  # a warning, never a send-back (tl-7y6.7.24)
            what = ("asked for no shots (name the shot methods to render in `shots`, or say in logic_only why nothing on screen differs)"
                    if e.pictures.shot_methods() else f"saved no screenshot of any changed screen or state in {e.evidence_dir}/")
            e.warn(f"this stage changes visual paths but {what}")

    def look_verify(self, gaps: Any) -> str:
        e = self.e
        looked = [n for n, u in enumerate(gaps, 1) if self.is_look(u)]
        if not looked:
            return ""
        seen = ", ".join(f"{e.evidence_dir}/{s}" for s in e.pictures.shots()) or "none saved"
        return (f"\nItems {', '.join(map(str, looked))} are about how it looks. They are never open: judge them from the screenshots "
                f"({seen}), against the task's done-when and any linked decision or reference image. Open each one. settled when it "
                "matches (evidence names the screenshot and what you saw); wrong when it does not (why says what differs).\n")

    def look_verdict(self, u: Any, v: str, a: Any, why: str) -> tuple[str, Any, str]:
        """A look item is settled only on evidence that names a screenshot file. Otherwise it goes back to the writer
        once, noted as not judged (a later verify that settles it clears the note); the second time the run moves on.
        The owner-look bead carries the note. The owner is never asked."""
        e = self.e
        shots, ev = e.pictures.shots(), a.get("evidence") or ""
        if v == "settled" and any(sh in ev or Path(sh).name in ev for sh in shots):
            e.look_unjudged.pop(u["what"], None)
            return v, a, why
        if v == "wrong":
            return v, a, why
        if v == "settled":
            why = "settled, but its evidence names no screenshot file"
        reason = why or ("no screenshot saved" if not shots else "no verdict")
        e.look_unjudged[u["what"]] = f"agent could not judge: {reason}"
        if u["what"] not in e.look_retried:
            e.look_retried.add(u["what"])
            if shots:
                named = ", ".join(shots)
                say = f"judge it from the screenshots ({named}): open each one and name the file you judged. "
                return "wrong", a, (say + (why or "")).strip()
            return "wrong", a, f"no screenshot to judge the look from: save them in {e.evidence_dir}/"
        e.warn("a look item is still not judged; the owner is not asked, it waits in the owner-look bead")
        return "settled", dict(a, evidence="agent could not judge: " + reason), reason

    def is_look(self, u: Any) -> bool:
        return bool(self.e.pictures.visual_cfg()) and Wording.is_look(u["what"])
