"""What a review's answer means for the stage: which findings block, which items are not the writer's to fix, which acceptance item has
no evidence. Pure functions over the answer's dicts (tests/review/test_findings.py)."""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from taskloop.domain.review.ledger import Ledger
from taskloop.domain.review.matchers import BdDemand

SEVERITY: Final = ("low", "medium", "high")
Finding = Mapping[str, Any]


def blocks(f: Finding) -> bool:
    """A finding sends the stage back only if its severity is high and it names a failure scenario (inputs, then the wrong
    output). Everything else is a note (tl-7y6.7.27)."""
    return SEVERITY.index(f["severity"]) >= SEVERITY.index("high") and bool(str(f.get("scenario") or "").strip())


def engine_finding(file: str, line: int, fix: str, scenario: str, axis: str = "standards", category: str = "engine") -> dict[str, Any]:
    """A finding the engine itself raises: high, with its scenario, so it blocks by the same rule as a reviewer's."""
    return {"file": file, "line": line, "severity": "high", "axis": axis, "category": category, "fix": fix,
            "scenario": scenario}


def note(f: Finding) -> dict[str, Any]:
    """The finding as a note: the same words, low severity (a warning that never blocks)."""
    return dict(f, severity="low")


def blocking(findings: Sequence[Finding]) -> list[Finding]:
    return [f for f in findings if blocks(f)]


def lows_after_first(findings: Sequence[Finding], round_no: int) -> list[Finding]:
    """Round 1 reports everything; a later round verifies the prior findings and looks for regressions: its lows are dropped."""
    return list(findings) if round_no <= 1 else [f for f in findings if f["severity"] != "low"]


def unmapped(items: Sequence[tuple[str, str]], criteria: Sequence[Finding]) -> list[dict[str, Any]]:
    """The spec axis: every acceptance item (id, text) is met (with evidence), unmet or the engine's, or it is a finding."""
    said = {str(c.get("item") or "").strip().upper() for c in criteria if c.get("status") != "met" or str(c.get("evidence") or "").strip()}
    return [engine_finding("", 0, f"say for acceptance item {i} whether it is met, with evidence: {text[:200]}",
                           f"acceptance item {i} has no evidence in the review, so nothing shows it is met",
                           axis="spec", category="unmapped")
            for i, text in items if i.upper() not in said]


def unmet_from(criteria: Sequence[Finding], unmet: Sequence[str]) -> list[str]:
    """The unmet list plus every criterion the reviewer marked unmet, once each."""
    extra = [f"{c['item']}: {c.get('evidence') or 'not met'}" for c in criteria if c.get("status") == "unmet"]
    return list(dict.fromkeys([*unmet, *extra]))


@dataclass(frozen=True)
class Routed:
    """A review's unmet items and findings after the engine took out what is not the writer's to fix."""

    unmet: list[str]
    findings: list[Finding]
    files: list[dict[str, str]] = field(default_factory=list)  # follow-up beads the engine files: {title, why}
    dropped: list[str] = field(default_factory=list)  # "goal is met" remarks and ledger-settled items, with why


def follow_up(text: str, why: str, category: str = "", file: str = "") -> dict[str, str]:
    """A follow-up bead to file; `category` and `file` are its key (domain/review/followups.py)."""
    title = "Follow-up: " + " ".join(text.split())[:100]
    lo = {"title": title, "why": f"{why}: {' '.join(text.split())[:500]}"}
    return dict(lo, category=category, file=file) if category else lo


def clauses(text: str) -> list[str]:
    return [c.strip() for c in text.split(";") if c.strip()]


def split_demands(text: str) -> tuple[str, list[tuple[str, str]]]:
    """(the part of `text` that is still the writer's, [(clause, 'bd'|'os')] the engine's): an item that mixes a real gap with a bd
    demand keeps the gap."""
    mine: list[str] = []
    theirs: list[tuple[str, str]] = []
    for c in clauses(text):
        kind = BdDemand.engine_only(c)
        if kind in ("bd", "os"):
            theirs.append((c, kind))
        else:
            mine.append(c)
    return "; ".join(mine), theirs


WHY: Final = {"bd": "A review asked for this and only the engine can run bd", "os": "A review asked for this on another operating system"}


def route(unmet: Sequence[str], findings: Sequence[Finding], ledger: Ledger) -> Routed:
    """Take out of the answer what the writer cannot or need not fix: a remark that the goal is met, an item the plan's ledger defers
    or gives to the engine (dropped), and a demand for a bd action or another operating system (filed as a follow-up bead)."""
    keep: list[str] = []
    files: list[dict[str, str]] = []
    dropped: list[str] = []
    for u in unmet:
        if BdDemand.is_goal_met(u):
            dropped.append(f"a remark, not a gap: {u[:80]}")
        elif ledger.route(u):
            dropped.append(f"the plan's ledger settles it: {u[:80]}")
        else:
            mine, theirs = split_demands(u)
            files += [follow_up(c, WHY[k], k) for c, k in theirs]
            if mine:
                keep.append(mine)
    kept: list[Finding] = []
    for f in findings:
        mine, theirs = split_demands(str(f.get("fix") or ""))
        files += [follow_up(c, WHY[k], str(f.get("category") or k), str(f.get("file") or "")) for c, k in theirs]
        if not theirs:
            kept.append(f)
        elif mine:
            kept.append(dict(f, fix=mine))
    return Routed(keep, kept, files, dropped)
