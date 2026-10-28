"""The SessionStart hook: index the session id -> its transcript path. Must never fail the session."""
import json

from taskloop.adapters.ident import config_dir
from taskloop.app.track.trail import now
from taskloop.contracts.paths import ConfigDir


def session_start(stdin_text: str) -> None:
    try:
        d = json.loads(stdin_text or "{}")
        sid = d.get("session_id")
        if sid:
            f = ConfigDir(config_dir()).session(sid)
            f.parent.mkdir(exist_ok=True)
            f.write_text(json.dumps({"session": sid, "transcript": d.get("transcript_path"), "cwd": d.get("cwd"),
                                     "source": d.get("source"), "t": now()}), encoding="utf-8")
    except Exception:
        pass
