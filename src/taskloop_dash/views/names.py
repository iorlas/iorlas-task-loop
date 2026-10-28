"""Names and times the task view prints: run names, lanes by family, models, clock times. No regex: the engine's own text is
split with str methods."""

import os
import time
from typing import Final

FAMILY: Final = {"openai": "Codex", "claude": "Claude", "xai": "Grok"}


def run_name(path: str) -> str:
    base = os.path.basename(path)
    return base[: -len(".jsonl")] if base.endswith(".jsonl") else base


def bead_of(run: str) -> str:
    """'tl-1-20261021-072411' -> 'tl-1'; '' when the name does not end in a date and a time."""
    head, _, rest = run.rpartition("-")
    bead, _, day = head.rpartition("-")
    ok = len(day) == 8 and day.isdigit() and len(rest) == 6 and rest.isdigit()
    return bead if ok and bead else ""


def is_bead_id(text: object) -> bool:
    """A letter or digit first, then letters, digits, '_', '.' and '-': never something bd would read as an option."""
    s = text if isinstance(text, str) else ""
    return bool(s) and s[0].isalnum() and s.isascii() and all(c.isalnum() or c in "_.-" for c in s)


def is_run_name(text: object) -> bool:
    s = text if isinstance(text, str) else ""
    return is_bead_id(s) and s[0] != "-" and bool(bead_of(s))


def num(ident: object) -> int:
    """The number in a step id ('n4' -> 4); 0 for none."""
    digits = str(ident or "").lstrip("nc")
    return int(digits) if digits.isdigit() else 0


def lane_name(lane: str = "", family: str = "") -> str:
    """Codex, Claude or Grok, from delegate's family or lane name."""
    if family in FAMILY:
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
