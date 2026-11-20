# Measurements and as-built decisions

Measured on 2026-11-14. Sections 1–3 are implemented. All numbers below are
synthetic observations, not latency guarantees or CI thresholds. Raw repeated
samples, empirical nearest-rank p95, query counts, peak traced Python allocations,
row counts, file sizes and query plans are retained in [samples](samples/).

## Reproduction and boundaries

The unchanged successor baseline is commit
`65b1e466a80a2650e1b12e722398b6161008b682` (schema 20). The implementation was
measured from this worktree with schema 21, before its factory commit. Both use
installed, non-editable `iorlas-task-loop==0`, Python 3.15.0, SQLite 3.53.1, and
`sqlite-store==0.1.0` pinned to shelf
`18d3164893f95dc82e391a7226652d286d9c4663`. No dependency changed. Host: Linux
6.18.54, x86_64 devbox, 8 logical CPUs, 36,948,016 KiB RAM. This is a shared host;
other activity was not controlled. Filesystem caches were never evicted.

Each measurement constructs a NEW directory and retains its files. The SQL owner
is `fixture_store.py`, using the application's `Store(SCHEMA)`, WAL, NORMAL
synchronous mode and enabled foreign keys. `foreign_key_check` returned no rows
for every retained dataset. Evidence has a hard construction budget of four
files of 256 bytes (1,024 bytes total), independent of history size. No real
factory, tracker, evidence tree, slot or uv cache was opened by these drivers.
Status and board use semantic observation, leftovers and tracker ports; no Git,
process or tracker command is executed. Startup construction likewise opens only
SQLite connection ports, never an external-action method.

`measure.py` performs one warm-up, three timed samples, then a separate traced
allocation run for each operation. Construction and tracing are outside timed
samples. `queries-*.json` uses one warm-up and five samples per query and integrity
check; insertion costs are five consecutive batches of 100 new rows, each in its
own transaction. Index variants each start with an independent, equal dataset.
No index is dropped. p95 is the largest sample at these small sample counts.
Peak memory is Python allocation measured by tracemalloc, not resident memory.
SQL counts include schema-version PRAGMAs, and query-group counts overlap when a
statement joins tables. Returned rows count public result rows; the hydration
counts below distinguish them from rows traversed inside SQLite.

Early exploratory fixtures exposed the unavailable-status path (holds lacked an
admission label and required-check lists were empty). They were corrected, and
all reported comparisons were rerun against the frozen, unchanged successor
package. Exploratory data remains in the temporary directory; its timings are
excluded here. The five uniform workloads end on plan; the mixed workload ends
with 60 plan, 20 landed and 20 held cards, identically before and after. Its
holds include finished and unfinished tracker handling. Setup/check/land history
exists only on implement attempts. Three backlogs/repositories reuse task IDs;
repeat chains and plan restarts are deterministic.

The baseline was installed offline from a read-only archive of that successor
commit. The reference implementation `731b7c7` is never imported. To reproduce
(use a fresh temporary directory name each time):

```sh
export TMPDIR="${TMPDIR:-/tmp}"
mkdir "$TMPDIR/growth-baseline-package"
git archive 65b1e466a80a2650e1b12e722398b6161008b682 src pyproject.toml uv.lock | tar -x -C "$TMPDIR/growth-baseline-package"
uv sync --offline --frozen --no-editable --project "$TMPDIR/growth-baseline-package"
just install
```

For each package, run `measure.py` with `(count,tasks)` equal to `(1000,100)`,
`(10000,100)`, `(100000,100)`, `(10000,1000)` and `(100000,10000)`. Also run
`(10000,100) --mixed`. For example:

```sh
"$TMPDIR/growth-baseline-package/.venv/bin/python" -I docs/design/tl-8bh9.14.109/measure.py "$TMPDIR/growth-before-1000" --revision 65b1e466a80a2650e1b12e722398b6161008b682 --count 1000 --tasks 100
uv run --frozen --no-sync python -I docs/design/tl-8bh9.14.109/measure.py "$TMPDIR/growth-after-1000" --revision implementation-worktree --count 1000 --tasks 100
```

The retained uniform runs originally used an absent check ID as their slot
negative control; the final driver and mixed runs use the real checks ID at
sequence 3. `queries-*.json` separately measures an existing late agent ID, an
existing late checks ID, and an absent ID with both slot query forms at all sizes.
The other uniform inputs and sample policies are identical. Use the baseline
package for `query_study.py` to compare absence/presence of the proposed indexes
on schema 20, at each of the three sizes:

