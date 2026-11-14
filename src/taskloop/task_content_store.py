"""Immutable task-content evidence owned by an admitted plan attempt."""

import sqlite3
from collections.abc import Callable

from taskloop.attempt_reads import StoreUnavailable
from taskloop.task_content import TaskContentDigest


class TaskContentStore:
    def __init__(self, connect: Callable[[], sqlite3.Connection | None]) -> None:
        self.connect = connect

    @staticmethod
    def insert(con: sqlite3.Connection, attempt_id: str, evidence: TaskContentDigest) -> None:
        """Join the caller's admission transaction; duplicate evidence is never overwritten."""
        con.execute("INSERT INTO task_content (attempt_id,digest) VALUES (?,?)", (attempt_id, evidence.value))

    def read(self, attempt_id: str) -> TaskContentDigest | None:
        con = self.connect()
        if con is None:
            raise StoreUnavailable("Task-content evidence store is unavailable")
        row = con.execute("SELECT digest FROM task_content WHERE attempt_id=?", (attempt_id,)).fetchone()
        return None if row is None else TaskContentDigest(value=row[0])
