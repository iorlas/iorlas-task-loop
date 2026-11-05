"""The one writer of the artifact store (the artifact_add tool and the engine's renders both call `add`) and its readers.

<root>/<repo>/<bead>/<run>/<stage>-<attempt>/<name> plus <name>.json (contracts/artifact.py ArtifactMeta). The file lands first
(built beside it, renamed in), the sidecar last, so a file without a sidecar is not an artifact. A run keeps at most `cap` bytes of
new content (keep.py: an identical picture is a link, not a second copy)."""
import hashlib
import json
from pathlib import Path

from atomic_io import atomic_write_bytes

from taskloop.app.artifacts import rules
from taskloop.app.artifacts.keep import CAP_BYTES, Keeper
from taskloop.contracts.artifact import SIDECAR_SUFFIX, ArtifactMeta, ArtifactSlot
from taskloop.contracts.wire import Refused, dump, load


def run_folder(root: Path, slot: ArtifactSlot) -> Path:
    return root / slot.repo / slot.bead / slot.run


def folder(root: Path, slot: ArtifactSlot) -> Path:
    return run_folder(root, slot) / f"{slot.stage}-{slot.attempt}"


def sidecar(file: Path) -> Path:
    return file.with_name(file.name + SIDECAR_SUFFIX)


def digest(src: Path) -> str:
    h = hashlib.sha256()
    with src.open("rb") as f:
        while block := f.read(1 << 20):
            h.update(block)
    return h.hexdigest()


def add(root: Path, slot: ArtifactSlot, src: Path, *, name: str, caption: str, role: str, now: float,
        cap: int = CAP_BYTES) -> ArtifactMeta:
    """`src` becomes artifact `name` of the slot's stage attempt; a name already there is replaced. Raises Refused (the message says
    what to change) and leaves nothing that reads as an artifact."""
    role = rules.check_fields(name, caption, role)
    kind = rules.check_file(src, name)
    dest = folder(root, slot) / name
    run = run_folder(root, slot)
    earlier = sorted(d for d in run.parent.iterdir() if d.is_dir() and d != run) if run.parent.is_dir() else []
    sidecar(dest).unlink(missing_ok=True)  # replacing: until the new sidecar is down the name is no artifact
    if not Keeper([run], earlier, cap).keep(src, dest):
        raise Refused(f"the run's artifacts would pass {cap >> 20} MB; keep fewer or smaller files")
    meta = ArtifactMeta(name=name, caption=caption, role=role, kind=kind, size=dest.stat().st_size,
                        sha256=digest(dest), created=now)
    atomic_write_bytes(sidecar(dest), json.dumps(dump(meta)).encode(), fsync=False)
    return meta


def listing(attempt_dir: Path) -> list[ArtifactMeta]:
    """The artifacts of one stage attempt folder, oldest first: its sidecars. A sidecar that does not read is skipped."""
    found: list[ArtifactMeta] = []
    if not attempt_dir.is_dir():
        return found
    for f in sorted(attempt_dir.glob("*" + SIDECAR_SUFFIX)):
        try:
            found.append(load(ArtifactMeta, f.read_bytes()))
        except (OSError, ValueError):
            continue
    return sorted(found, key=lambda m: m.created)


def run_listing(root: Path, slot: ArtifactSlot) -> list[tuple[Path, ArtifactMeta]]:
    """Every artifact of the slot's run, oldest first: (file, meta). One fixed level, <stage>-<attempt>, no wildcard over the tree."""
    run = run_folder(root, slot)
    if not run.is_dir():
        return []
    found = [(d / m.name, m) for d in sorted(run.iterdir()) if d.is_dir() for m in listing(d)]
    return sorted(found, key=lambda x: x[1].created)
