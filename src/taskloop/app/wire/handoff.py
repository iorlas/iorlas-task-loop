"""`tl handoff write|show`, and what the hooks do with it: the handoff is generated from the stores into one file per repo."""
from pathlib import Path

from atomic_io import atomic_write_text

from taskloop.app.wire import brief
from taskloop.domain.brief import handoff_text


def write(repo: str, plugin_root: Path, now: float, with_slots: bool = True) -> Path:
    f = brief.handoff_file(repo)
    atomic_write_text(f, handoff_text(brief.build(repo, plugin_root, now, with_slots)), fsync=False)
    return f


def read(repo: str) -> str:
    try:
        return brief.handoff_file(repo).read_text(encoding="utf-8")
    except OSError:
        return ""
