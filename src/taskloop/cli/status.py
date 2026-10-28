"""`tl status [--brief] [--json]` and `tl handoff write|show`: print what the stores say (src/taskloop/domain/brief.py makes the text)."""
from pathlib import Path

from taskloop.app.wire import brief, handoff


def run_status(repo: str, plugin_root: Path, now: float, as_json: bool) -> int:
    print(brief.status_text(repo, plugin_root, now, as_json))
    return 0


def run_handoff(op: str, repo: str, plugin_root: Path, now: float) -> int:
    if op == "write":
        print(handoff.write(repo, plugin_root, now))
        return 0
    text = handoff.read(repo)
    print(text or f"no handoff written for {repo} (tl handoff write)", end="" if text else "\n")
    return 0 if text else 1
