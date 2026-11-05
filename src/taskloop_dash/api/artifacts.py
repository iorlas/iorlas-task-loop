"""A bead's artifacts, read from the store `<config>/artifacts/<repo>/<bead>/<run>/<stage>-<attempt>/<name>` (+ `<name>.json`).

The directory is the index (tl-jvpm.5): a file with no sidecar is not an artifact. Only the fixed levels are walked, run by run and
stage folder by stage folder, never a wildcard over the store (tl-jvpm.11). A folder's listing is kept until its mtime changes, so a
poll stats directories and reads a sidecar once per folder change (tl-jvpm.17). The old flat per-bead folders are not read."""

import os
import threading
from collections.abc import Sequence
from pathlib import Path

from taskloop.contracts import wire
from taskloop.contracts.artifact import SIDECAR_SUFFIX, ArtifactMeta
from taskloop.contracts.ids import is_bead_id
from taskloop_dash.env import Env
from taskloop_dash.views.artifact_files import Item, plain, served, split_stage


def mtime(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None


class Artifacts:
    def __init__(self, env: Env) -> None:
        self.env = env
        self.lock = threading.Lock()
        self.runs: dict[Path, tuple[int, tuple[str, ...]]] = {}  # run folder -> (its mtime, its stage-attempt folder names)
        self.folders: dict[Path, tuple[int, tuple[Item, ...]]] = {}  # stage folder -> (its mtime, its items)

    def root(self, repo: str, bead: str) -> Path:
        return self.env.config.artifact_store() / repo / bead

    def listing(self, repo: str, bead: str, runs: Sequence[str]) -> list[Item]:
        """The bead's artifacts, newest first: the folders of the runs the bead is known to have, nothing else."""
        if not plain(repo) or not is_bead_id(bead):
            return []
        out: list[Item] = []
        for run in runs:
            if plain(run):
                out += self.of_run(self.root(repo, bead) / run, run)
        return sorted(out, key=lambda i: -i.t)

    def of_run(self, folder: Path, run: str) -> list[Item]:
        stamp = mtime(folder)
        if stamp is None:
            return []
        with self.lock:
            hit = self.runs.get(folder)
        if hit is None or hit[0] != stamp:
            try:
                subs = tuple(sorted(e.name for e in os.scandir(folder) if e.is_dir(follow_symlinks=False)))
            except OSError:
                return []
            hit = (stamp, subs)
            with self.lock:
                self.runs[folder] = hit
        return [i for sub in hit[1] if (st := split_stage(sub)) for i in self.of_folder(folder / sub, run, *st)]

    def of_folder(self, folder: Path, run: str, stage: str, attempt: int) -> tuple[Item, ...]:
        stamp = mtime(folder)
        if stamp is None:
            return ()
        with self.lock:
            hit = self.folders.get(folder)
        if hit is None or hit[0] != stamp:
            hit = (stamp, self.read_folder(folder, run, stage, attempt))
            with self.lock:
                self.folders[folder] = hit
        return hit[1]

    def read_folder(self, folder: Path, run: str, stage: str, attempt: int) -> tuple[Item, ...]:
        try:
            entries = {e.name: e for e in os.scandir(folder)}
        except OSError:
            return ()
        out: list[Item] = []
        for fname in sorted(entries):
            name = fname.removesuffix(SIDECAR_SUFFIX)
            if fname == name or name not in entries or not entries[name].is_file(follow_symlinks=False):
                continue
            side = self.sidecar(folder / fname)
            if side is None or side.name != name:
                continue
            out.append(Item(run, stage, attempt, name, served(name)[0], side.caption, side.role, side.created))
        return tuple(out)

    def sidecar(self, path: Path) -> ArtifactMeta | None:
        try:
            return wire.load(ArtifactMeta, path.read_bytes())
        except (OSError, ValueError):
            return None

    def file(self, repo: str, bead: str, run: str, stage: str, attempt: str, name: str) -> tuple[bytes, str, bool] | None:
        """(bytes, content type, inline) of one registered file; None for a bad part, a symlink, a missing file or sidecar."""
        if not (plain(repo) and is_bead_id(bead) and plain(run) and plain(stage) and attempt.isascii() and attempt.isdigit()
                and plain(name)):
            return None
        folder = self.root(repo, bead) / run / f"{stage}-{int(attempt)}"
        p = folder / name
        try:
            if p.is_symlink() or not p.is_file():
                return None
            side = self.sidecar(folder / (name + SIDECAR_SUFFIX))
            if side is None or side.name != name:
                return None
            data = p.read_bytes()
        except OSError:
            return None
        kind, ctype = served(name)
        return data, ctype, kind != "file"
