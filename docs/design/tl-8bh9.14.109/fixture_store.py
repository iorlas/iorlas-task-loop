"""Opt-in synthetic database owner. All paths are beneath a new output directory."""
import json
import sqlite3
from pathlib import Path

from sqlite_store import Store
from taskloop.factory_schema import SCHEMA

SHA = 'a' * 40
DIGEST = '0' * 64


class FixtureStore:
    def __init__(self, root: Path, count: int, tasks: int, mixed: bool = False):
        root.mkdir(parents=True, exist_ok=False)
        self.mixed = mixed
        self.path = root / 'synthetic.db'
        self.store = Store(SCHEMA)
        self.con = self.store.shared_rw(self.path)
        assert self.con is not None
        self.statements = []
        self.con.set_trace_callback(self.statements.append)
        self.seed(count, tasks)
        self.statements.clear()
        # Explicit evidence budget: 4 files, 256 bytes each, independent of history.
        for i in range(4):
            (root / f'evidence-{i}.txt').write_bytes(b'x' * 256)

    def insert(self, table, values):
        self.con.execute(f"INSERT INTO {table} ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", tuple(values.values()))

    def seed(self, count, tasks):
        with self.store.begin_immediate(self.con):
            for repo in range(3):
                self.insert('slot', dict(repo_id=f'r{repo}', name='s1', path=f'/synthetic/r{repo}/s1'))
            for i in range(count):
                task, seq = i % tasks, i // tasks + 1
                key = f'a{i:07}'
                common = dict(attempt_id=key, dispatch_token=key, generation=1)
                current_implement = self.mixed and i + tasks >= count and task % 4 == 0
                repeat = seq % 4 == 2 and not current_implement
                step = 'implement' if seq % 4 == 3 or current_implement else 'plan'
                self.insert('attempt', dict(**common, step=step, adapter='beads', backlog=f'b{task % 3}',
                    task_id=f't{task // 3}', tracker_root='/synthetic/tracker', repo_id=f'r{task % 3}', slot='s1',
                    input_path='input.txt', input_digest=DIGEST, schema_version=1, model='chosen', effort='high',
                    access_policy=json.dumps(dict(harness='codex', sandbox='workspace-write')), deadline=100,
                    number=2 if repeat else 1, seq=seq, slot_head=SHA, base_commit=SHA,
                    previous_attempt_id=f'a{i-tasks:07}' if repeat else None, repeat_reason='unsafe' if repeat else None,
                    after_commit=SHA if step == 'implement' else None, label='auto', phase='captured', end_commit=SHA))
                self.history(common, i, step)

    def history(self, common, i, step):
        evidence = {f'{name}_{field}': ('file.txt' if field == 'path' else DIGEST)
                    for name in ('stdout', 'stderr', 'answer', 'diagnostic') for field in ('path', 'digest')}
        self.insert('execution', dict(**common, rc=0, timed_out=0, work=1, stands=1, answered=1,
                    session_state='complete', answer_kind='valid', disposition='implemented', effect='keep',
                    commit_paths='[]', **evidence))
        self.insert('verification', dict(**common, verdict='verified', observed_at=1, reused=1))
        self.insert('slot_release', dict(**common, head=SHA, released_at=2, claim='unclaimed' if i % 10 == 0 else 'kept'))
        self.insert('published_branch', dict(**common, commit_sha=SHA, remote_head=SHA, published_at=2))
        if step == 'implement':
            self.insert('setup_run', dict(**common, run=1, commit_sha=SHA, digest=DIGEST, started_at=1,
                        ended_at=2, rc=0, conclusion='passed'))
        if step != 'implement':
            self.hold(common, i)
            return
        check = f'c{i:07}'
        self.insert('checks_attempt', dict(attempt_id=check, dispatch_token=check, generation=1,
                    after_attempt_id=common['attempt_id'], number=1, slot='s1', slot_head=SHA, target_commit=SHA,
                    required=json.dumps([['test', DIGEST]]), deadline=100, phase='concluded', conclusion='passed', concluded_at=2,
                    released_at=2, parked=SHA))
        self.insert('check_result', dict(attempt_id=check, dispatch_token=check, generation=1, block=1,
                    position=0, name='test', argv_digest=DIGEST, timeout=10, started_at=1, ended_at=2, rc=0, conclusion='passed'))
        self.insert('land_candidate', dict(candidate_id=f'l{i:07}', dispatch_token=f'l{i:07}', generation=1,
                    checks_attempt_id=check, number=1, origin_commit=SHA, commit_sha=SHA, tree_same=1, required=json.dumps([['test', DIGEST]]),
                    validation='same_tree', validated_at=2, delivery='pushed', delivered_at=2, remote_head=SHA,
                    close='closed', closed_at=2))
        self.hold(common, i)

    def hold(self, common, i):
        if i % 5 == 0:
            self.insert('task_hold', dict(attempt_id=common['attempt_id'], cause_id=common['attempt_id'],
                        reason='needs_owner', held_at=1, labels='moved', labelled_at=2,
                        commenting_at=2, commented_at=2 if i % 10 == 0 else None))

    def facts(self):
        tables = [r[0] for r in self.con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return dict(rows={t: self.con.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in tables},
                    sizes={p.name: p.stat().st_size for p in self.path.parent.iterdir()},
                    index_bytes=self.con.execute("SELECT coalesce(sum(pgsize),0) FROM dbstat WHERE name IN (SELECT name FROM sqlite_master WHERE type='index')").fetchone()[0],
                    schema_version=SCHEMA.version, sqlite=sqlite3.sqlite_version, foreign_keys=self.con.execute('PRAGMA foreign_key_check').fetchall())

    def plans(self):
        queries = dict(scoped="SELECT * FROM attempt p WHERE adapter='beads' AND backlog='b0' AND task_id='t0'",
            later="SELECT p.attempt_id FROM attempt p WHERE p.adapter='beads' AND NOT EXISTS (SELECT 1 FROM attempt q WHERE q.adapter=p.adapter AND q.backlog=p.backlog AND q.task_id=p.task_id AND q.seq>p.seq)",
            grouped="SELECT adapter,backlog,task_id,max(seq) FROM attempt WHERE adapter='beads' GROUP BY adapter,backlog,task_id",
            repo="SELECT s.path FROM slot s JOIN attempt p ON p.repo_id=s.repo_id WHERE p.attempt_id='a0000000' AND s.name=p.slot")
        return {name: self.con.execute('EXPLAIN QUERY PLAN ' + query).fetchall() for name, query in queries.items()}
