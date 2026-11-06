"""Authoritative run manifests and atomic changes in factory.db."""

import json
from collections.abc import Callable, Generator
from contextlib import contextmanager

from taskloop.contracts import attemptrows, factorydb, wire
from taskloop.contracts.ids import loop_key
from taskloop.contracts.paths import ConfigDir
from taskloop.contracts.run import RunManifest


class StaleRevision(ValueError):
    """The caller's revision no longer names the current row."""


def manifest_of(text: str, run: str) -> RunManifest:
    """The manifest in a row. Forward-readable: a top-level key this tl does not know (a newer writer's) is read past, not an error,
    so one newer row cannot block every landing; a write back keeps only the keys this tl knows. A row that still does not
    validate raises a DatabaseError that says so (the run and the msgspec reason), not a bare 'unreadable'."""
    try:
        body = json.loads(text)
        if isinstance(body, dict):
            known = {"v", *wire.names(RunManifest)}
            body = {k: v for k, v in body.items() if k in known}
        return wire.load(RunManifest, body)
    except (ValueError, TypeError) as error:
        raise factorydb.DatabaseError(f"run manifest {run} does not validate: {error}") from error


class RunRows:
    """Operations reuse a thread's writer; short transactions never span external work."""

    def __init__(self, cfg: ConfigDir) -> None:
        self.cfg = cfg

    @contextmanager
    def transaction(self) -> Generator[factorydb.sqlite3.Connection]:
        self.cfg.root.mkdir(parents=True, exist_ok=True)
        con = factorydb.shared_rw(self.cfg.factory_db())
        if con is None:
            raise factorydb.DatabaseError("factory.db unavailable for run state")
        with factorydb.begin_immediate(con):
            yield con

    def get(self, run: str) -> RunManifest | None:
        if not self.cfg.factory_db().exists():
            return None
        with self.transaction() as con:
            return self.read(con, run)

    @staticmethod
    def read(con: factorydb.sqlite3.Connection, run: str) -> RunManifest | None:
        row = con.execute("SELECT manifest FROM run WHERE run=?", (run,)).fetchone()
        return manifest_of(row[0], run) if row else None

    def put(self, manifest: RunManifest, expect_rev: int | None = None) -> None:
        with self.transaction() as con:
            self.write(con, manifest, expect_rev)

    def write(self, con: factorydb.sqlite3.Connection, m: RunManifest, expect_rev: int | None = None,
              *, attempt_started: float | None = None) -> None:
        if not con.in_transaction:
            raise ValueError("run writes require a caller-owned transaction")
        if expect_rev is not None:
            row = con.execute("SELECT rev FROM run WHERE run=?", (m.run,)).fetchone()
            if row is None or row[0] != expect_rev:
                raise StaleRevision(m.run)
        cols = ("run", "repo", "repo_key", "bead", "mode", "owner", "session", "loop", "worktree", "branch", "sha",
                "state", "reason", "started", "ended", "next_step", "bundle", "manifest", "outcome", "why")
        finish = m.finish
        values = (m.run, m.repo, loop_key(m.repo), m.bead, m.mode, m.owner, m.session, m.loop, m.worktree, m.branch, m.sha,
                  m.state.value, m.reason, m.started, m.ended, m.next_step.value if m.next_step else None,
                  str(self.cfg.run_dir(m.run)), json.dumps(wire.dump(m), indent=1, ensure_ascii=False) + "\n",
                  finish.outcome.value if finish else None,
                  finish.why if finish else None)
        con.execute(f"INSERT INTO run ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)}) "
                    f"ON CONFLICT(run) DO UPDATE SET {','.join(c + '=excluded.' + c for c in cols[1:])}, rev=run.rev+1", values)
        attemptrows.ensure(con, m, attempt_started)

    def change(self, run: str, change: Callable[[RunManifest], RunManifest]) -> None:
        with self.transaction() as con:
            old = self.read(con, run)
            if old is not None:
                new = change(old)
                if new != old:
                    self.write(con, new)

    def _select(self, where: str = "", params: tuple[str, ...] = ()) -> list[RunManifest]:
        if not self.cfg.factory_db().exists():
            return []
        with self.transaction() as con:
            rows = con.execute("SELECT manifest, run FROM run " + where + " ORDER BY started, run", params).fetchall()
            return [manifest_of(row[0], row[1]) for row in rows]

    def all(self) -> list[RunManifest]:
        return self._select()

    def of_bead(self, bead: str, repo: str | None = None) -> list[RunManifest]:
        return self._select("WHERE bead=?" + (" AND repo=?" if repo is not None else ""),
                            (bead, repo) if repo is not None else (bead,))

    def of_repo(self, repo: str) -> list[RunManifest]:
        return self._select("WHERE repo=?", (repo,))

    def snapshot(self, run: str) -> tuple[str, int] | None:
        """Wire bytes and revision, useful to prove a reader did not mutate state."""
        with self.transaction() as con:
            row = con.execute("SELECT manifest,rev FROM run WHERE run=?", (run,)).fetchone()
            return (row[0], row[1]) if row else None
