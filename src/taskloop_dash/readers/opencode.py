"""OpenCode's session store, read only: an xai-lane worker's transcript is a session id into its SQLite file, never a text file."""

import os
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import quote

PREFIX = "opencode:"


def db_path(home: Path) -> str:
    """OpenCode's session store; OPENCODE_DB overrides it (tests)."""
    env = os.environ.get("OPENCODE_DB")
    if env:
        return env
    base = os.environ.get("XDG_DATA_HOME") or str(home / ".local" / "share")
    return str(Path(base) / "opencode" / "opencode.db")


def session_id(ref: object) -> str:
    """`ses_...` or `opencode:ses_...` -> the OpenCode session id, else ""."""
    text = str(ref or "")
    text = text.removeprefix(PREFIX)
    return text if text.startswith("ses_") and len(text) > 4 and text[4:].isascii() and text[4:].isalnum() else ""


class OpenCode:
    def __init__(self, home: Path) -> None:
        self.home = home

    def rows(self, sql: str, args: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        """Read-only query of the session, message and part tables: a list of rows, [] when the DB is missing, locked or another shape."""
        path = db_path(self.home)
        if not os.path.isfile(path):
            return []
        try:
            con = sqlite3.connect("file:%s?mode=ro" % quote(path), uri=True, timeout=1.0)
            try:
                return con.execute(sql, args).fetchall()
            finally:
                con.close()
        except (sqlite3.Error, ValueError, OSError):
            return []

    def has(self, sid: str) -> bool:
        return bool(sid) and bool(self.rows("SELECT 1 FROM session WHERE id = ?", (sid,)))

    def updated(self, sid: str) -> float | None:
        """Seconds since the epoch of the session's last change (OpenCode stores ms), or None."""
        rows = self.rows("SELECT MAX(t) FROM (SELECT MAX(time_updated) t FROM message WHERE session_id = ? "
                         "UNION ALL SELECT MAX(time_updated) FROM part WHERE session_id = ?)", (sid, sid))
        return rows[0][0] / 1000.0 if rows and rows[0][0] else None

    def reference(self, ref: object) -> str:
        """`opencode:ses_...` for a session the DB knows, else ""."""
        sid = session_id(ref)
        return PREFIX + sid if self.has(sid) else ""
