"""Authoritative run manifests and atomic changes in factory.db."""

import json
import os
from collections.abc import Callable, Generator
from contextlib import contextmanager
from pathlib import Path

from taskloop.contracts import attemptrows, factorydb, wire
from taskloop.contracts.guard import guard
from taskloop.contracts.ids import loop_key
from taskloop.contracts.paths import ConfigDir, RunFiles
from taskloop.contracts.run import DoneMemo, RunManifest
from taskloop.contracts.stores import JsonStore

_IMPORTED: set[tuple[int, str]] = set()


class StaleRevision(ValueError):
    """The caller's revision no longer names the current row."""


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
        try:
            return wire.load(RunManifest, row[0]) if row else None
        except (ValueError, TypeError) as error:
            raise factorydb.DatabaseError(f"unreadable run manifest: {run}") from error

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
            rows = con.execute("SELECT manifest FROM run " + where + " ORDER BY started, run", params).fetchall()
            try:
                return [wire.load(RunManifest, row[0]) for row in rows]
            except (ValueError, TypeError) as error:
                raise factorydb.DatabaseError("unreadable run manifests") from error

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


def import_legacy(cfg: ConfigDir) -> int:
    """Import missing rows once; retained legacy files are rollback copies only."""
    try:
        entries = list(cfg.runs_dir().iterdir())
    except FileNotFoundError:
        return 0
    store = RunRows(cfg)
    count = 0
    with store.transaction() as con:
        known = {row[0] for row in con.execute("SELECT run FROM run")}
        for entry in entries:
            if not entry.is_dir():
                continue
            m = store.read(con, entry.name) if entry.name in known else JsonStore(cfg.run_manifest(entry.name), RunManifest).get()
            if m is not None and m.run == entry.name:
                if entry.name not in known:
                    store.write(con, m)
                    count += 1
                else:
                    attemptrows.ensure(con, m)
                _import_steps(con, cfg, m)
    return count


def _import_steps(con: factorydb.sqlite3.Connection, cfg: ConfigDir, m: RunManifest) -> None:
    files = RunFiles(cfg.run_dir(m.run))
    for path in (files.done_memo(), files.legacy_done_memo()):
        _import_step_file(con, path, m)


def _import_step_file(con: factorydb.sqlite3.Connection, path: Path, m: RunManifest) -> None:
    """A source marker prevents rereading even torn or empty legacy memos."""
    if con.execute("SELECT 1 FROM source WHERE path=?", (str(path),)).fetchone():
        return
    if con.execute("SELECT 1 FROM step WHERE run=? LIMIT 1", (m.run,)).fetchone() is None:
        memo = JsonStore(path, DoneMemo).get()
        for key, entry in (memo.done.items() if memo else ()):
            con.execute("INSERT INTO step (run,key,try,attempt,status,started,ended,input_digest,result,calls) "
                        "VALUES (?,?,1,?,'done',?,?,?,?,0)",
                        (m.run, key, m.attempts, m.started, m.started, entry.sha, json.dumps(wire.dump(entry))))
    con.execute("INSERT INTO source (path,family,seen) VALUES (?,'step',?)", (str(path), m.started))


def import_once(cfg: ConfigDir) -> None:
    """One directory listing per config root per process, independent of locator count."""
    key = (os.getpid(), str(cfg.root.resolve()))
    if key in _IMPORTED:
        return
    if not cfg.runs_dir().exists():
        _IMPORTED.add(key)
        return
    with guard(cfg.lock_record("run-import", "legacy")):
        if key not in _IMPORTED:
            import_legacy(cfg)
            _IMPORTED.add(key)