```sh
"$TMPDIR/growth-baseline-package/.venv/bin/python" -I docs/design/tl-8bh9.14.109/query_study.py "$TMPDIR/growth-query-1000" --count 1000
uv run --frozen --no-sync python -I docs/design/tl-8bh9.14.109/startup.py "$TMPDIR/growth-after-1000" "$TMPDIR/growth-startup-1000"
uv run --frozen --no-sync python -I docs/design/tl-8bh9.14.109/startup.py "$TMPDIR/growth-after-1000" "$TMPDIR/growth-opens-1000-2" --opens-only
uv run --frozen --no-sync python -I docs/design/tl-8bh9.14.109/startup.py "$TMPDIR/growth-after-1000" "$TMPDIR/growth-opens-1000-3" --opens-only
```

Repeat startup commands for 10,000 and 100,000 rows. Each shell invocation is a
fresh process; only its first writable open is process-cold. Store-repeat and
other-store samples are process-warm, and all are filesystem-warm. The driver
refuses existing output (verified: exit 2 with preservation message); startup
also requires the synthetic dataset's metadata and four evidence sentinels.

## Current reads and board

Times below are medians in milliseconds; ratios are before / after.

| Attempts | Tasks | Listing before | Listing after | Ratio | Board before | Board after | Ratio |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1000 | 100 | 15.498 | 5.011 | 3.1× | 29.982 | 6.393 | 4.7× |
| 10000 | 100 | 163.991 | 8.123 | 20.2× | 390.739 | 9.923 | 39.4× |
| 100000 | 100 | 2798.255 | 40.686 | 68.8× | 5793.439 | 40.736 | 142.2× |
| 10000 | 1000 | 176.112 | 54.951 | 3.2× | 489.906 | 74.697 | 6.6× |
| 100000 | 10000 | 2523.400 | 602.409 | 4.2× | 6530.860 | 940.379 | 6.9× |
| 10000 mixed | 100 | 167.993 | 15.070 | 11.1× | 356.029 | 16.984 | 21.0× |

At fixed task count, listing now hydrates T current agent rows, and a board
hydrates those same T rows once. Previously listing hydrated N history rows and
the board hydrated another N. Full history remains on explicit history/detail
paths. SQLite still traverses history for grouped maximum; this is not constant
work. The new count query traverses the relevant covering index and spans plan
restarts; substituted checks cards retain the original checks-number rule.
Source rows, release/publication fields and counts come from ONE SELECT snapshot.
There is no read transaction spanning tracker, Git, process or evidence IO.

| Attempts / tasks | Board SQL statements before / after | Hydrated agent rows before / after | Peak Python bytes before / after |
| --- | ---: | ---: | ---: |
| 1000 / 100 | 211 / 209 | 2000 / 100 | 3442013 / 603815 |
| 10000 / 100 | 211 / 209 | 20000 / 100 | 30566025 / 592040 |
| 100000 / 100 | 211 / 209 | 200000 / 100 | 301760229 / 592226 |
| 10000 / 1000 | 2011 / 2009 | 20000 / 1000 | 34393263 / 6062365 |
| 100000 / 10000 | 20011 / 20009 | 200000 / 10000 | 343932195 / 60697375 |
| 10000 / 100 mixed | 371 / 369 | 20000 / 100 | 30669651 / 696301 |

The 10,000-card board still allocates about 61 MB and takes about a second.
No card is hidden and the poll cadence is unchanged. The mixed board performs
40 checks-table reads (including joins), 20 check-result reads, 20 land reads,
20 setup reads, 100 execution reads and one batched hold read. Individual owner
reads on that same dataset were measured separately:

| Read | Before median ms | After median ms |
| --- | ---: | ---: |
| checks_history | 0.024 | 0.043 |
| checks_results | 0.007 | 0.034 |
| land | 0.018 | 0.047 |
| holds | 0.103 | 0.164 |

These tiny isolated samples have noise and do not dominate total board time;
read/codec work grows with visible tasks. Raw query counts and peak allocations
are retained for each operation, including current selection on the new package.
All-history, backlog-only, task-only, and full scoped history measurements follow:

| Attempts / tasks | All history ms before / after | Backlog ms before / after | Task-only ms before / after | Backlog + task ms before / after |
| --- | ---: | ---: | ---: | ---: |
| 1000 / 100 | 11.088 / 12.303 | 3.096 / 4.074 | 0.279 / 0.424 | 0.138 / 0.085 |
| 10000 / 100 | 148.329 / 193.251 | 49.278 / 46.911 | 3.454 / 3.692 | 2.083 / 1.097 |
| 100000 / 100 | 2183.352 / 2319.188 | 680.734 / 681.494 | 52.301 / 49.488 | 23.327 / 19.438 |
| 10000 / 1000 | 154.916 / 146.553 | 45.563 / 43.191 | 0.716 / 1.348 | 0.775 / 0.140 |
| 100000 / 10000 | 1951.005 / 3026.990 | 592.754 / 584.599 | 4.904 / 5.323 | 5.224 / 0.118 |

