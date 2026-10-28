"""The SessionStart and PreCompact hooks: index the session, keep the `tl` shim pointing at this install, write the handoff before a
compaction and give it back after one."""
import json
import time
from pathlib import Path

from taskloop.app.wire import handoff
from taskloop.app.wire import hook as index


def context_out(text: str) -> str:
    return json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}) if text else ""


def start(stdin_text: str, plugin_root: Path) -> str:
    """Never fails the session. After a compaction (source "compact") the stdout carries the handoff as added context."""
    index.session_start(stdin_text)
    index.write_shim(plugin_root)
    try:
        data = json.loads(stdin_text or "{}")
        if data.get("source") == "compact":
            repo = index.repo_of(data)
            return context_out(handoff.read(repo) if repo else "")
    except (ValueError, AttributeError, OSError):
        pass
    return ""


def precompact(stdin_text: str, plugin_root: Path) -> str:
    """Write the repo's handoff. Slots are left out of this one (a bd call): the status shows them."""
    try:
        repo = index.repo_of(json.loads(stdin_text or "{}"))
        if repo:
            handoff.write(repo, plugin_root, time.time(), with_slots=False)
    except (ValueError, AttributeError, OSError, SystemExit):
        pass
    return ""

