"""The SessionStart and PreCompact hooks: index the session, keep launchers on the newest install, write the handoff before a
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
    """Introduce task-loop in profile repos; after compaction append the handoff. Never fail the session."""
    try:
        index.ensure_machine(plugin_root, env)
        data = json.loads(stdin_text or "{}")
        repo = index.repo_of(git, data)
        parts = [index.self_description(repo)]
        if data.get("source") == "compact":
            parts.append(handoff.read(repo, env) if repo else "")
        return context_out("\n\n".join(part for part in parts if part))
    except Exception:
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
