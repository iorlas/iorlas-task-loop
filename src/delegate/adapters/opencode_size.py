"""How big an OpenCode session's context was at its last assistant turn, from OpenCode's own session store (read only)."""

import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import quote


def db_path() -> str:
    """OpenCode's session store; OPENCODE_DB overrides it (tests)."""
    override = os.environ.get("OPENCODE_DB")
    if override:
        return override
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return str(Path(base) / "opencode" / "opencode.db")


def session_id(ref: object) -> str:
    """`ses_...` or `opencode:ses_...` -> the OpenCode session id, else ""."""
    text = str(ref or "")
    if text.startswith("opencode:"):
        text = text[9:]
    return text if text.startswith("ses_") and len(text) > 4 and text[4:].isascii() and text[4:].isalnum() else ""


def context_k(ref: object) -> float | None:
    """Input + cache read + cache write tokens of the session's last assistant message that reports any, in thousands; None when there is
    no such session, no store, or no usage."""
    sid, path = session_id(ref), db_path()
    if not sid or not os.path.isfile(path):
        return None
    try:
        con = sqlite3.connect(f"file:{quote(path)}?mode=ro", uri=True, timeout=1.0)
        try:
            rows = con.execute(
                "SELECT data FROM message WHERE session_id = ? ORDER BY time_created DESC, id DESC LIMIT 20", (sid,)
            ).fetchall()
        finally:
            con.close()
    except (sqlite3.Error, ValueError, OSError):
        return None
    for (data,) in rows:
        try:
            d = json.loads(data)
            if d.get("role") != "assistant":
                continue
            t = d["tokens"]
            n = int(t.get("input") or 0) + int((t.get("cache") or {}).get("read") or 0) + int((t.get("cache") or {}).get("write") or 0)
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
        if n:
            return round(n / 1000, 1)
    return None
