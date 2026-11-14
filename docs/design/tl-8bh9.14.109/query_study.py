"""Compare query forms and optional indexes on new, retained synthetic data only."""
import argparse
import json
import runpy
import statistics
import time
from pathlib import Path

FixtureStore = runpy.run_path(str(Path(__file__).with_name('fixture_store.py')))['FixtureStore']

LATER = """SELECT p.attempt_id FROM attempt p WHERE p.adapter='beads' AND NOT EXISTS
(SELECT 1 FROM attempt q WHERE q.adapter=p.adapter AND q.backlog=p.backlog AND q.task_id=p.task_id AND q.seq>p.seq)"""
GROUPED = """SELECT p.attempt_id FROM attempt p JOIN
(SELECT adapter,backlog,task_id,max(seq) seq FROM attempt WHERE adapter='beads' GROUP BY adapter,backlog,task_id) q
ON p.adapter=q.adapter AND p.backlog=q.backlog AND p.task_id=q.task_id AND p.seq=q.seq"""
OLD_SLOT = """SELECT s.path FROM slot s JOIN attempt p ON p.repo_id=s.repo_id
WHERE (p.attempt_id=?1 AND s.name=p.slot) OR EXISTS (SELECT 1 FROM checks_attempt c WHERE c.attempt_id=?1
AND c.after_attempt_id=p.attempt_id AND c.slot=s.name) LIMIT 1"""
SLOT = """SELECT s.path FROM attempt p JOIN slot s ON s.repo_id=p.repo_id AND s.name=p.slot WHERE p.attempt_id=?1
UNION ALL SELECT s.path FROM checks_attempt c JOIN attempt p ON p.attempt_id=c.after_attempt_id
JOIN slot s ON s.repo_id=p.repo_id AND s.name=c.slot WHERE c.attempt_id=?1 LIMIT 1"""
COUNT = "SELECT count(*) FROM attempt WHERE adapter='beads' AND backlog='b0' AND task_id='t0' AND step='plan'"


def measure(con, query, params=()):
    con.execute(query, params).fetchall()
    times = []
    for _ in range(5):
        start = time.perf_counter()
        rows = con.execute(query, params).fetchall()
        times.append(time.perf_counter()-start)
    return dict(seconds=times, median=statistics.median(times), p95=max(times), rows=len(rows),
                plan=con.execute('EXPLAIN QUERY PLAN ' + query, params).fetchall())


def insertion(fixture, label):
    start = time.perf_counter()
    with fixture.store.begin_immediate(fixture.con):
        for i in range(100):
            fixture.con.execute("""INSERT INTO attempt (attempt_id,dispatch_token,generation,step,adapter,backlog,
            task_id,tracker_root,repo_id,slot,input_path,input_digest,schema_version,model,effort,access_policy,deadline,
            number,seq,slot_head) SELECT ?,?,1,'plan',adapter,backlog,?,tracker_root,repo_id,slot,input_path,input_digest,
            schema_version,model,effort,access_policy,deadline,1,1,slot_head FROM attempt WHERE attempt_id='a0000000'""",
            (f'{label}{i}', f'{label}{i}', f'{label}{i}'))
    return time.perf_counter()-start


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--count', type=int, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    check_seq = ((args.count // 100 - 3) // 4) * 4 + 3
    check_id = f'c{(check_seq-1)*100+99:07}'
    queries = dict(later=(LATER, ()), grouped=(GROUPED, ()), count=(COUNT, ()),
        old_agent=(OLD_SLOT, (f'a{args.count-1:07}',)), old_check=(OLD_SLOT, (check_id,)),
        old_missing=(OLD_SLOT, ('absent',)), agent=(SLOT, (f'a{args.count-1:07}',)),
        check=(SLOT, (check_id,)), missing=(SLOT, ('absent',)))
    output = {}
    for label, ddl in [('base', None), ('repo_index', 'CREATE INDEX synthetic_repo ON attempt(repo_id)'),
                       ('count_index', 'CREATE INDEX synthetic_count ON attempt(adapter,backlog,task_id,step,seq)')]:
        fixture = FixtureStore(args.output / label, args.count, 100)
        con = fixture.con
        if ddl:
            con.execute(ddl)
        output[label] = dict(queries={name:measure(con, *pair) for name, pair in queries.items()},
                             facts=fixture.facts(), quick_check=measure(con, 'PRAGMA quick_check'),
                             insertion100_seconds=[insertion(fixture, f'{label}{i}-') for i in range(5)])
        fixture.store.close_shared()
    (args.output / 'study.json').write_text(json.dumps(output, indent=2)+'\n')
    print(args.output / 'study.json')


if __name__ == '__main__':
    main()
