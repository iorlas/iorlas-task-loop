"""The owner-look gallery's items: taste items the engine filed into owner-look beads (metadata `looks`), with their before and
after pictures. Pure: the answers and the bd calls are api/looks.py.

An item: {id "<source bead>#<n>", look_bead, bead, title, note, shots [{path, role before|after, label}], status
open|good|redo, redo_bead, answer_note, answered}. A look bead from before `looks` existed has no metadata: its
description's "- path" lines become one item per "## <bead>: <title>" section, every picture an "after"."""

import calendar
import time
from pathlib import Path
from typing import Any, Final

LABEL = "owner-look"
PICTURES: Final = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
Item = dict[str, Any]


def clean(e: Item, look_bead: str) -> Item:
    shots = [{"path": str(s.get("path") or "").replace("\\", "/"), "role": "before" if s.get("role") == "before" else "after",
              "label": str(s.get("label") or "")} for s in e.get("shots") or [] if isinstance(s, dict) and s.get("path")]
    return {"id": str(e.get("id") or ""), "look_bead": look_bead, "bead": str(e.get("bead") or ""),
            "title": str(e.get("title") or ""), "note": str(e.get("note") or ""), "shots": shots,
            "status": e.get("status") if e.get("status") in ("good", "redo") else "open",
            "redo_bead": str(e.get("redo_bead") or ""), "answer_note": str(e.get("answer_note") or ""),
            "answered": e.get("answered") or 0}


def picture_path(line: str) -> str:
    """The path in a '- path.png' description line, '' for any other line."""
    text = line.rstrip()
    path = text[2:] if text.startswith("- ") else ""
    return path if len(path) > 4 and not any(c.isspace() for c in path) and Path(path).suffix.lower() in PICTURES else ""


def sections(desc: str) -> list[str]:
    """The '## ' sections of a description, each starting with its heading."""
    first, *more = ("\n\n" + desc.strip()).split("\n\n## ")
    return [("## " + m) for m in more] if more else ([desc.strip()] if first.strip() else [])


def parse_description(desc: object, look_bead: str) -> list[Item]:
    """Old look beads: '## bead: title' sections; the '- path' lines of a section are its pictures (all 'after')."""
    items = []
    for sec in sections(str(desc or "")):
        heading = sec.split("\n", 1)[0]
        bead, sep, title = heading[3:].partition(": ") if heading.startswith("## ") else ("", "", "")
        if not sep or not bead or ":" in bead:
            continue
        paths = [p for p in (picture_path(ln) for ln in sec.splitlines()) if p]
        if paths:
            items.append(clean({"id": "%s#0" % bead, "bead": bead, "title": title,
                                "shots": [{"path": p, "role": "after", "label": Path(p).stem} for p in paths]}, look_bead))
    return items


def items_of(look_bead: str, shown: Item) -> list[Item]:
    """Items of one owner-look bead as `bd show` gave it; metadata `looks` wins, the description is the fallback."""
    looks = (shown.get("metadata") or {}).get("looks")
    if isinstance(looks, list):
        return [clean(e, look_bead) for e in looks if isinstance(e, dict) and e.get("id")]
    return parse_description(shown.get("description"), look_bead)


def stored(look_bead: str, shown: Item) -> list[Item]:
    """The items to write back: metadata `looks` as is, or the parsed description made into metadata the first time."""
    looks = (shown.get("metadata") or {}).get("looks")
    if isinstance(looks, list):
        return [e for e in looks if isinstance(e, dict)]
    return [{k: v for k, v in i.items() if k != "look_bead"} for i in parse_description(shown.get("description"), look_bead)]


def epoch(s: object) -> float:
    """An ISO time from bd (UTC when it ends in Z or +00:00) as epoch seconds; 0 when it is not one."""
    s = str(s or "")
    try:
        t = time.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return 0
    return calendar.timegm(t) if s[19:].startswith(("Z", "+00", ".")) or not s[19:] else time.mktime(t)


def summary(items: list[Item]) -> dict[str, int]:
    return {k: sum(1 for i in items if i["status"] == k) for k in ("open", "good", "redo")}
