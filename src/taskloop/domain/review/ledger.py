"""The ledger (tl-bxk.13.16.1): how the plan says each criterion is proved. A criterion deferred to a follow-up bead (leftover) or left to
the engine (engine_step) is not the reviewer's or the verifier's to judge: an item about it is routed here, never sent back."""
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from taskloop.domain.plan.matchers import word_set
from taskloop.domain.review.matchers import Wording

Entry = dict[str, str]


def deferred_items(plan: Mapping[str, Any] | None, leftovers: Sequence[Mapping[str, Any]]) -> list[tuple[str, str]]:
    """[(title, why)]: the follow-up work the plan and the reviews already set aside; the engine files each at land."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for lo in list((plan or {}).get("leftovers") or []) + list(leftovers):
        t = " ".join(str(lo.get("title") or "").split())
        if t and t not in seen:
            seen.add(t)
            out.append((t, " ".join(str(lo.get("why") or "").split())))
    return out


class Ledger:
    def __init__(self, plan: Mapping[str, Any] | None, leftovers: Sequence[Mapping[str, Any]] = ()) -> None:
        self.plan = plan or {}
        self.leftovers = list(leftovers)

    def deferred(self) -> list[tuple[str, str]]:
        return deferred_items(self.plan, self.leftovers)

    def entries(self) -> list[Entry]:
        """[{criterion, proved_by, via, text}]: what the plan defers (leftover) or leaves to the engine (engine_step)."""
        out: list[Entry] = []
        for c in self.plan.get("cases") or []:
            if c.get("proved_by") in ("leftover", "engine_step"):
                via = c.get("via") or ""
                out.append({"criterion": c["criterion"], "proved_by": c["proved_by"], "via": via, "text": f"{c['criterion']} {via}"})
        out += [{"criterion": t, "proved_by": "leftover", "via": t, "text": t} for t, _ in self.deferred()]
        return out

    def match(self, what: str) -> Entry | None:
        """The entry an item is about: most of the entry's words are the item's (3 at least). A claim about the code that merely shares
        words with a deferred item is not that item: unless the item is about filing, it must be a near-paraphrase (60% of both sides,
        4 words at least)."""
        mine = word_set(what)
        if len(mine) < 3:
            return None
        filing = Wording.about_filing(what)
        for e in self.entries():
            theirs = word_set(e["text"])
            shared = len(mine & theirs)
            if shared >= max(3, int(0.6 * len(theirs) + 0.99)) and (filing or (shared >= 4 and shared >= 0.6 * len(mine))):
                return e
        return None

    def route(self, what: str) -> str:
        e = self.match(what)
        return e["proved_by"] if e else ""

    def steps(self) -> list[Entry]:
        return [e for e in self.entries() if e["proved_by"] == "engine_step"]

    def missing_leftovers(self, known: Iterable[str] = ()) -> list[dict[str, str]]:
        """The leftovers a case deferred in the ledger forgot to list: one per case, so the work is filed. `known`: titles already
        deferred elsewhere (an earlier plan's)."""
        have = {" ".join(lo["title"].split()) for lo in self.plan.get("leftovers") or []} | {t for t, _ in self.deferred()} | set(known)
        out: list[dict[str, str]] = []
        for c in self.plan.get("cases") or []:
            if c.get("proved_by") != "leftover":
                continue
            via = " ".join((c.get("via") or "").split())
            if via and any(word_set(via) and len(word_set(via) & word_set(t)) >= 0.6 * len(word_set(via)) for t in have):
                continue
            title = (via or c["criterion"])[:120]
            out.append({"title": title, "why": "Deferred by the plan: " + c["criterion"]})
            have.add(title)
        return out

    def text(self) -> str:
        """The part of a review or verify prompt that says what is set aside and what the engine does itself."""
        items, steps, out = self.deferred(), self.steps(), ""
        if items:
            lines = "".join("- {}{}\n".format(t[:160], (": " + w[:160]) if w else "") for t, w in items[:10])
            out += ("\nAlready set aside (the plan or an earlier review put each in leftovers; the engine files each as a follow-up "
                    "bead at land, and nobody here can run bd). Never list one as unmet, as a finding or as unchecked, nor ask "
                    "the owner about it:\n" + lines)
        if steps:
            out += ("\nThe engine does these itself, after the stages (the plan's ledger). Never list one as unmet, as a "
                    "finding or as unchecked:\n"
                    + "".join("- {} ({})\n".format(e["criterion"][:160], e["via"][:60] or "engine step") for e in steps[:8]))
        return out
