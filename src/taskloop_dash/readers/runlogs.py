"""The engine-log views over one FileCache: the facts a task row needs."""

import dataclasses
from typing import Any

from taskloop.contracts.runlife import Liveness, liveness
from taskloop_dash import jsonl
from taskloop_dash.cache import FileCache
from taskloop_dash.views import names
from taskloop_dash.views.runfacts import Run, run_of


class RunLogs:
    def __init__(self, files: FileCache) -> None:
        self.files = files
        self.life = FileCache()  # the same logs with their Beat records: what runlife.liveness reads
        self.runs = FileCache(limit=5000)  # path -> (records with Beats, the Run made when they were read), for the v2 builders

    def liveness(self, path: str, now: float) -> Liveness:
        return liveness(self.life.get(path, lambda p: jsonl.records(p, beats=True), []), now)

    def typed_run(self, path: str, now: float) -> Run:
        """The typed facts of one run, its records parsed once per change of the file; liveness is read against `now` every time."""
        def load(p: str) -> tuple[list[Any], Run]:
            recs = jsonl.records(p, beats=True)
            return recs, run_of(names.run_name(p), recs, now)
        recs, made = self.runs.get(path, load, ([], run_of(names.run_name(path), [], now)))
        return dataclasses.replace(made, life=liveness(recs, now))
