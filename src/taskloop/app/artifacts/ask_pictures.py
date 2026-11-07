"""The pictures a failing check left, joined to the ask that stops the run (tl-jvpm.25, tl-3qz): the newest attempt of each check under
<run>/attempts/*/artifacts/<check>/ is read, every image in it is registered in the store through the one writer, and the ids go on the
ask. What is an image comes from the first bytes, never from a file name. Nothing here raises into the engine."""
from pathlib import Path
from typing import Final

from tlkernel.artifact import ArtifactSlot
from tlkernel.paths import RunFiles
from tlkernel.wire import Refused

from taskloop.app.artifacts import rules, store

MAX_PICTURES: Final = 4
IMAGES: Final = ("png", "jpg", "gif", "webp")


def newest_attempt(check_dir: Path) -> Path | None:
    attempts = [(int(d.name.removeprefix("attempt-")), d) for d in check_dir.iterdir()
                if d.is_dir() and d.name.startswith("attempt-") and d.name.removeprefix("attempt-").isdigit()]
    return max(attempts, key=lambda x: x[0])[1] if attempts else None


def attach(root: Path, slot: ArtifactSlot, run_dir: Path, *, now: float, cap: int | None = None) -> list[str]:
    """The ids (`<repo>/<bead>/<run>/<stage>-<attempt>/<name>`) of the pictures registered for the slot's ask; [] when the run kept none."""
    ids: list[str] = []
    newest: dict[str, Path] = {}
    for _, check_dir in RunFiles(run_dir).check_dirs():  # oldest run attempt first: a later one replaces the step's folder
        newest[check_dir.name] = check_dir
    for check_dir in sorted(newest.values()):
        try:
            attempt = newest_attempt(check_dir)
            files = sorted(f for f in attempt.iterdir() if f.is_file() and not f.is_symlink()) if attempt else []
        except OSError:
            continue
        for f in files:
            name = f"{check_dir.name}-{f.name}"
            if len(ids) >= MAX_PICTURES:
                return ids
            try:
                if rules.check_file(f, name) not in IMAGES:
                    continue
                kw = {} if cap is None else {"cap": cap}
                store.add(root, slot, f, name=name, caption=f"left by the failing check {check_dir.name}", role="result", now=now, **kw)
            except (Refused, KeyError, OSError):  # not a picture, or not one the store takes: the ask goes without it
                continue
            ids.append(f"{slot.repo}/{slot.bead}/{slot.run}/{slot.stage}-{slot.attempt}/{name}")
    return ids
