"""Run projections from factory.db only; this reader never opens a run file."""

from dataclasses import dataclass, replace

from tlkernel import wire
from tlkernel.paths import ConfigDir
from tlkernel.run import RunManifest
from tlkernel.runlife import shown

from tldash.readers import runprojection
from tldash.views.runfacts import FoldState, Run, run_from


@dataclass(frozen=True)
class StoredRun:
    """Engine-owned manifest joined to optional indexer-owned log facts."""
    manifest: RunManifest
    state: FoldState
    has_log: bool
    log_mtime: float

    def project(self, now: float) -> Run:
        return replace(run_from(self.manifest.run, self.state, now), life=shown(self.manifest, now))


def read(cfg: ConfigDir, now: float, *, repo: str | None = None, bead: str | None = None) -> tuple[list[StoredRun], str]:
    rows, error = runprojection.run_rows(cfg.factory_db(), now, repo=repo, bead=bead)
    try:
        return [StoredRun(r.manifest, wire.load(FoldState, r.state), r.has_log, r.log_mtime)
                for r in rows], error
    except (ValueError, TypeError, KeyError):
        return [], "database unavailable: unreadable run facts"


FOREIGN = "is schema v"  # factorydb's SchemaError text for a version this code does not read
Kept = dict[tuple[str | None, str | None], list[StoredRun]]  # the last valid read of each (repo, bead) question


def read_kept(kept: Kept, cfg: ConfigDir, now: float, *, repo: str | None = None, bead: str | None = None) -> tuple[list[StoredRun], str]:
    """`read`, remembering the last valid answer: a factory.db of a schema this dashboard cannot read (a producer ahead or behind it)
    returns that observation with its error, so the foreign version shows as an error over what was last seen, not as absence. A stale
    index or a corrupt file still drops the rows: old runs there would read as current."""
    rows, error = read(cfg, now, repo=repo, bead=bead)
    if not error:
        kept[repo, bead] = rows
        return rows, ""
    return (kept.get((repo, bead), rows) if FOREIGN in error else rows), error
