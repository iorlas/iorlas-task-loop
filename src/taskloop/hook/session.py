"""The SessionStart and PreCompact hooks: index the session, keep the `tl` shim pointing at this install, write the handoff before a
compaction and give it back after one."""
import json
import time
from pathlib import Path

from taskloop.app.wire import handoff, real
from taskloop.app.wire import hook as index
from taskloop.contracts.env import Env, snapshot
from taskloop.contracts.ports import Git


def context_out(text: str) -> str:
    return json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}) if text else ""


def start(stdin_text: str, plugin_root: Path, env: Env, git: Git) -> str:
    """Never fails the session. After a compaction (source "compact") the stdout carries the handoff as added context."""
    index.session_start(stdin_text, env)
    index.write_shim(plugin_root, env)
    index.write_hooks(plugin_root, env)
    try:
        data = json.loads(stdin_text or "{}")
        if data.get("source") == "compact":
            repo = index.repo_of(git, data)
            return context_out(handoff.read(repo, env) if repo else "")
    except (ValueError, AttributeError, OSError):
        pass
    return ""


def precompact(stdin_text: str, plugin_root: Path, env: Env, git: Git) -> str:
    """Write the repo's handoff. Slots are left out of this one (a bd call): the status shows them."""
    try:
        repo = index.repo_of(git, json.loads(stdin_text or "{}"))
        if repo:
            handoff.write(repo, plugin_root, time.time(), env, who=None)
    except (ValueError, AttributeError, OSError, SystemExit):
        pass
    return ""



def entry(event: str, stdin_text: str, plugin_root: Path) -> str:
    """The session hooks' edge: the real Git port on this process's environment, handed down."""
    env = snapshot()
    git = real.git(env)
    return (start if event == "session-start" else precompact)(stdin_text, plugin_root, env, git)
