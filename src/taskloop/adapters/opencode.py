"""OpenCode's session store, read only (session, message and part tables; never the credential ones), and where a transcript is."""
import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote

from taskloop.contracts.env import Env


def opencode_db(env: Env) -> str:
    """OpenCode's session store (macOS/Linux); OPENCODE_DB overrides it (tests)."""
    override = env.get("OPENCODE_DB")
    if override:
        return override
    base = env.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return str(Path(base) / "opencode" / "opencode.db")


def opencode_id(ref: object) -> str:
    """`ses_...` or `opencode:ses_...` -> the OpenCode session id, else ""."""
    text = str(ref or "")
    if text.startswith("opencode:"):
        text = text[9:]
    return text if re.match(r"^ses_[A-Za-z0-9]+$", text) else ""


def opencode_rows(env: Env, sql: str, args: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    """A query of OpenCode's DB: a list of rows, [] when the DB is missing, locked or another shape. Never writes."""
    path = opencode_db(env)
    if not os.path.isfile(path):
        return []
    try:
        con = sqlite3.connect(f"file:{quote(path)}?mode=ro", uri=True, timeout=1.0)
        try:
            return con.execute(sql, args).fetchall()
        finally:
            con.close()
    except (sqlite3.Error, ValueError, OSError):
        return []


def opencode_has(env: Env, sid: str) -> bool:
    return bool(sid) and bool(opencode_rows(env, "SELECT 1 FROM session WHERE id = ?", (sid,)))


def opencode_updated(env: Env, sid: str) -> float | None:
    """Seconds since the epoch of the session's last change (OpenCode stores ms), or None."""
    rows = opencode_rows(env, "SELECT MAX(t) FROM (SELECT MAX(time_updated) t FROM message WHERE session_id = ? "
                         "UNION ALL SELECT MAX(time_updated) FROM part WHERE session_id = ?)", (sid, sid))
    return rows[0][0] / 1000.0 if rows and rows[0][0] else None


def opencode_context(env: Env, sid: str) -> int | None:
    """Input + cache read + cache write tokens of the session's last assistant message that reports any, or None."""
    for (data,) in opencode_rows(env, "SELECT data FROM message WHERE session_id = ? ORDER BY time_created DESC, id DESC LIMIT 20", (sid,)):
        try:
            d = json.loads(data)
            if d.get("role") != "assistant":
                continue
            t = d["tokens"]
            n = int(t.get("input") or 0) + int((t.get("cache") or {}).get("read") or 0) + int((t.get("cache") or {}).get("write") or 0)
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
        if n:
            return n
    return None


def transcript_of(env: Env, family: str, ref: str) -> str:
    """Where a worker session's transcript lives on this machine: Codex rollouts and Claude projects, by session id; for
    family xai (OpenCode) the session's `opencode:ses_...` reference into its DB."""
    if not ref:
        return ""
    if family == "xai" or opencode_id(ref):
        sid = opencode_id(ref)
        return "opencode:" + sid if opencode_has(env, sid) else ""
    home = Path.home()
    if family == "openai":
        root, pattern = home / ".codex" / "sessions", f"*{ref}*.jsonl"
    else:
        root, pattern = home / ".claude" / "projects", f"*/{ref}.jsonl"
    hits = sorted(root.glob("**/" + pattern)) if root.is_dir() else []
    return str(hits[-1]) if hits else ""
