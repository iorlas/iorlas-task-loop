"""The engine-log views over one FileCache: the facts a task row needs."""

import dataclasses
from typing import Any

from taskloop.contracts.locator import RunBundle
from taskloop.contracts.runlife import shown
from taskloop_dash import jsonl
from taskloop_dash.cache import FileCache
from taskloop_dash.views.runfacts import Run, run_of


class RunLogs:
    def __init__(self, files: FileCache) -> None:
        self.files = files
        self.runs = FileCache(limit=5000)  # path -> (records with Beats, the Run made when they were read), for the v2 builders

    def typed_run(self, b: RunBundle, now: float) -> Run:
        """The typed facts of one run, its records parsed once per change of the file; its state is the manifest's (lost when the
        reconciler would mark it so now: displayed, never written), read every time."""
        def load(p: str) -> tuple[list[Any], Run]:
            recs = jsonl.records(p)
            return recs, run_of(b.run, recs, now)
        _, made = self.runs.get(str(b.log), load, ([], run_of(b.run, [], now)))
        return dataclasses.replace(made, life=shown(b.manifest, now))
