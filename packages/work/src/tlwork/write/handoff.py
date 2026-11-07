"""Handoff: what a writer that did not see the earlier rounds is told. The record
(`handoff`: the rounds so far, the low findings a review already noted) lives on the host and in the checkpoint; this class reads and
extends it and renders it into the writer's and the reviewer's prompts."""
import contextlib
import hashlib
from collections.abc import Sequence
from typing import Any

from tlkernel import rundocs
from tlkernel.gitport import Git
from tlkernel.run import HandoffMirror, Round

from tlwork.review.findings import blocks
from tlwork.write.host import HandoffHost
from tlwork.write.prompts import DONE_SO_FAR, STAGES_DONE, WRITE_RESUME_PROMPT

HANDOFF_CAP = 1500  # characters of round history one prompt carries (tl-bxk.13.6)


class Handoff:
    def __init__(self, host: HandoffHost, git: Git) -> None:
        self.e = host
        self.git = git

    def seen_now(self) -> list[str]:
        """What a writer session holds of the task once it has answered: the brief's and the plan's hash."""
        return [hashlib.sha1(t.encode("utf-8")).hexdigest() for t in (self.e.briefs.text(), self.e.cases.plan_text())]

    def so_far_text(self) -> str:
        """What a fresh writer is told its predecessor did: the diff --stat of the stage so far, and its last summary."""
        tree = self.e.checkout.tree_hash()
        stat = self.git.diff(self.e.wt, self.e.stage_tree or self.e.checkout.base_sha(), tree, stat=True) if tree else ""
        return DONE_SO_FAR % ((stat or "(no file changed yet)").strip(), (self.e.write.last_summary or "(none)").strip(),
                              self.rounds_text(last=4) or "(none)\n")

    def accepted_text(self) -> str:
        """What a fresh writer starting a later stage is told: the accepted stages and their diff from the task's base."""
        tree = self.e.checkout.tree_hash()
        stat = self.git.diff(self.e.wt, self.e.checkout.base_sha(), tree, stat=True) if tree else ""
        goals = "".join(f"- {g}\n" for g in self.e.done) or "(none)\n"
        return STAGES_DONE % (goals, (stat or "(no file changed yet)").strip(), self.rounds_text(last=4) or "(none)\n")

    def delta(self, n: int, goal: str, files: str, anchors: str, checks: str, where: str, feedback: str, tail: str) -> str | None:
        """The prompt of a resumed writer: what changed since its session last saw the brief and the plan. None when the brief
        changed (the owner edited it, an answer came in): that session gets the whole prompt again."""
        seen = self.e.writer.seen
        if not seen or seen[0] != self.seen_now()[0]:
            return None
        same = seen[1] == self.seen_now()[1]
        plan = "The plan is unchanged." if same else f"The plan changed:\n<plan>\n{self.e.cases.plan_text(n - 1)}\n</plan>"
        return WRITE_RESUME_PROMPT.format(brief=self.e.brief_file, plan=plan, n=n, goal=goal, files=files, anchors=anchors, checks=checks,
                                          where=where, feedback=feedback) + tail

    def seen_lows_text(self) -> str:
        lows = self.e.handoff.seen_lows
        if not lows:
            return ""
        return ("\nLow findings earlier reviews of this task already noted (do not list one again unless the code under it "
                "changed):\n" + "".join(f"- {x}\n" for x in lows[-10:]))

    def rounds_text(self, last: int = 6, each: int = 300, cap: int = HANDOFF_CAP) -> str:
        """The newest rounds first kept, oldest dropped when the text would pass `cap` characters."""
        out: list[str] = []
        size = 0
        for r in reversed(self.e.handoff.rounds[-last:]):
            line = f"- {r.stage}, round {r.round} ({r.kind})"
            if r.writer:
                line += f"; the writer said: {r.writer[:each]}"
            if r.open:
                line += "; sent back: " + " | ".join(r.open)
            line = line[:each + 400]
            if out and size + len(line) > cap:
                break
            out.append(line)
            size += len(line) + 1
        return ("\n".join(reversed(out)) + "\n") if out else ""

    def note_round(self, name: str, rnd: int, kind: str, writer: str = "", open_items: Sequence[str] = ()) -> None:
        h = self.e.handoff
        h.rounds.append(Round(stage=name, round=rnd, kind=kind, writer=" ".join(writer.split())[:300],
                              open=[" ".join(x.split())[:200] for x in list(open_items)[:6]]))
        h.rounds = h.rounds[-12:]
        self.save()

    def note_lows(self, findings: Sequence[dict[str, Any]]) -> None:
        for f in findings:
            if not blocks(f):
                x = ("{}:{} {}".format(f["file"], f["line"], " ".join(str(f["fix"]).split())))[:160]
                if x not in self.e.handoff.seen_lows:
                    self.e.handoff.seen_lows.append(x)
        self.e.handoff.seen_lows = self.e.handoff.seen_lows[-20:]
        self.save()

    def save(self) -> None:
        with contextlib.suppress(OSError):
            h = self.e.handoff
            rundocs.handoff(self.e.home, self.e.run_id).write(HandoffMirror(
                rounds=list(h.rounds), seen_lows=list(h.seen_lows),
                deferred=[{"what": t, "why": w} for t, w in self.e.routing.ledger().deferred()], filed=list(self.e.filed)))
