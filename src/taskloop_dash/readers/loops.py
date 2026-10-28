"""The loops of a repo as their files tell it: each live loop's state (LoopState, with the queue it ranked) and the stop commands
filed for them (LoopCommand). Read only."""

import hashlib
from pathlib import Path
from typing import Any, Final

from taskloop_dash.env import Env
from taskloop_dash.readers.records import pid_alive
from taskloop_dash.tails import read_dict

STATE_V: Final = 2  # LoopState.V: a file of another version is not a loop of this build
STOP_ACTIONS: Final = {"stop_now": "now", "stop_after_current": "after"}  # LoopCommand.action -> the lane's stop mode
STOP_KINDS: Final = {"now": "now", "after_current": "after"}  # LoopState.stop.kind -> the lane's stop mode


def loop_key(repo: str) -> str:
    """The name the loop files of a repo share (its folder and a hash of its path)."""
    return f"{Path(repo).name}-{hashlib.sha1(repo.encode()).hexdigest()[:8]}"


class Loops:
    def __init__(self, env: Env) -> None:
        self.env = env

    def live(self, repo: str) -> list[dict[str, Any]]:
        """The state of every live loop on the repo, freshest beat first."""
        cfg, key = self.env.config, loop_key(repo)
        state = cfg.loop_state(key)
        states = (read_dict(f) for f in sorted(state.parent.glob(key + ".*.json")))
        found = [st for st in states if st.get("v") == STATE_V and pid_alive(st.get("pid"))]
        return sorted(found, key=lambda st: -float(st.get("t") or 0))

    def command_stops(self, repo: str) -> dict[int, str]:
        """{pid: now|after} the repo's command file names (a `resume` or an unreadable file names none)."""
        cmd = read_dict(self.env.config.loop_command(loop_key(repo)))
        mode, targets = STOP_ACTIONS.get(str(cmd.get("action"))), cmd.get("targets")
        return {int(p): mode for p in targets if isinstance(p, int)} if mode and isinstance(targets, list) else {}

    def queue(self, repo: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """([(id, reason)] in the order the loop takes them, [(id, why skipped)]), as the freshest live loop last ranked them. No live
        loop, no queue."""
        live = self.live(repo)
        rows = [r for r in (live[0].get("queue") or []) if isinstance(r, dict)] if live else []
        ranked = sorted((r for r in rows if not r.get("skip")), key=lambda r: r.get("ahead") or 0)
        return ([(r["bead"], r.get("reason") or "") for r in ranked],
                [(r["bead"], (r["skip"] or {}).get("why") or "") for r in rows if r.get("skip")])
