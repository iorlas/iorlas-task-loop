"""Run projections from factory.db only; this reader never opens a run file."""

from dataclasses import dataclass, replace

from taskloop.contracts import factorydb, wire
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import RunManifest
from taskloop.contracts.runlife import shown
from taskloop_dash.views.runfacts import FoldState, Run, run_from


@dataclass(frozen=True)
class StoredRun:
    manifest: RunManifest
    state: FoldState
    has_log: bool
    log_mtime: float

    def project(self, now: float) -> Run:
        return replace(run_from(self.manifest.run, self.state, now), life=shown(self.manifest, now))


def read(cfg: ConfigDir, now: float, *, repo: str | None = None, bead: str | None = None) -> tuple[list[StoredRun], str]:
    rows, error = factorydb.run_rows(cfg.factory_db(), now, repo=repo, bead=bead)
    try:
        return [StoredRun(r.manifest, wire.load(FoldState, r.state), r.has_log, r.log_mtime)
                for r in rows], error
    except (ValueError, TypeError, KeyError):
        return [], "database unavailable: unreadable run facts"
