"""Handoff: what a writer that did not see the earlier rounds is told, and when a writer session is dropped for a new one. The record
(`handoff`: the rounds so far, the low findings a review already noted) lives on the host and in the checkpoint; this class reads and
extends it and renders it into the writer's and the reviewer's prompts."""
import contextlib
import hashlib
import json
from collections.abc import Sequence
from typing import Any

from taskloop.contracts.config import FRESH_ABOVE_K
from taskloop.domain.prompts.write import DONE_SO_FAR, STAGES_DONE, WRITE_RESUME_PROMPT

HANDOFF_CAP = 1500  # characters of round history one prompt carries (tl-bxk.13.6)


class Handoff:
    def __init__(self, host: Any) -> None:
        self.e = host

    def seen_now(self) -> list[str]:
        """What a writer session holds of the task once it has answered: the brief's and the plan's hash."""
        return [hashlib.sha1(t.encode("utf-8")).hexdigest() for t in (self.e.brief_text(), self.e.plan_text())]

    def fresh_above_k(self, family: str) -> float:
        v = self.e.cfg.write_fresh_above_k
        if isinstance(v, dict):
            key = "codex" if family == "openai" else family
            v = v.get(key, FRESH_ABOVE_K.get(key, 0))
        return float(v or 0)

    def drop_big(self, boundary: bool = False) -> str:
        """tl-bxk.10.29: -> why a new writer starts, or "". The session's last context is above write_fresh_above_k for its
        family: it is not resumed (every later turn would carry it all); the next write is a new session. At a stage
        boundary the lower write_fresh_stage_k applies (tl-bxk.13.7): lifesim-yxbb.9 carried 276K into stage 2 (11.7M tokens)."""
        ref, ctx = self.e.writer.get("delegate"), self.e.writer.get("ctx")
        limit = self.fresh_above_k(self.e.writer_family or "")
        if boundary and limit:  # write_fresh_above_k 0 means never: the stage limit does not override it
            b = float(self.e.cfg.write_fresh_stage_k or 0)
            limit = min(limit, b) if b else limit
        if not ref or not ctx or not limit or ctx <= limit:
            return ""
        self.e.writer.pop("delegate")
        why = f"session at {ctx:d}k"
        self.e.log.note(f"fresh writer: {why} (above {limit:g}k for {self.e.writer_family})")
        return why

    def so_far_text(self) -> str:
        """What a fresh writer is told its predecessor did: the diff --stat of the stage so far, and its last summary."""
        tree = self.e.tree_hash()
        stat = self.e.git("diff", "--stat", self.e.stage_tree or self.e.base_sha(), tree) if tree else ""
        return DONE_SO_FAR % ((stat or "(no file changed yet)").strip(), (self.e.last_summary or "(none)").strip(),
                              self.rounds_text(last=4) or "(none)\n")

    def accepted_text(self) -> str:
        """What a fresh writer starting a later stage is told: the accepted stages and their diff from the task's base."""
        tree = self.e.tree_hash()
        stat = self.e.git("diff", "--stat", self.e.base_sha(), tree) if tree else ""
        goals = "".join(f"- {g}\n" for g in self.e.done) or "(none)\n"
        return STAGES_DONE % (goals, (stat or "(no file changed yet)").strip(), self.rounds_text(last=4) or "(none)\n")

    def delta(self, n: int, goal: str, files: str, checks: str, where: str, feedback: str, tail: str) -> str | None:
        """The prompt of a resumed writer: what changed since its session last saw the brief and the plan. None when the brief
        changed (the owner edited it, an answer came in): that session gets the whole prompt again."""
        seen = self.e.writer.get("seen")
        if not seen or seen[0] != self.seen_now()[0]:
            return None
        plan = "The plan is unchanged." if seen[1] == self.seen_now()[1] else f"The plan changed:\n<plan>\n{self.e.plan_text()}\n</plan>"
        return WRITE_RESUME_PROMPT.format(brief=self.e.brief_file, plan=plan, n=n, goal=goal, files=files, checks=checks,
                                          where=where, feedback=feedback) + tail

    def seen_lows_text(self) -> str:
        lows = self.e.handoff["seen_lows"]
        if not lows:
            return ""
        return ("\nLow findings earlier reviews of this task already noted (do not list one again unless the code under it "
                "changed):\n" + "".join(f"- {x}\n" for x in lows[-10:]))

    def rounds_text(self, last: int = 6, each: int = 300, cap: int = HANDOFF_CAP) -> str:
        """The newest rounds first kept, oldest dropped when the text would pass `cap` characters."""
        out: list[str] = []
        size = 0
        for r in reversed(self.e.handoff["rounds"][-last:]):
            line = "- {}, round {} ({})".format(r["stage"], r["round"], r["kind"])
            if r.get("writer"):
                line += "; the writer said: {}".format(r["writer"][:each])
            if r.get("open"):
                line += "; sent back: " + " | ".join(r["open"])
            line = line[:each + 400]
            if out and size + len(line) > cap:
                break
            out.append(line)
            size += len(line) + 1
        return ("\n".join(reversed(out)) + "\n") if out else ""

    def note_round(self, name: str, rnd: int, kind: str, writer: str = "", open_items: Sequence[str] = ()) -> None:
        self.e.handoff["rounds"].append({"stage": name, "round": rnd, "kind": kind, "writer": " ".join(str(writer).split())[:300],
                                       "open": [" ".join(str(x).split())[:200] for x in list(open_items)[:6]]})
        self.e.handoff["rounds"] = self.e.handoff["rounds"][-12:]
        self.save()

    def note_lows(self, findings: Sequence[dict[str, Any]]) -> None:
        for f in findings:
            if f["severity"] == "low":
                x = ("{}:{} {}".format(f["file"], f["line"], " ".join(str(f["fix"]).split())))[:160]
                if x not in self.e.handoff["seen_lows"]:
                    self.e.handoff["seen_lows"].append(x)
        self.e.handoff["seen_lows"] = self.e.handoff["seen_lows"][-20:]
        self.save()

    def save(self) -> None:
        with contextlib.suppress(OSError):
            (self.e.run_dir / "handoff.json").write_text(json.dumps(dict(
                self.e.handoff, deferred=[{"what": t, "why": w} for t, w in self.e.deferred_items()],
                filed=self.e.filed), indent=1))
