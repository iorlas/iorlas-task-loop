"""Who and where this process is: the task-loop config dir, Claude's dir, the session it acts for, and the bd actor name."""
import json
import socket
from pathlib import Path

from taskloop.adapters.gitrepo import git
from taskloop.contracts import env as penv
from taskloop.contracts.envvars import EnvVar


def config_dir() -> Path:
    """~/.config/task-loop (XDG_CONFIG_HOME moves it), made on first ask."""
    base = Path(penv.ambient("XDG_CONFIG_HOME") or Path.home() / ".config")
    d = base / "task-loop"
    d.mkdir(parents=True, exist_ok=True)
    return d


def claude_dir() -> Path:
    return Path(penv.ambient("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def hostname() -> str:
    return socket.gethostname().split(".")[0].lower()


def session_id() -> str:
    """The session this process acts for: a Claude session, or the engine's own id when nobody drives it."""
    return (penv.ambient(EnvVar.TASK_LOOP_SESSION) or penv.ambient("CLAUDE_CODE_SESSION_ID")
            or penv.ambient("CLAUDE_SESSION_ID") or "")


def actor() -> str:
    """One name per session: two sessions with one actor both 'win' a claim (bd lets the same actor re-claim)."""
    if penv.ambient(EnvVar.TASK_LOOP_ACTOR):
        return penv.ambient(EnvVar.TASK_LOOP_ACTOR)
    sid = session_id()
    if sid:
        return "tl-" + sid[:8]
    if penv.ambient("CLAUDE_PID"):  # older Claude Code: one name per session process, never per folder
        return f"tl-{hostname()}-{penv.ambient('CLAUDE_PID')}"
    top = git("rev-parse", "--show-toplevel")
    return "tl-" + (Path(top).name if top else socket.gethostname())


PLUGIN_ROOT = Path(__file__).resolve().parents[3]  # the install this code runs from (src/taskloop/adapters/ident.py)


def plugin_version() -> str:
    """This install's task-loop version, from its plugin.json ('' when it is run from a bare copy)."""
    try:
        return str(json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")).get("version") or "")
    except (OSError, ValueError):
        return ""
