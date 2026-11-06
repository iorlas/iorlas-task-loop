"""Marker-gated bd ingestion, one registered repository per indexer pass."""

import sqlite3
from collections.abc import Callable
from pathlib import Path

from taskloop.contracts import beadrows, factorydb
from taskloop.contracts.beadsport import BdFailure, BeadQuery, Beads
from taskloop.contracts.ids import loop_key

MAX_AGE = 60


class BeadPass:
    """Persist successes and failed attempts; an unchanged marker survives process restarts."""

    def __init__(self, repos: Callable[[], list[str]], store_of: Callable[[str], Beads]) -> None:
        self.repos, self.store_of = repos, store_of
        self.cursor = 0

    def pass_once(self, con: sqlite3.Connection, now: float, *, force: bool = False) -> None:
        repos = self.repos()
        if repos:
            repo = repos[self.cursor % len(repos)]
            self.cursor += 1
            self.refresh(con, repo, now, force=force)

    def refresh(self, con: sqlite3.Connection, repo: str, now: float, *, force: bool = False) -> None:
        key = loop_key(repo)
        try:
            marker = (Path(repo) / ".beads" / "last-touched").stat().st_mtime_ns
        except FileNotFoundError:
            marker = None
        except OSError as error:
            with factorydb.begin_immediate(con):
                beadrows.set_error(con, key, str(error), now)
            return
        before, ok_at, bd_error, attempted = beadrows.observation(con, key)
        unchanged = marker is not None and marker == before and ok_at is not None and not bd_error
        recent = marker is None and attempted is not None and now - attempted < MAX_AGE
        if not force and (unchanged or recent):
            return
        try:
            rows = [beadrows.row_of(bead) for bead in self.store_of(repo).find(BeadQuery(include_closed=True))]
        except (BdFailure, ValueError, OSError) as error:
            with factorydb.begin_immediate(con):
                beadrows.set_error(con, key, str(error) or type(error).__name__, now)
        else:
            with factorydb.begin_immediate(con):
                beadrows.replace_repo(con, key, rows, marker, now)
