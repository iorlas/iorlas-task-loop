"""Read-only profile validation and slot folder facts for setup callers."""
import contextlib
import io
import json
from dataclasses import dataclass
from pathlib import Path

from tlslots import config as slots_config


@dataclass(frozen=True)
class SlotFolders:
    count: int
    root: Path
    missing: tuple[str, ...]


def profile_problem(profile: Path) -> str:
    """'' when the profile loads, else why not (the loader exits naming the key; its message is caught, not printed)."""
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            slots_config.load_profile(json.loads(profile.read_text(encoding="utf-8")))
    except (SystemExit, ValueError, OSError) as e:
        return (err.getvalue().strip() or str(e) or "unreadable")[:300]
    return ""


def slot_folders(repo: Path) -> SlotFolders | None:
    """The configured slot folders, or no facts when the profile cannot load or counts none."""
    try:
        cfg = slots_config.load_profile(json.loads((repo / ".task-loop.json").read_text(encoding="utf-8"))).slots
    except (SystemExit, ValueError, OSError):
        return None
    if cfg.count < 1:
        return None
    root = Path(slots_config.slot_dir(str(repo), "x", cfg)).parent
    missing = tuple(n for n in (f"s{i}" for i in range(1, cfg.count + 1)) if not (root / n).is_dir())
    return SlotFolders(cfg.count, root, missing)
