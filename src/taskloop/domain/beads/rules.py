"""Bead lint (tl-7y6.7.1): one rule table over a bead's structure, never over its prose. A bead is loop work when it has a goal
(description), acceptance criteria, a short Touches list, is not a container (an epic with children) and is not a decision or a
spike without an Output file; plus the tl-f52 rule (matchers.py): its text cites nothing outside the repo. Pure functions."""
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from taskloop.contracts.bead import Bead
from taskloop.domain.beads import matchers

MAX_TOUCHES: Final = 8
NEEDS_AC: Final = "needs-ac"  # the label the loop puts on a bead it refused
AUTO: Final = "auto"  # the label that says a bead may be taken unattended


@dataclass(frozen=True)
class Fail:
    rule: str  # R1, R2, ...
    why: str  # one line

    def line(self) -> str:
        return f"{self.rule}: {self.why}"


Children = Callable[[], bool]  # does this bead have child beads (asked only for an epic)
Rule = Callable[[Bead, str, Children], str]  # (bead, repo root, children) -> why it fails, "" when it passes


def r1(b: Bead, root: str, kids: Children) -> str:
    return "" if b.description.strip() else "no description (goal)"


def r2(b: Bead, root: str, kids: Children) -> str:
    return "" if b.acceptance_criteria.strip() or matchers.has_ac_heading(b.description) else "no acceptance criteria"


def r3(b: Bead, root: str, kids: Children) -> str:
    n = len(matchers.touches(b.description))
    return f"Touches names {n} paths (at most {MAX_TOUCHES})" if n > MAX_TOUCHES else ""


def r5(b: Bead, root: str, kids: Children) -> str:
    return "an epic with children is a container, not work" if b.issue_type == "epic" and kids() else ""


def r6(b: Bead, root: str, kids: Children) -> str:
    if b.issue_type == "decision":
        return "a decision bead is not loop work"
    if b.issue_type == "spike" and not matchers.has_output(b.description):
        return "a spike bead names no `Output:` file"
    return ""


def r_facts(b: Bead, root: str, kids: Children) -> str:
    return matchers.why(b, root)


RULES: tuple[tuple[str, Rule], ...] = (("R1", r1), ("R2", r2), ("R3", r3), ("R5", r5), ("R6", r6), ("FACTS", r_facts))


def failures(bead: Bead, root: str = "", children: Children = lambda: False) -> list[Fail]:
    return [Fail(rid, why) for rid, rule in RULES if (why := rule(bead, root, children))]


def why(bead: Bead, root: str = "", children: Children = lambda: False) -> str:
    """The pick-step skip reason: every failed rule in one line, "" for a bead that passes."""
    return "; ".join(f.line() for f in failures(bead, root, children))
