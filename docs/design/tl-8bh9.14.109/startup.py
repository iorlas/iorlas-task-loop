"""Fresh-process startup observations on a retained dataset made by measure.py only."""
import argparse
import json
import sqlite3
import time
from pathlib import Path

from sqlite_store import Store
from taskloop.cli_composition import open_land
from taskloop.composition import (open_admission, open_advance, open_attempts, open_chain, open_checking,
    open_checks_admission, open_verifier)
from taskloop.factory_schema import SCHEMA
from taskloop.git_views import GitViews
from taskloop.operations import Failed

EVENTS = []


class Observed(sqlite3.Connection):
    def execute(self, sql, parameters=()):
        start = time.perf_counter()
        result = super().execute(sql, parameters)
        if sql.upper() == 'PRAGMA QUICK_CHECK':
            EVENTS.append(time.perf_counter()-start)
        return result


def command(path, artifacts, stores, registration=None):
    views = GitViews(30)
    operations = [open_admission(path, artifacts, views, stores[0]), open_chain(path, artifacts, stores[1]),
        open_advance(path, artifacts, views, stores[2]), open_checks_admission(path, views, stores[3]),
        open_verifier(path, stores[4], views).store]
    for operation in operations:
        assert operation.connect() is not None
    with open_land(path, artifacts, views, stores[5], registration) as land:
        assert not isinstance(land, Failed)
        assert land.work.store.connect() is not None
        # A land that registers a validation command needs its bounded writer too.
        assert land.work.setups.registering.connect() is not None


def lifetime(path, artifacts, mode, reuse):
    shared, bounded, stores, connections = Store(SCHEMA), Store(SCHEMA), [], []
    try:
        if mode in ('command', 'rounds'):
            for _ in range(3 if mode == 'rounds' else 1):
                selected = [shared] * 6 if reuse else [Store(SCHEMA) for _ in range(6)]
                stores.extend(selected)
                command(path, artifacts, selected, bounded if reuse else None)
        elif mode == 'entry':
            app = open_attempts(path, artifacts, GitViews(30))
            connections = [app.store.connect(), app.registration_store.connect()]
        else:
            work = open_checking(path, artifacts, GitViews(30))
            connections = [work.store.connect(), work.setups.registering.connect()]
        assert all(con is not None for con in connections)
    finally:
        bounded.close_shared()
        shared.close_shared()
        for store in stores:
            store.close_shared()
        for con in connections:
            if con is not None:
                con.close()


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--opens-only', action='store_true')
    args = parser.parse_args()
    metadata = json.loads((args.dataset / 'results.json').read_text())
    assert metadata['facts']['rows']['attempt'] == metadata['count']
    assert metadata['facts']['schema_version'] == SCHEMA.version
    assert all((args.dataset / f'evidence-{i}.txt').read_bytes() == b'x' * 256 for i in range(4))
    path = args.dataset / 'synthetic.db'
    args.output.mkdir(parents=True, exist_ok=False)
    original = sqlite3.connect
    def observed(*a, **kw):
        return original(*a, **kw, factory=Observed)
    sqlite3.connect = observed
    result = dict(schema=SCHEMA.version, filesystem_cold=False, samples=3)
    first = Store(SCHEMA)
    result['opens'] = {}
    # First item is process-cold; repeats and other Store objects are process-warm.
    for label in ('first_and_same_store', 'distinct_stores', 'readonly'):
        samples = []
        for _ in range(3):
            EVENTS.clear()
            store = first if label == 'first_and_same_store' else Store(SCHEMA)
            start = time.perf_counter()
            con = store.open_ro(path) if label == 'readonly' else store.open_rw(path)
            assert con is not None
            samples.append(dict(seconds=time.perf_counter()-start, quick_check_seconds=EVENTS.copy()))
            con.close()
        result['opens'][label] = samples
    for mode in (() if args.opens_only else ('command', 'entry', 'checks_entry', 'rounds')):
        result[mode] = {}
        for reuse in (False, True):
            samples = []
            for _ in range(3):
                EVENTS.clear()
                start = time.perf_counter()
                lifetime(path, args.output / 'absent-evidence', mode, reuse)
                samples.append(dict(seconds=time.perf_counter()-start, quick_check_seconds=EVENTS.copy()))
            result[mode]['reuse' if reuse else 'separate'] = samples
    (args.output / 'startup.json').write_text(json.dumps(result, indent=2)+'\n')
    print(args.output / 'startup.json')


if __name__ == '__main__':
    main()
