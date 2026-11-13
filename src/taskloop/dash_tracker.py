"""The dashboard's tracker reads: the tracker's task data turned into the page's model, bounded and cached, because each
read is a `bd` call. A failed read keeps the last good answer (or none) and says so in `notice`; a task's title is read
once. A task's fields raise when they cannot be read and nothing was read before (the drawer says so). Display only."""

import threading
from collections.abc import Callable
from pathlib import Path

from taskloop.dash_model import Comment, Fields, Ready
from taskloop.task import TaskInspectionError
from taskloop.tracker_client import tracker_comments, tracker_facts, tracker_ready_listing, tracker_titles

READY_TTL = 10.0  # seconds a ready listing stands
TASK_TTL = 5.0  # seconds one task's fields and comments stand


class CachedTracker:
    def __init__(self, label: str, root: Path, clock: Callable[[], float]) -> None:
        self.label, self.root, self.clock = label, root, clock
        self._ready: tuple[float, tuple[Ready, ...]] | None = None
        self._titles: dict[str, str] = {}
        self._tasks: dict[str, tuple[float, tuple[Fields, tuple[Comment, ...]] | None]] = {}
        self._problem: str | None = None
        self._lock = threading.Lock()  # a page, the poller and several drawers read at once: one `bd` read at a time

    def notice(self) -> str | None:
        return self._problem

    def ready(self) -> tuple[Ready, ...]:
        with self._lock:
            return self._read_ready()

    def titles(self, task_ids: tuple[str, ...]) -> dict[str, str]:
        if all(each in self._titles for each in task_ids):  # known titles never wait for a `bd` read in flight
            return {each: self._titles[each] for each in task_ids}
        with self._lock:
            return self._read_titles(task_ids)

    def fields(self, task_id: str) -> tuple[Fields, tuple[Comment, ...]] | None:
        with self._lock:
            return self._read_fields(task_id)

    def _read_ready(self) -> tuple[Ready, ...]:
        now = self.clock()
        if self._ready is None or now - self._ready[0] > READY_TTL:
            try:
                listed = tuple(Ready(each.task_id, each.title, each.created_at) for each in tracker_ready_listing(self.label, self.root))
            except TaskInspectionError as error:
                self._problem = f"Tracker unavailable: {error}"
                return () if self._ready is None else self._ready[1]
            self._ready, self._problem = (now, listed), None
        return self._ready[1]

    def _read_titles(self, task_ids: tuple[str, ...]) -> dict[str, str]:
        missing = tuple(each for each in task_ids if each not in self._titles)
        if missing:
            try:
                self._titles |= tracker_titles(missing, self.root)
            except TaskInspectionError as error:
                self._problem = f"Tracker unavailable: {error}"
        return {each: self._titles[each] for each in task_ids if each in self._titles}

    def _read_fields(self, task_id: str) -> tuple[Fields, tuple[Comment, ...]] | None:
        now = self.clock()
        kept = self._tasks.get(task_id)
        if kept is not None and now - kept[0] <= TASK_TTL:
            return kept[1]
        try:
            facts = tracker_facts(task_id, self.root)
            comments = tracker_comments(task_id, self.root) if facts is not None else ()
        except TaskInspectionError as error:
            self._problem = f"Tracker unavailable: {error}"
            if kept is None:
                raise
            return kept[1]
        found = None if facts is None else (
            Fields(f"P{facts.priority}" if facts.priority is not None else "none", facts.labels, f"task/{facts.task_id}", facts.assignee,
                   facts.created_at, facts.updated_at, facts.dependencies, facts.description, facts.acceptance, facts.design, facts.notes),
            tuple(Comment(each.author, each.at, each.text) for each in comments),
        )
        self._tasks[task_id] = (now, found)
        return found
