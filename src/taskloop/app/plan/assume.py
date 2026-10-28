"""Assumptions: what the planner could not decide or find is recorded on the plan, never asked of the owner (tl-ntp)."""
from pathlib import Path
from typing import Any

from taskloop.contracts.answers import ASSUMPTION
from taskloop.domain.plan.matchers import word_set


def assume(data: dict[str, Any], text: str) -> None:
    """Record an Assumption on the plan (typed: step, text, reversible) and keep going."""
    data.setdefault("assumptions", []).append({"step": "plan", "text": " ".join(text.split())[:600], "reversible": True})


def assume_question(data: dict[str, Any], log: Any) -> dict[str, Any]:
    """A plan question about a step that can be undone becomes an Assumption; the plan goes on without the ask."""
    q = " ".join(data["question"].split())
    assume(data, "no owner answer; planned on the bead text and the repo. Open question: " + q)
    data["question"], data["options"], data["irreversible"] = "", list[Any](), ""
    log.note(ASSUMPTION + q[:300])
    return data


def check_unresolved(data: dict[str, Any], wt: Path, log: Any) -> None:
    """tl-bxk.13.16.3, tl-ntp: inputs the planner could not find. A file that is there after all drops out; one a case defers
    (proved_by leftover) is a follow-up; the rest is an Assumption in the plan: missing reference material is not a reason to
    ask the owner (tl-7y6.6.15 stopped on study files no worktree can read)."""
    cases: list[dict[str, Any]] = [c for c in data.get("cases") or [] if c.get("proved_by") == "leftover"]
    deferred = [word_set("{} {}".format(c["criterion"], c.get("via") or "")) for c in cases]
    deferred += [word_set(lo["title"] + " " + lo["why"]) for lo in data.get("leftovers") or []]
    gone: list[dict[str, Any]] = []
    open_: list[dict[str, Any]] = []
    for u in data.get("unresolved") or []:
        path = (u.get("path") or "").strip()
        if path and ".." not in path and (Path(path) if path.startswith("/") else wt / path).exists():
            continue  # it is there
        (gone if any(len(word_set(u["what"]) & d) >= 2 for d in deferred) else open_).append(u)
    if gone:
        log.note("inputs not found, their criteria deferred: {}".format("; ".join(u["what"][:100] for u in gone)))
    for u in open_:
        where = ", expected at " + u["path"] if u.get("path") else ""
        assume(data, f"{u['what']} ({u['kind']}{where}) is not available; planned from the bead text and the repo")
        log.note(ASSUMPTION + u["what"][:300])
