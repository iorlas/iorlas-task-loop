"""Who and where this process is: the task-loop config dir, Claude's dir, the session it acts for, and the bd actor name."""
import os
import socket
from pathlib import Path

from taskloop.adapters.gitrepo import git


def config_dir() -> Path:
    """~/.config/task-loop (XDG_CONFIG_HOME moves it), made on first ask."""
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / "task-loop"
    d.mkdir(parents=True, exist_ok=True)
    return d


def claude_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def hostname() -> str:
    return socket.gethostname().split(".")[0].lower()


def session_id() -> str:
    """The session this process acts for: a Claude session, or the engine's own id when nobody drives it."""
    return (os.environ.get("TASK_LOOP_SESSION") or os.environ.get("CLAUDE_CODE_SESSION_ID")
            or os.environ.get("CLAUDE_SESSION_ID") or "")


def actor() -> str:
    """One name per session: two sessions with one actor both 'win' a claim (bd lets the same actor re-claim)."""
    if os.environ.get("TASK_LOOP_ACTOR"):
        return os.environ["TASK_LOOP_ACTOR"]
    sid = session_id()
    if sid:
        return "tl-" + sid[:8]
    if os.environ.get("CLAUDE_PID"):  # older Claude Code: one name per session process, never per folder
        return f"tl-{hostname()}-{os.environ['CLAUDE_PID']}"
    top = git("rev-parse", "--show-toplevel")
    return "tl-" + (Path(top).name if top else socket.gethostname())
