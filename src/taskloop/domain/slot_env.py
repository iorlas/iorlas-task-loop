"""The environment of one slot: what every command a bead runs in that slot is given, so no two slots share a temp file, a pipe or
a lock (a compiler server, a build node, a package scratch: the repo names those in engine.slot_env). Pure: the caller makes the folders."""
import hashlib
from collections.abc import Mapping
from pathlib import Path

from taskloop.contracts.config import fill_slot_env


def repo_id(origin: str, fallback: str) -> str:
    """A short name of the repo for ids and folders: the origin url's last part (else the folder's), made of [\\w.-]."""
    name = Path((origin or fallback).rstrip("/")).name
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in name.removesuffix(".git"))[:40] or "repo"


def state_key(origin: str, fallback: str) -> str:
    """The folder name of a repo's state under repos/: its short name and a hash of the origin url, so two repos of one name never meet."""
    return f"{repo_id(origin, fallback)}-{hashlib.sha1((origin or fallback).encode('utf-8', 'surrogateescape')).hexdigest()[:10]}"


def slot_env(state: Path, repo: str, slot: str, extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """TMPDIR/TMP/TEMP under `state` (the slot's folder outside its worktree) and TL_SLOT; then `extra` (engine.slot_env: the repo's own
    toolchain scratch) over them, placeholders filled."""
    tmp = str(state / "tmp")
    base = {"TMPDIR": tmp, "TMP": tmp, "TEMP": tmp, "TL_SLOT": slot}
    return {**base, **fill_slot_env(extra or {}, slot=slot, slot_dir=str(state), repo=repo)}


def folders(env: Mapping[str, str], state: Path) -> list[str]:
    """The folders the environment names (made on use): every value that is a path under the slot's state."""
    return [v for v in env.values() if Path(v).is_absolute() and Path(v).is_relative_to(state)]