There are small-dataset regressions: at 1,000 attempts, all-history is about 11%
slower, backlog-only about 31%, and task-only about 52%. At 100,000 attempts /
10,000 tasks all-history is about 55% slower; it still hydrates all history and
remains allocation-heavy. Concurrent shared-host activity and only three samples
limit attribution. The task-only shape cannot seek past backlog in the existing
unique index; no speculative extra index was added for it. Scoped reads expose
backlog/task equalities to that index, preserve ordering and decode the entire
requested history. No timing improvement is claimed for every filter/size.

## Query and index choice

The grouped-maximum and later-row-exclusion queries were compared directly with
five repeated samples on each size. Slot lookups compare existing IDs near the
end of history, plus absence; first-row IDs alone would conceal the old scan.

| Attempts | Later exclusion ms | Grouped maximum ms | Count without index ms | Covering count ms | Old late agent ms | New late agent ms | Old late checks ms | New late checks ms |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1000 | 0.253 | 0.127 | 0.002 | 0.002 | 0.138 | 0.003 | 0.150 | 0.003 |
| 10000 | 3.551 | 1.037 | 0.019 | 0.004 | 3.464 | 0.003 | 4.118 | 0.005 |
| 100000 | 35.762 | 7.678 | 1.056 | 0.019 | 29.911 | 0.004 | 40.692 | 0.003 |

Choose grouped maximum: it traverses the unique task/sequence index before
joining wide rows. Add `attempt_step_count(adapter,backlog,task_id,step,seq)`:
its covering traversal avoids table hydration to count a current step's tries.
Do not add `attempt(repo_id)`: splitting slot lookup into primary-key agent and
checks joins removes the scan and seeks slot's composite primary key directly.
The repository index still scans on the old OR shape, and is unnecessary for
those new primary-key joins. No other repository-scoped read justified it.
The raw EXPLAIN output captures all three choices and scoped filters; tests
assert structural index use rather than an entire SQLite plan string.

Index tradeoff (independent datasets; median insertion time for 100 rows; full
quick_check at the original row count):

| Attempts | Extra repo index bytes | Extra count index bytes | Insert base / repo / count ms | quick_check base / count ms |
| ---: | ---: | ---: | ---: | ---: |
| 1000 | 16384 | 32768 | 1.360 / 1.612 / 1.831 | 4.810 / 4.431 |
| 10000 | 106496 | 286720 | 1.831 / 2.281 / 1.858 | 52.557 / 52.734 |
| 100000 | 1073152 | 2977792 | 2.731 / 2.440 / 2.017 | 609.449 / 512.376 |

The covering index costs roughly 3 MB at 100,000 rows. Insertion and integrity
samples show its write/startup cost as well as its read benefit; neither is
assumed free. Schema 21 is deliberately incompatible: version 20 is refused,
with no migration/compatibility reader. Tests preserve the old database and its
contents. No running factory database was drained, replaced or discarded.
Operational rollout must use the separately authorized drain/upgrade operation.

## Growth and retained files

At every size, attempt, execution, verification, slot_release and published_branch
have N rows; setup_run, checks_attempt, check_result and land_candidate have
proportional implement history (200 at 1,000 attempts, 2,500 at 10,000 and 25,000
at 100,000). There are N/5 holds and three slots, with no reservations in these
completed-history workloads. Other current-schema tables remain present. Mixed
history adds 25 current implement/check/land rows. Exact counts for all 14 tables,
database/WAL/shared-memory bytes, total index bytes and evidence bytes are in
every dataset's `facts`. File sizes are captured before timing/checkpoint activity;
database and WAL sizes may overlap and must not be added as distinct logical data.

| Attempts | Database bytes before / after | WAL bytes before / after | Index bytes before / after | Evidence files / bytes |
| ---: | ---: | ---: | ---: | ---: |
| 1000 | 4096 / 4096 | 1738672 / 1775752 | 258048 / 290816 | 4 / 1024 |
| 10000 | 15040512 / 15351808 | 15264632 / 15581872 | 2150400 / 2461696 | 4 / 1024 |
| 100000 | 150036480 / 153415680 | 151051592 / 154454712 | 21700608 / 25079808 | 4 / 1024 |

