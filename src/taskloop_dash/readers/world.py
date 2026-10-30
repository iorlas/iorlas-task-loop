"""The v2 World read from this machine: registered repos, bd (the cached list, typed), the slot beads, the loops' state files, the
owner-look items, the engine logs as typed runs, the live asks, the ask ledger, the decisions in force, the landed runs and
delegate's lane status. Read only; a poll never runs bd: the bead list and the look items
keep to their TTLs."""

import socket
from collections.abc import Sequence
from typing import Any

from taskloop.contracts import wire
from taskloop.contracts.adrs import AdrStore
from taskloop.contracts.ask import Ask
from taskloop.contracts.bead import Bead, Comment
from taskloop.contracts.delegate import LiveEvent
from taskloop.contracts.enums import Outcome
from taskloop.contracts.ids import BeadId
from taskloop.contracts.ledger import LedgerEntry
from taskloop.contracts.loop import LoopState
from taskloop.contracts.stores import AskStore, JsonStore, LedgerStore, StatusStore
from taskloop_dash import jsonl
from taskloop_dash.api.looks import Looks
from taskloop_dash.env import Env
from taskloop_dash.readers.beads import Beads, basename
from taskloop_dash.readers.loops import loop_key
from taskloop_dash.readers.records import Records
from taskloop_dash.readers.runlogs import RunLogs
from taskloop_dash.views import names
from taskloop_dash.views.runfacts import Run
from taskloop_dash.views.world import AdrIn, Landing, LookItem, ProjectIn, World

LIST_TTL = 5  # seconds the typed bead list is kept (readers.beads keeps bd's own answer longer)
DETAIL_TTL = 15  # seconds one bead's comments are kept
LEDGER_TTL = 5  # seconds the ask ledger, the decisions and the landed runs are kept


def typed_beads(rows: Sequence[dict[str, Any]]) -> list[Bead]:
    out: list[Bead] = []
    for r in rows:
        try:
            out.append(wire.load(Bead, r))
        except ValueError:
            continue  # a row that is not a bead of this contract is not shown
    return out


def live_event(data: object) -> LiveEvent:
    """A live-file line as its typed event (`k` names the kind; the file carries no `v`), as the runner reads it."""
    if not isinstance(data, dict):
        raise ValueError("not a live event")
    return wire.load(LiveEvent, {**{k: v for k, v in data.items() if k != "k"}, "kind": data.get("k"), "v": 1})


class Worlds:
    def __init__(self, env: Env, records: Records, beads: Beads, runlogs: RunLogs, looks: Looks) -> None:
        self.env, self.records, self.beads, self.runlogs, self.looks = env, records, beads, runlogs, looks

    def repos(self) -> dict[str, str]:
        """{project id: repo path}: a project is a registered repo, named by its folder."""
        return {basename(p): p for p in self.records.repos()}

    def project(self, id: str, path: str) -> ProjectIn:
        env = self.env
        rows = env.ttl.get("v2beads:" + path, LIST_TTL, lambda: typed_beads(self.beads.beads_of(path)))
        slots = typed_beads(env.ports.slot_beads(path))
        states = [s for s in (JsonStore(f, LoopState).read() for f in sorted(env.config.loop_state(loop_key(path)).parent.glob(
            loop_key(path) + ".*.json"))) if s is not None]
        _, items = self.looks.look_items(path)
        looks = [LookItem(bead=i["bead"], title=i["title"], shots=tuple(
            self.looks.shot_url(basename(path), s["path"]) for s in i["shots"] if s["role"] == "after"))
            for i in items if i["status"] == "open" and i["bead"]]
        return ProjectIn(id=id, name=id, beads=rows, slots=slots, loops=states, looks=looks, adrs=self.adrs(path))

    def runs(self, full: BeadId | None = None) -> dict[str, list[Run]]:
        """bead -> its runs, oldest first: the retained logs, and all of `full`'s."""
        now = self.env.clock()
        out: dict[str, list[Run]] = {}
        for bead, paths in self.records.engine_logs().items():
            out[bead] = [self.runlogs.typed_run(p, now) for p in paths]
        if full:
            out[full] = [self.runlogs.typed_run(p, now) for p in self.records.engine_logs(retain=False).get(full, [])]
        return {b: r for b, r in out.items() if r}

    def asks(self) -> dict[str, Ask]:
        return {a.bead: a for a in AskStore.at(self.env.config).live()}

    def adrs(self, path: str) -> list[AdrIn]:
        """The repo's decisions in force, each with its reuse count (plans that cited it) and when last."""
        def load() -> list[AdrIn]:
            store = AdrStore.at(self.env.config, path)
            used = store.reuses()
            return [AdrIn(a, used.get(a.id, (0, 0.0))[0], used.get(a.id, (0, 0.0))[1] or None) for a in store.in_force()]
        return self.env.ttl.get("v2adrs:" + path, LEDGER_TTL, load)

    def ledger(self) -> list[LedgerEntry]:
        return self.env.ttl.get("v2ledger", LEDGER_TTL, lambda: [i.rec for i in LedgerStore(self.env.config).read_from(0).items])

    def landings(self) -> list[Landing]:
        """The runs of the traces that landed: when each ended and how many plans it redid."""
        def load() -> list[Landing]:
            return [Landing(t.ended, t.stats.replans) for t in self.records.traces().runs.values() if t.outcome is Outcome.LANDED]
        return self.env.ttl.get("v2landings", LEDGER_TTL, load)

    def world(self, full: BeadId | None = None) -> World:
        env = self.env
        return World(now=env.clock(), host=socket.gethostname(), version=env.version,
                     projects=[self.project(i, p) for i, p in self.repos().items()], runs=self.runs(full), asks=self.asks(),
                     status=StatusStore(env.config).read(), ledger=self.ledger(), landings=self.landings(),
                     skipped_traces=self.records.traces().skipped)

    def comments(self, path: str, bead: BeadId) -> list[Comment]:
        def load() -> list[Comment]:
            return [Comment(author=str(c.get("author") or ""), text=str(c.get("text") or ""), created_at=str(c.get("created_at") or ""))
                    for c in self.beads.comments(path, bead)]
        return self.env.ttl.get(f"v2comments:{path}:{bead}", DETAIL_TTL, load)

    def live_events(self, run: Run | None) -> list[LiveEvent]:
        """The typed events of the newest call file of a run that still writes (delegate's per-call live files)."""
        if run is None or not names.is_run_name(run.name):
            return []
        folder = self.env.config.live_dir(run.name)
        try:
            files = sorted(folder.glob("*.jsonl"), key=lambda f: f.stat().st_mtime)
        except OSError:
            return []
        return jsonl.records(str(files[-1]), decode=live_event) if files else []
