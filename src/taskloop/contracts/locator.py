"""Find and update authoritative run manifests in factory.db; finish_run owns the terminal answer."""
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from stream_proc import proc_start

from taskloop.contracts.enums import Step
from taskloop.contracts.finish import FinishResult, finish_run, previous_finish
from taskloop.contracts.ids import RunId
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import RunManifest, RunState
from taskloop.contracts.runrows import RunRows, import_once


def host_name() -> str:
    """This machine's name, the `host` a run records (a pid means something only on its own host)."""
    return os.uname().nodename


@dataclass(frozen=True)
class RunBundle:
    """One run: its manifest and where its files are."""

    manifest: RunManifest
    log: Path  # the engine log
    err: Path
    live: Path  # the worker's per-call files
    dir: Path  # the run folder (brief, plan, answers, check results)

    @property
    def run(self) -> str:
        return self.manifest.run

    @property
    def bead(self) -> str:
        return self.manifest.bead

    @property
    def repo(self) -> str:
        return self.manifest.repo

    @property
    def started(self) -> float:
        return self.manifest.started


class RunLocator:
    """Finds runs in the shared database without holding a connection."""

    def __init__(self, cfg: ConfigDir) -> None:
        self.cfg = cfg
        self.rows = RunRows(cfg)

    def _ready(self) -> None:
        import_once(self.cfg)

    def bundle(self, manifest: RunManifest) -> RunBundle:
        c = self.cfg
        log = c.engine_log(manifest.run)
        return RunBundle(manifest, log, log.with_suffix(".stderr"), c.live_dir(manifest.run), c.run_dir(manifest.run))

    def get(self, run: str) -> RunBundle | None:
        """The bundle of a run id; None when it has no readable manifest."""
        self._ready()
        m = self.rows.get(run)
        return self.bundle(m) if m is not None and m.run == run else None

    def runs(self) -> list[RunBundle]:
        """Every run that has a manifest, oldest start first (ties: by id)."""
        self._ready()
        return [self.bundle(m) for m in self.rows.all()]

    def of_bead(self, bead: str, repo: str | None = None) -> list[RunBundle]:
        """The runs of a bead (of one repo when `repo` is named), oldest first."""
        self._ready()
        return [self.bundle(m) for m in self.rows.of_bead(bead, repo)]

    def of_repo(self, repo: str) -> list[RunBundle]:
        self._ready()
        return [self.bundle(m) for m in self.rows.of_repo(repo)]

    def newest(self, bead: str, repo: str | None = None) -> RunBundle | None:
        return next(iter(reversed(self.of_bead(bead, repo))), None)

    def _change(self, run: str, change: Callable[[RunManifest], RunManifest]) -> None:
        self._ready()
        self.rows.change(run, change)

    def identify(self, run: str, mode: str, owner: str, session: str) -> None:
        self._change(run, lambda m: m.replace(mode=mode, owner=owner, session=session))

    def advance(self, run: str, step: Step | None) -> None:
        self._change(run, lambda m: m.replace(next_step=step))

    def worktree(self, run: str, path: str) -> None:
        self._change(run, lambda m: m.replace(worktree=path))

    def create(self, repo: str, bead: str, now: float, loop: str | None = None, *, mode: str = "", owner: str = "",
               session: str = "", loop_id: str | None = None) -> RunBundle:
        """A new run: a fresh opaque id, its folder and its manifest (state created, owned by this process). `mode`, `owner` and
        `session` say what kind of run it is and whose."""
        while True:
            run = str(RunId.new(now))
            try:
                self.cfg.run_dir(run).mkdir(parents=True)
            except FileExistsError:
                continue
            break
        m = RunManifest(run=run, repo=repo, bead=bead, started=now, loop=loop, loop_id=loop_id, heartbeat=now, pid=os.getpid(),
                        pid_start=proc_start(os.getpid()) or "", host=host_name(), mode=mode, owner=owner, session=session)
        self._ready()
        with self.rows.transaction() as con:
            self.rows.write(con, m, attempt_started=now)
        self.cfg.engine_dir().mkdir(parents=True, exist_ok=True)
        return self.bundle(m)

    def take_up(self, run: str, repo: str, bead: str, now: float) -> RunBundle:
        """An engine takes an unfinished run up after exec: one more attempt, owned by this process. A resumed close keeps its terminal
        answer; a run folder with no manifest gets one. A terminal network pause continues under a new run id instead."""
        self.cfg.run_dir(run).mkdir(parents=True, exist_ok=True)
        self.cfg.engine_dir().mkdir(parents=True, exist_ok=True)
        self._ready()
        with self.rows.transaction() as con:
            old = self.rows.read(con, run)
            own = {"heartbeat": now, "pid": os.getpid(), "pid_start": proc_start(os.getpid()) or "", "host": host_name()}
            m = (old.replace(attempts=old.attempts + 1, **(own if old.state.live else {})) if old
                 else RunManifest(run=run, repo=repo, bead=bead, started=now, **own))
            self.rows.write(con, m, attempt_started=now)
        return self.bundle(m)

    def add_bead(self, run: str, bead: str) -> None:
        """A run learns a bead it works on: the first fills `bead`, the others join `beads` (once each)."""
        def add(m: RunManifest) -> RunManifest:
            if not bead or bead == m.bead or bead in m.beads:
                return m
            return m.replace(bead=bead) if not m.bead else m.replace(beads=(*m.beads, bead))

        self._change(run, add)

    def beat(self, run: str, now: float) -> None:
        """The engine's tick: the run is running and alive as of `now`. A run that already has a terminal state keeps it."""
        self._ready()
        with self.rows.transaction() as con:
            m = self.rows.read(con, run)
            if m is not None:
                if m.state.live:
                    self.rows.write(con, m.replace(state=RunState.RUNNING, heartbeat=now))
                con.execute("UPDATE attempt SET beat=? WHERE run=? AND n=? AND ended IS NULL", (now, run, m.attempts))

    def end(self, run: str, now: float, state: RunState, reason: str = "") -> FinishResult | None:
        """Compatibility entry for callers with only a state; finish_run owns every terminal write."""
        if state.live:
            raise ValueError(f"{state} is not a terminal state")
        old = self.get(run)
        if old is None:
            return None
        candidate = previous_finish(old.manifest.replace(state=state, ended=now, reason=reason, finish=None))
        return finish_run(self.cfg, run, candidate)

    def mark_lost(self, run: str, reason: str) -> FinishResult | None:
        """The reconciler's one write: a run still in a live state becomes `lost`, once, with its reason (`runlife.reconcile` decides)."""
        old = self.get(run)
        if old is None:
            return None
        candidate = previous_finish(old.manifest.replace(state=RunState.LOST, ended=old.manifest.heartbeat,
                                                        reason=reason[:300], finish=None))
        return finish_run(self.cfg, run, candidate)
