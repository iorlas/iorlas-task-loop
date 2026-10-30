"""Who and where this process is: the task-loop config dir, Claude's dir, the session it acts for, and the bd actor name."""
import json
import os
import socket
from pathlib import Path

from taskloop.adapters.gitrepo import pinned_env
from taskloop.contracts.env import Env
from taskloop.contracts.envvars import EnvVar
from taskloop.contracts.identity import Identity
from taskloop.contracts.paths import default_root


def config_dir(env: Env) -> Path:
    """~/.config/task-loop (XDG_CONFIG_HOME of `env` moves it), made on first ask."""
    d = default_root(env)
    if not d.is_dir():
        d.mkdir(parents=True, exist_ok=True)
    return d


def claude_dir(env: Env) -> Path:
    return Path(env.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def hostname() -> str:
    return socket.gethostname().split(".")[0].lower()


def identity(env: Env) -> Identity:
    """The session this process acts for (a Claude session, or the engine's own id when nobody drives it) and its bd actor: one name per
    session, since two sessions with one actor both 'win' a claim (bd lets the same actor re-claim)."""
    home = str(default_root(env))  # not made here: a verb that refuses its input leaves no folder behind
    session = env.get(EnvVar.TASK_LOOP_SESSION) or env.get("CLAUDE_CODE_SESSION_ID") or env.get("CLAUDE_SESSION_ID")
    if env.get(EnvVar.TASK_LOOP_ACTOR):
        return Identity(actor=env.get(EnvVar.TASK_LOOP_ACTOR), home=home, session=session)
    if session:
        return Identity(actor="tl-" + session[:8], home=home, session=session)
    if env.get("CLAUDE_PID"):  # older Claude Code: one name per session process, never per folder
        return Identity(actor=f"tl-{hostname()}-{env.get('CLAUDE_PID')}", home=home)
    top = pinned_env(os.getcwd()).get("GIT_WORK_TREE", "")  # the checkout this process runs in
    return Identity(actor="tl-" + (Path(top).name if top else socket.gethostname()), home=home)


PLUGIN_ROOT = Path(__file__).resolve().parents[3]  # the install this code runs from (src/taskloop/adapters/ident.py)


def plugin_version() -> str:
    """This install's task-loop version, from its plugin.json ('' when it is run from a bare copy)."""
    try:
        return str(json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")).get("version") or "")
    except (OSError, ValueError):
        return ""
