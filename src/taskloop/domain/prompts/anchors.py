"""A stage's anchors, as the writer reads them: where in the code the work starts, what to read first, the patterns to follow."""
from collections.abc import Mapping
from typing import Any

MAX_ANCHORS = 8


def anchor_line(a: Mapping[str, Any]) -> str:
    """`- path:lines symbol: why` (the parts the planner left empty are dropped)."""
    where = str(a.get("path") or "") + (":" + str(a["lines"]) if a.get("lines") else "")
    return "- " + " ".join(x for x in (where, str(a.get("symbol") or ""), "-- " + str(a["why"]) if a.get("why") else "") if x)


def anchors_text(stage: Mapping[str, Any]) -> str:
    """The block a stage's prompt carries above its checks; empty when the plan gave no anchors, read_first, patterns or constraints."""
    out: list[str] = []
    if stage.get("anchors"):
        out.append("Anchors (start here; the planner already read these):\n" + "\n".join(anchor_line(a) for a in stage["anchors"]))
    if stage.get("read_first"):
        out.append("Read first: " + ", ".join(stage["read_first"]))
    if stage.get("patterns"):
        out.append("Follow these patterns:\n" + "\n".join(f"- {p}" for p in stage["patterns"]))
    if stage.get("constraints"):
        out.append("Constraints: " + str(stage["constraints"]))
    return ("\n".join(out) + "\n") if out else ""


def unanchored(stage: Mapping[str, Any], exists: Mapping[str, bool]) -> list[str]:
    """The files of the stage that exist in the tree (`exists`) and that no anchor names."""
    named = {str(a.get("path") or "") for a in stage.get("anchors") or []}
    return [f for f in stage.get("files") or [] if exists.get(f) and f not in named]
