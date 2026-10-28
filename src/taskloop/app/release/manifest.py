"""MANIFEST.sha256: the sha256 of every tracked file of a release, committed with it. `tl doctor` checks an installed plugin against it."""
import hashlib
from pathlib import Path

NAME = "MANIFEST.sha256"


def digest(f: Path) -> str:
    return hashlib.sha256(f.read_bytes()).hexdigest()


def build(root: Path, files: list[str]) -> str:
    """One `<sha256>  <path>` line per file, sorted. The manifest itself and anything not a readable file (a dangling link) is left out."""
    rows = sorted((p, digest(root / p)) for p in files if p != NAME and (root / p).is_file())
    return "".join(f"{sha}  {p}\n" for p, sha in rows)


def write(root: Path, files: list[str]) -> None:
    (root / NAME).write_text(build(root, files), encoding="utf-8")


def verify(root: Path) -> list[str]:
    """What differs between the files under `root` and its manifest, one line per file naming it; [] when all match. A file the
    manifest does not list is none of its business (bytecode, logs)."""
    try:
        text = (root / NAME).read_text(encoding="utf-8")
    except OSError:
        return [f"{NAME} is missing in {root}"]
    out: list[str] = []
    for line in text.splitlines():
        sha, _, rel = line.partition("  ")
        f = root / rel
        try:
            if digest(f) != sha:
                out.append(f"{rel} differs from {NAME}")
        except OSError:
            out.append(f"{rel} is listed in {NAME} but missing")
    return out
