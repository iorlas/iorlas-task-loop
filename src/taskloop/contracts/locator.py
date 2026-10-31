"""Where a run is: the one API that finds a run, and the one writer of its manifest. runs/<run>/manifest.json is the authority (run id,
repo, bead, start and end, loop, attempts); nothing else reads a bead, a repo or a time out of a file name or a path depth. Queries: a
run id -> its bundle; (repo, bead) -> its runs; a repo -> its runs; every run, by start time. A directory scan plus the manifests, no
index: a manifest is decoded again only when its file changed. A run folder without a manifest is not a run here. The manifest also
holds the run's state (RunState): the engine writes it, `reconcile` marks a dead run lost, and every reader reads only that state."""
import os
from dataclasses import dataclass
from pathlib import Path

from taskloop.contracts.ids import RunId
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import RunManifest, RunState
from taskloop.contracts.stores import JsonStore


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
    """Finds runs under a ConfigDir. Keep one per process where scans repeat: it remembers the manifests it decoded."""

    def __init__(self, cfg: ConfigDir) -> None:
        self.cfg = cfg
        self._seen: dict[str, tuple[tuple[int, int], RunManifest | None]] = {}

    def bundle(self, manifest: RunManifest) -> RunBundle:
        c = self.cfg
        log = c.engine_log(manifest.run)
        return RunBundle(manifest, log, log.with_suffix(".stderr"), c.live_dir(manifest.run), c.run_dir(manifest.run))

    def get(self, run: str) -> RunBundle | None:
        """The bundle of a run id; None when it has no readable manifest."""
        m = JsonStore(self.cfg.run_manifest(run), RunManifest).get()
        return self.bundle(m) if m is not None and m.run == run else None

    def runs(self) -> list[RunBundle]:
        """Every run that has a manifest, oldest start first (ties: by id)."""
        found: list[RunBundle] = []
        try:
            entries = [e for e in os.scandir(self.cfg.runs_dir()) if e.is_dir()]
        except OSError:
            return found
        for e in entries:
            m = self._manifest(e.name)
            if m is not None and m.run == e.name:
                found.append(self.bundle(m))
        return sorted(found, key=lambda b: (b.started, b.run))

    def of_bead(self, bead: str, repo: str | None = None) -> list[RunBundle]:
        """The runs of a bead (of one repo when `repo` is named), oldest first."""
        return [b for b in self.runs() if b.bead == bead and (repo is None or b.repo == repo)]

    def of_repo(self, repo: str) -> list[RunBundle]:
        return [b for b in self.runs() if b.repo == repo]

    def newest(self, bead: str, repo: str | None = None) -> RunBundle | None:
        return next(iter(reversed(self.of_bead(bead, repo))), None)

    def _manifest(self, run: str) -> RunManifest | None:
        path = self.cfg.run_manifest(run)
        try:
            st = path.stat()
        except OSError:
            self._seen.pop(run, None)
            return None
        sig = (st.st_mtime_ns, st.st_size)
        hit = self._seen.get(run)
        if hit is None or hit[0] != sig:
            hit = (sig, JsonStore(path, RunManifest).get())
            self._seen[run] = hit
        return hit[1]

    # the writer: the engine of the run, and the one reconciler
    def _put(self, m: RunManifest) -> None:
        JsonStore(self.cfg.run_manifest(m.run), RunManifest).write(m)

    def create(self, repo: str, bead: str, now: float, loop: str | None = None, *, mode: str = "", owner: str = "",
               session: str = "") -> RunBundle:
        """A new run: a fresh opaque id, its folder and its manifest (state created, owned by this process). `mode`, `owner` and
        `session` say what kind of run it is and whose."""
        while True:
            run = str(RunId.new(now))
            try:
                self.cfg.run_dir(run).mkdir(parents=True)
            except FileExistsError:
                continue
            break
        m = RunManifest(run=run, repo=repo, bead=bead, started=now, loop=loop, heartbeat=now, pid=os.getpid(), host=host_name(),
                        mode=mode, owner=owner, session=session)
        self._put(m)
        self.cfg.engine_dir().mkdir(parents=True, exist_ok=True)
        return self.bundle(m)

    def take_up(self, run: str, repo: str, bead: str, now: float) -> RunBundle:
        """An engine process takes a run up again (after an exec, a pause or a crash in the close): one more attempt, state created,
        owned by this process. A run folder with no manifest gets one."""
        self.cfg.run_dir(run).mkdir(parents=True, exist_ok=True)
        self.cfg.engine_dir().mkdir(parents=True, exist_ok=True)
        old = self.get(run)
        own = {"state": RunState.CREATED, "ended": None, "reason": "", "heartbeat": now, "pid": os.getpid(), "host": host_name()}
        m = (old.manifest.replace(attempts=old.manifest.attempts + 1, **own) if old
             else RunManifest(run=run, repo=repo, bead=bead, started=now, **own))
        self._put(m)
        return self.bundle(m)

    def add_bead(self, run: str, bead: str) -> None:
        """A run learns a bead it works on: the first fills `bead`, the others join `beads` (once each)."""
        old = self.get(run)
        if old is None or not bead or bead == old.manifest.bead or bead in old.manifest.beads:
            return
        m = old.manifest
        self._put(m.replace(bead=bead) if not m.bead else m.replace(beads=(*m.beads, bead)))

    def beat(self, run: str, now: float) -> None:
        """The engine's tick: the run is running and alive as of `now`. A run that already has a terminal state keeps it."""
        old = self.get(run)
        if old is not None and old.manifest.state.live:
            self._put(old.manifest.replace(state=RunState.RUNNING, heartbeat=now))

    def end(self, run: str, now: float, state: RunState, reason: str = "") -> None:
        """The run ended: its terminal state, why, and when. A run that is already terminal is left as it is (a state is set once)."""
        if state.live:
            raise ValueError(f"{state} is not a terminal state")
        old = self.get(run)
        if old is not None and old.manifest.state.live:
            self._put(old.manifest.replace(state=state, ended=now, heartbeat=now, reason=reason[:300]))

    def mark_lost(self, run: str, reason: str) -> None:
        """The reconciler's one write: a run still in a live state becomes `lost`, once, with its reason (`runlife.reconcile` decides)."""
        old = self.get(run)
        if old is not None and old.manifest.state.live:
            m = old.manifest
            self._put(m.replace(state=RunState.LOST, ended=m.heartbeat, reason=reason[:300]))
