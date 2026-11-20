"""Run with installed Python -I; explicit NEW output directory, no external services."""
import argparse
import importlib.metadata
import json
import platform
import runpy
import statistics
from collections import Counter
import time
import tracemalloc
from pathlib import Path

from sqlite_store import Store
from taskloop.attempt_store import AttemptStore
from taskloop.attempt_types import AttemptKey
from taskloop.check_store import CheckStore
from taskloop.land_store import LandStore
from taskloop.hold_store import HoldStore
from taskloop.attempt_status import Listed, StatusPorts, list_attempts
from taskloop.dash_board import BoardPorts, build_board
from taskloop.evidence_files import EvidenceFiles
from taskloop.dash_model import Board
from taskloop.factory_schema import SCHEMA
from taskloop.operations import Failed

FixtureStore = runpy.run_path(str(Path(__file__).with_name('fixture_store.py')))['FixtureStore']


class Tracker:
    def ready(self): return ()
    def titles(self, ids): return {}
    def notice(self): return None


def sample(operation, statements, samples):
    operation()  # One warm-up, no OS cache eviction.
    raw, counts, row_counts, columns = [], [], [], {}
    for _ in range(samples):
        statements.clear()
        start = time.perf_counter()
        result = operation()
        raw.append(time.perf_counter() - start)
        assert not isinstance(result, Failed), result
        if isinstance(result, Listed):
            assert all(row.next != "unknown" for row in result.attempts), "Invalid synthetic status"
        if isinstance(result, Board):
            assert all(card.status != "unknown" for card in result.tasks), "Invalid synthetic board"
            row_counts.append(len(result.tasks))
            columns = dict(Counter(card.column for card in result.tasks))
        elif isinstance(result, Listed):
            row_counts.append(len(result.attempts))
        elif isinstance(result, (tuple, dict)):
            row_counts.append(len(result))
        else:
            row_counts.append(int(result is not None))
        counts.append(len(statements))
        del result
    groups = {name: sum(name in query.lower() for query in statements)
              for name in ('checks_attempt', 'check_result', 'land_candidate', 'task_hold', 'setup_run', 'execution')}
    tracemalloc.start()
    operation()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return dict(seconds=raw, median=statistics.median(raw), p95=sorted(raw)[-1], statements=counts, returned_rows=row_counts, columns=columns, query_groups=groups, peak_bytes=peak)


def opens(path, samples):
    shared = Store(SCHEMA)
    def opened(store, readonly=False):
        start = time.perf_counter()
        con = store.open_ro(path) if readonly else store.open_rw(path)
        elapsed = time.perf_counter() - start
        assert con is not None
        con.close()
        return elapsed
    return dict(same_store=[opened(shared) for _ in range(samples)],
                distinct_stores=[opened(Store(SCHEMA)) for _ in range(samples)],
                readonly=[opened(Store(SCHEMA), True) for _ in range(samples)])


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--count', type=int, required=True)
    parser.add_argument('--tasks', type=int, required=True)
    parser.add_argument('--mixed', action='store_true')
    parser.add_argument('--samples', type=int, default=3)
    args = parser.parse_args()
    if not 0 < args.tasks <= args.count or args.samples < 1:
        parser.error('Require 0 < tasks <= count and positive samples')
    if args.output.exists():
        parser.error("Synthetic output directory already exists; preserving it")
    fixture = FixtureStore(args.output, args.count, args.tasks, args.mixed)
    store = AttemptStore(lambda: fixture.con)
    reads = StatusPorts(store, lambda _: 'gone', lambda: 200., lambda _: None, lambda: 'synthetic')
    board = BoardPorts(reads, EvidenceFiles(args.output / 'absent-evidence'), Tracker())
    operations = dict(all=lambda: store.attempts(), backlog=lambda: store.attempts('b0'),
        task=lambda: store.attempts(task_id='t0'), scoped=lambda: store.attempts('b0', 't0'),
        agent_slot=lambda: store.slot_path('a0000000'), check_slot=lambda: store.slot_path(f'c{2*args.tasks:07}'),
        listing=lambda: list_attempts(reads), board=lambda: build_board(board))
    check_id = f'c{2*args.tasks:07}'
    check_key = AttemptKey(check_id, check_id, 1)
    checks = CheckStore(lambda: fixture.con)
    lands = LandStore(lambda: fixture.con)
    holds = HoldStore(lambda: fixture.con)
    operations.update(checks_history=lambda: checks.of_attempt(f'a{2*args.tasks:07}'),
        checks_results=lambda: checks.results(check_key), land=lambda: lands.latest(check_id),
        holds=lambda: holds.of_attempts(tuple(f'a{i:07}' for i in range(args.count-args.tasks, args.count))))
    if hasattr(store, 'current_attempts'):
        operations['current'] = store.current_attempts
    result = dict(revision=args.revision, python=platform.python_version(), host=platform.uname()._asdict(),
        mixed=args.mixed, package=importlib.metadata.version('iorlas-task-loop'), count=args.count, tasks=args.tasks,
        samples=args.samples, warmups=1, filesystem_cold=False, facts=fixture.facts(), plans=fixture.plans(),
        opens=opens(fixture.path, args.samples),
        timings={name: sample(op, fixture.statements, args.samples) for name, op in operations.items()})
    (args.output / 'results.json').write_text(json.dumps(result, indent=2) + '\n')
    fixture.store.close_shared()
    print(args.output / 'results.json')


if __name__ == '__main__':
    main()
