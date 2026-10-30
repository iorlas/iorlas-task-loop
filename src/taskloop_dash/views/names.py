"""Names and times the task view prints: run names, lanes by family, models, clock times. No regex: the engine's own text is
split with str methods."""

import mimetypes
import os
import time
from typing import Final

from taskloop.contracts.ids import BeadId, RunId

FAMILY: Final = {"openai": "Codex", "claude": "Claude", "xai": "Grok"}


def run_name(path: str) -> str:
    base = os.path.basename(path)
    return base[: -len(".jsonl")] if base.endswith(".jsonl") else base


def bead_of(run: str) -> BeadId | None:
    """'tl-1-20261021-072411' -> 'tl-1'; None when the name does not end in a date and a time."""
    rid = RunId.of(run)
    return rid.bead if rid else None


IMAGES: Final = ("image/png", "image/jpeg", "image/gif", "image/webp")


def kind_of(name: str) -> str:
    """'image' (shown inline), 'pdf' (opens in a tab) or 'file' (download only: HTML is never run as a page)."""
    ctype = mimetypes.guess_type(name)[0] or ""
    return "image" if ctype in IMAGES else "pdf" if ctype == "application/pdf" else "file"


def is_run_name(text: object) -> bool:
    return isinstance(text, str) and RunId.of(text) is not None


def num(ident: object) -> int:
    """The number in a step id ('n4' -> 4); 0 for none."""
    digits = str(ident or "").lstrip("nc")
    return int(digits) if digits.isdigit() else 0


def lane_name(lane: str | None = "", family: str | None = "") -> str:
    """Codex, Claude or Grok, from delegate's family or lane name."""
    if family and family in FAMILY:
        return FAMILY[family]
    up = (lane or "").upper()
    if "GROK" in up or up.endswith("XAI") or "_XAI" in up:
        return "Grok"
    if "OPENAI" in up or "CODEX" in up:
        return "Codex"
    return "Claude" if "CLAUDE" in up or "ANTHROPIC" in up else ""


def nice_model(model: object) -> str:
    if not model:
        return ""
    m = str(model)
    for name in ("opus", "sonnet", "haiku", "fable"):
        if m.lower().startswith(name):
            rest = m[len(name) :].strip("-_ ")
            return name.capitalize() + ((" " + rest.replace("-", ".")) if rest else "")
    return m


def hhmm(t: float | None) -> str:
    return time.strftime("%H:%M", time.localtime(t)) if t else ""


def when(t: float | None) -> str:
    """HH:MM today, else the weekday too."""
    if not t:
        return ""
    same = time.strftime("%Y%m%d", time.localtime(t)) == time.strftime("%Y%m%d")
    return hhmm(t) if same else time.strftime("%a %H:%M", time.localtime(t))
