"""`tl handoff write|show`, and what the hooks do with it: the handoff is generated from the stores into one file per repo."""
import os
from pathlib import Path

from taskloop.app.wire import brief
from taskloop.domain.brief import handoff_text


def write(repo: str, plugin_root: Path, now: float, with_slots: bool = True) -> Path:
    f = brief.handoff_file(repo)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f"{f.name}.{os.getpid()}.tmp")
    tmp.write_text(handoff_text(brief.build(repo, plugin_root, now, with_slots)), encoding="utf-8")
    os.replace(tmp, f)
    return f


def read(repo: str) -> str:
    try:
        return brief.handoff_file(repo).read_text(encoding="utf-8")
    except OSError:
        return ""
