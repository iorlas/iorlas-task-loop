"""The v2 World read from this machine: registered repos, the database bead projection, slot beads, loops' state files, the
owner-look items, the engine logs as typed runs, the live asks, the ask ledger, the decisions in force, the landed runs and
delegate's lane status. Read only; bead listings come only from factory.db."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from taskloop.contracts import factorydb, wire
from taskloop.contracts.adrs import AdrStore
from taskloop.contracts.ask import Ask
from taskloop.contracts.askrows import read_snapshot
from taskloop.contracts.bead import Bead, Comment
from taskloop.contracts.dashruns import ResourceLease, RunHeader
from taskloop.contracts.delegate import LiveEvent
from taskloop.contracts.enums import Outcome
from taskloop.contracts.ids import BeadId, loop_key
from taskloop.contracts.ledger import LedgerEntry
from taskloop.contracts.loop import LoopState
from taskloop.contracts.run import RunState
from taskloop.contracts.runlife import RETAIN, Liveness, shown
from taskloop.contracts.slots import slots_of
from taskloop.contracts.slottable import SlotSource
from taskloop.contracts.stores import LIVE, JsonStore, StatusStore
from taskloop_dash.api.looks import Looks
from taskloop_dash.env import Env
from taskloop_dash.readers import dbruns
from taskloop_dash.readers.beads import Beads, basename
from taskloop_dash.readers.dbruns import StoredRun
from taskloop_dash.readers.logs import Logs
from taskloop_dash.readers.observed import strays_of
from taskloop_dash.readers.records import Records
from taskloop_dash.views.runfacts import Run
from taskloop_dash.views.world import AdrIn, Landing, LookItem, ProjectIn, World

LEDGER_TTL = 5  # seconds the ask ledger, the decisions and the landed runs are kept


def typed_beads(rows: Sequence[dict[str, Any]]) -> list[Bead]:
    out: list[Bead] = []
    for r in rows:
        try:
            out.append(wire.load(Bead, r))
        except ValueError:
            continue  # a row that is not a bead of this contract is not shown
    return out


class Worlds:
    def __init__(self, env: Env, records: Records, beads: Beads, looks: Looks) -> None:
        self.env, self.records, self.beads, self.looks = env, records, beads, looks
        self.logs = Logs(env.config)

    def repos(self) -> dict[str, str]:
        """{immutable project key: registered repo path}."""
        return {loop_key(p): p for p in self.records.repos()}

    def database_error(self) -> str:
        return factorydb.database_error(self.env.config.factory_db(), self.env.clock())

    def project(self, id: str, path: str) -> ProjectIn:
        env = self.env
        raw = self.beads.beads_of(path)
        rows = typed_beads(raw)
        bd_ok_at, bd_error = self.beads.health(path)
        slot_source = self.slot_source(path)
        slots = slots_of(rows, slot_source.host.split(".")[0].lower())  # titled as ident.hostname() names this machine
        states = [s for s in (JsonStore(f, LoopState).get() for f in sorted(env.config.loop_state(loop_key(path)).parent.glob(
            loop_key(path) + ".*.json"))) if s is not None]
        _, items = self.looks.look_items(id, raw)
        looks = [LookItem(bead=i["bead"], title=i["title"], artifacts=tuple(
            self.looks.shot_url(id, s["path"]) for s in i["shots"] if s["role"] == "after"))
            for i in items if i["status"] == "open" and i["bead"]]
        return ProjectIn(id=id, name=basename(path), beads=rows, slots=slots, loops=states, looks=looks, adrs=self.adrs(path),
                         slot_source=slot_source,
                         bd_ok_at=bd_ok_at, bd_error=bd_error,
                         profile_error=self.profile_error(path))

    def slot_source(self, path: str) -> SlotSource:
        """The slot count as the loops read it. Like the red row, the git read is kept while the profile's source files are unchanged (30
        seconds when they cannot be stamped); the folders are listed every time, which spawns nothing."""
        env = self.env
        stamp = env.ports.profile_stamp(path)
        key = "slots:" + path
        hit = env.ttl.peek(key)
        if hit and hit[1][0] == stamp and (stamp is not None or env.clock() - hit[0] < 30):
            found = hit[1][1]
        else:
            found = env.ports.slot_source(path)
            env.ttl.put(key, (stamp, found))
        return replace(found, host=env.host, dirs=env.ports.slot_dirs(found.root) if found.root else found.dirs)

    def profile_error(self, path: str) -> str:
        """Keep the row while its source files are unchanged; unknown sources fall back to 30 seconds."""
        env = self.env
        stamp = env.ports.profile_stamp(path)
        key = "profile:" + path
        hit = env.ttl.peek(key)
        if hit:
            before, row = hit[1]
            if before == stamp and (stamp is not None or env.clock() - hit[0] < 30):
                return row
        row = env.ports.profile_error(path)
        env.ttl.put(key, (stamp, row))
        return row

    def bead_runs(self, path: str, bead: str) -> list[Run]:
        """DB state and log-reader history for only this drawer's runs."""
        now = self.env.clock()
        rows, _ = dbruns.read(self.env.config, now, repo=path, bead=bead)
        return [replace(r.project(now), records=self.logs.records(r.manifest.run)) for r in rows if r.has_log]

    def runs(self, full: tuple[str, str] | None = None, rows: list[StoredRun] | None = None) -> dict[tuple[str, str], list[Run]]:
        """(repo key, bead) -> indexed runs, oldest first, with drawer retention."""
        now = self.env.clock()
        out: dict[tuple[str, str], list[Run]] = {}
        if rows is None:
            rows, _ = dbruns.read(self.env.config, now)
        for row in rows:
            key = (loop_key(row.manifest.repo), row.manifest.bead)
            if row.has_log and (key == full or row.manifest.state.live or row.log_mtime >= now - RETAIN):
                out.setdefault(key, []).append(row.project(now))
        return out

    def asks(self) -> dict[tuple[str, str], Ask]:
        asks, _ = read_snapshot(self.env.config)
        return {(loop_key(a.repo), a.bead): a for a in asks if a.status in LIVE}

    def run_headers(self, now: float, rows: list[StoredRun] | None = None) -> list[RunHeader]:
        """Stage runs need no bead or log to be visible; read their authoritative DB manifest."""
        projects = {path: project for project, path in self.repos().items()}
        out: list[RunHeader] = []
        parks = self.records.parks()
        if rows is None:
            rows, _ = dbruns.read(self.env.config, now)
        for row in reversed(rows):
            m = row.manifest
            if not m.mode or m.repo not in projects or (not m.state.live and (m.ended or m.started) < now - RETAIN):
                continue
            state = RunState.LOST if shown(m, now) is Liveness.LOST else m.state
            park = parks.get(m.bead)
            out.append(RunHeader(run=m.run, project=projects[m.repo], mode=m.mode, owner=m.owner, session=m.session,
                                 state=state, started=m.started, ended=m.ended, reason=m.reason, bead=m.bead,
                                 branch=m.branch or m.sha[:8] or basename(m.worktree or m.repo),
                                 retry_at=park.retry_at if park and park.run == m.run and not m.state.live else 0.0))
        return out

    def leases(self, now: float, rows: list[StoredRun] | None = None) -> list[ResourceLease]:
        """Join a live lease's pid to its run manifest; the holder hint itself has no run id."""
        if rows is None:
            rows, _ = dbruns.read(self.env.config, now)
        runs = [r.manifest for r in rows if shown(r.manifest, now) is Liveness.LIVE]
        projects = {path: project for project, path in self.repos().items()}
        out: list[ResourceLease] = []
        for name, rec in self.env.ports.resource_holders(self.env.config):
            run = next((r for r in reversed(runs) if r.pid == rec.pid), None)
            out.append(ResourceLease(name=name, holder=rec.holder, since=rec.t, run=run.run if run else "",
                                     project=projects.get(run.repo, "") if run else ""))
        return out

    def adrs(self, path: str) -> list[AdrIn]:
        """The repo's decisions in force, each with its reuse count (plans that cited it) and when last."""
        def load() -> list[AdrIn]:
            store = AdrStore.at(self.env.config, path)
            used = store.reuses()
            return [AdrIn(a, used.get(a.id, (0, 0.0))[0], used.get(a.id, (0, 0.0))[1] or None) for a in store.in_force()]
        return self.env.ttl.get("v2adrs:" + path, LEDGER_TTL, load)

    def ledger(self) -> list[LedgerEntry]:
        return self.env.ttl.get("v2ledger", LEDGER_TTL, lambda: read_snapshot(self.env.config)[1])

    def landings(self) -> list[Landing]:
        """The runs of the traces that landed: when each ended and how many plans it redid."""
        def load() -> list[Landing]:
            return [Landing(t.ended, t.stats.replans) for t in self.records.traces().runs.values() if t.outcome is Outcome.LANDED]
        return self.env.ttl.get("v2landings", LEDGER_TTL, load)

    def world(self, full: tuple[str, str] | None = None) -> World:
        env = self.env
        now = env.clock()
        rows, database_error = dbruns.read(env.config, now)
        try:
            asks, ledger = read_snapshot(env.config)
        except factorydb.DatabaseError as error:
            asks, ledger = list[Ask](), list[LedgerEntry]()
            database_error = f"database unavailable: {error}; run tl doctor --reindex"
        runs = self.runs(full, rows)
        paths = self.repos()
        projects = [self.project(i, p) for i, p in paths.items()]
        names = Counter(p.name for p in projects)
        projects = [replace(p, name=f"{p.name} ({Path(paths[p.id]).parent})") if names[p.name] > 1 else p for p in projects]
        events = self.records.events()
        projects = [replace(p, strays=strays_of(p.beads, p.slots, {b: r for (key, b), r in runs.items() if key == p.id}, now),
                            events=[e for e in events if e.repo == paths[p.id]]) for p in projects]
        return World(now=now, host=env.host, version=env.version, projects=projects, runs=runs,
                     asks={(loop_key(a.repo), a.bead): a for a in asks if a.status in LIVE},
                     run_headers=self.run_headers(now, rows), leases=self.leases(now, rows), database_error=database_error,
                     status=StatusStore(env.config).get(), ledger=ledger, landings=self.landings(),
                     parks=self.records.parks(), net_pauses=self.records.net_pauses(), skipped_traces=self.records.traces().skipped)

    def comments(self, path: str, bead: BeadId) -> list[Comment]:
        return [Comment(author=str(c.get("author") or ""), text=str(c.get("text") or ""), created_at=str(c.get("created_at") or ""))
                for c in self.beads.comments(path, bead)]

    def live_events(self, run: Run | None) -> list[LiveEvent]:
        """The typed events of the newest call file of a run that still writes (delegate's per-call live files)."""
        return self.logs.console(run.name) if run else []

    def stage_events(self, runs: Sequence[Run]) -> dict[str, dict[int, Sequence[LiveEvent]]]:
        """Delegate live lines keep their own file reader; they are not run history."""
        return {run.name: dict(self.logs.calls(run.name)) for run in runs}
