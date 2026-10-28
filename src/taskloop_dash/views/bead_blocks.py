"""A run's blocks as the Roadmap's stage rail and the bead panel draw them."""

from typing import Any


def trail(blocks: list[dict[str, Any]], full: bool = False) -> list[dict[str, Any]]:
    """The blocks of a run reduced to what the page shows; `full` adds the seconds' tokens and the arrow into each (the bead panel)."""
    out = []
    for x in blocks:
        row = {"kind": x["kind"], "label": x["label"], "stage": x.get("stage_index"), "stages": x.get("stage_count"),
               "secs": x.get("secs"), "status": (x.get("result") or {}).get("status"), "text": (x.get("result") or {}).get("text")}
        if full:
            row.update(tokens=x.get("tokens"), arrow=(x.get("arrow") or {}).get("text"))
        out.append(row)
    return out