All requested dataset sizes completed. Evidence and all grow-only history remain
retained; this task introduces no cleaner, purge, TTL, pagination or board cache.

## Startup lifetimes and residual shelf proposal

`startup.py` observes public SQLite execute calls on its own connections. A
quick_check produces its result during execute; its measured time is recorded
separately from the surrounding open. It does not consume or replace the result,
seed a cache, or patch shelf internals. Read-only opens execute zero integrity
checks. Schema-version PRAGMAs remain on use and are not counted as integrity scans.

The representative command constructs admission, repeat, advance, checks,
verification and nested land writers and touches their connection ports. The
three-round case repeats that lifetime. `separate` uses one Store per old
responsibility; `reuse` supplies the same ordinary Store and a separate bounded
registration Store through the real composition APIs. This measures database
startup work, not external-action runtime or total CLI import/process latency.
Entry and checks-entry use their real composition, whose two Stores remain
necessary for different timeouts. A path not needing registration may open only
one writer; lazy unopened stores execute no check.

| Attempts | Command checks before / after | Command ms before / after | Three-round checks before / after | Three-round ms before / after | Entry ms (after) | Checks-entry ms (after) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1000 | 7 / 2 | 46.447 / 13.917 | 21 / 2 | 135.951 / 14.189 | 10.904 | 13.033 |
| 10000 | 7 / 2 | 403.860 / 113.866 | 21 / 2 | 1266.196 / 112.075 | 112.460 | 121.340 |
| 100000 | 7 / 2 | 3504.397 / 998.241 | 21 / 2 | 10461.420 / 968.641 | 1007.742 | 973.132 |

Fresh-process first writable opens (three independent processes per size), and
warm open medians from the representative process:

| Attempts | Process-cold median / p95 ms | Same Store repeat ms | Distinct Store ms | Read-only ms | Checks on repeat / distinct / read-only |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1000 | 8.823 / 8.914 | 0.651 | 6.523 | 0.549 | 0 / 1 / 0 |
| 10000 | 54.769 / 77.182 | 0.660 | 55.127 | 0.390 | 0 / 1 / 0 |
| 100000 | 499.884 / 508.265 | 0.568 | 495.508 | 0.580 | 0 / 1 / 0 |

At 100,000 attempts the retained two checks account for 0.995 seconds of
the command's roughly one-second SQLite startup; the repeated-round lifetime
retains two checks total, not two per round. Entry and checks-entry also retain
two checks each. Integrity still materially dominates startup after local reuse.

Proposed shelf follow-up only: expose a process-owned integrity-check cache that
can be explicitly shared between distinct Store instances, while keeping their
per-thread writer ownership, timeout policies, transaction/error eviction and
connection lifetimes separate. It must synchronize first checks, key success by
process/resolved path/device/inode, invalidate on replacement, and never cache a
failed check. This would allow ordinary and bounded connections to share a
successful check without sharing a mutable timeout. No shelf API/pin or integrity
policy is changed here; approval and implementation belong to separate work.

## Owner decisions and verification

Q2: automatic integrity checks stay; local duplicates were removed and the
measured residual motivates only the shelf proposal above. Q3: every attempt
evidence file stays, including unreferenced evidence; no cleaner. Q4: all nine
history tables, newer tables and finished holds stay; growth is accepted. Q5:
existing fresh-setup uv cache/tools emptying stays; no fresh setup was run on a
real slot and no extra cleanup was added. Q6: every landed/held card stays and
there is no pagination. These are final owner decisions, not reopened questions.

Added test files: `tests/steps/test_attempt_listing.py` and
`tests/cli/test_writer_lifetime.py`. They cover filter identities and order,
current maximum/counts, restarts, single board selection without history
hydration, empty/unavailable metadata, landed/check substitution, both hold
states, old-schema preservation, index seeks, a concurrent admission during a
single SELECT, no open transaction at external observation, writer closure,
per-thread connections, identity replacement rechecking and distinct timeouts.
Existing CLI, round, detail, check-repeat, checks/land/hold tests exercise the
shared listing operation. The SQL ownership policy recognizes the schema-owned
index. A pre-existing dashboard test used `Run.summary`; it now asserts the
actual `Run.access` field.

Validation: required `just check` passed (ruff, pyrefly, nine import contracts);
required `just test` passed (3,438 tests in 41.32 s). Focused tests also passed. Earlier gate runs exposed
and then resolved the index ownership assertion, fixture setup and type/lint
issues; no failing gate remains. `git diff --check` passed. No Git write, remote
publication, dependency change or deletion was performed.
