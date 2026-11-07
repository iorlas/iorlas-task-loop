# Lens A — aggressive stdlib and third-party extraction, second pass

This pass selects **7,799 gross donor lines for removal from task-loop/delegate: 5.43% of the measured 143,632-line corpus**. That is 3,263 application/launcher lines and 4,536 test/support lines. It includes substantial refactoring: shared record backends, typed storage, vendor stream readers, a unified real/fake Git contract, and portable test infrastructure. Generic mechanisms move even when their present module also contains factory rules.

**This lens does not establish the owner's 50% target.** Half this checkout is 71,816 lines; this concrete inventory is 64,017 lines short. The denominator includes 75,492 test/support/fixture lines, whose largest files mostly specify factory behavior, and 8,129 lines of already-shared vendored shelf code. Moving factory contracts or minifying golden JSON would pad the number. This is an implementable extraction inventory, not a claim that the remaining code has been proven irreducible.

Read first: _shelf/AGENTS.md, _shelf/CONTEXT.md, _shelf/docs/constitution.md and _shelf/catalog/*.toml. Existing shelf packages were checked before proposing new ones; their implementation/public surfaces are cited below. The constitution requires a shelf package never to import an app and permits promoting generic substrate without waiting for a second consumer.

This is a static local review. No source/tests changed, no credential files were read, no network or runtime/test/Git/tracker commands ran. Tests below are ownership requirements, not claims of passing validation. The shell sandbox could not create its namespace; the exact read commands were rerun with the requested escalation. None was denied.

## Counting and release contract

The measured command was:

    wc -l $(rg --files --hidden --no-ignore src tests skills dev _delegate/src _delegate/skills -g '*.py' -g '*.js' -g '*.html' -g '*.json' -g '*.md')

The result is **143,632 physical lines in 1,257 files**, including blanks/comments, fixtures, goldens, static JavaScript/HTML, skills and development code. Both ordinary and unignored inventories give the same total. src/taskloop_dash is inside src and counted once. This supplied delegate tree has no top-level tests or dev directory; embedded delegate fixtures in task-loop tests are counted where they actually live.

| Root | Lines |
| --- | ---: |
| src, including both taskloop packages and static assets | 46,727 |
| tests, including support, fixtures and goldens | 75,492 |
| skills, including shelf vendor copies | 7,431 |
| dev | 2,051 |
| _delegate/src | 7,771 |
| _delegate/skills, including shelf vendor copies | 4,160 |
| **Total** | **143,632** |

The requested extension list excludes .jsonl: a separate wc measured **568 JSONL fixture/golden lines** under these roots. They remain consumer contract data; none is claimed as savings. Counting them too gives 144,200 lines and lowers this inventory to 5.41%. CSS, shell scripts, shelf and lifesim are outside the requested denominator. Lifesim is evidence for additional consumers, never free volume.

Every range in the candidate manifests below was measured with sed -n 'START,ENDp' FILE | wc -l. Ranges are inclusive and disjoint across accepted candidates. Whole-file counts came from wc, not SLOC estimates. Code embedded in tests is explicitly in the test/support column. A named test slice moves only after app-specific fixture types/imports are replaced with package-local probes; the app's golden contracts and end-to-end assertions stay as holdouts. New package tests, replacement calls and compatibility adapters cost lines and are not subtracted from these gross donor figures.

Accounting categories: **M** = old mechanism/tests transferred behind a shelf API; **D** = duplicate old implementation deleted after equivalent shelf coverage; **S** = old implementation replaced by stdlib/third-party. This is not net ecosystem shrinkage. In this proposal D is the 1,857-line gitsim duplicate and S is 23 lines replaced by graphlib. No dead-code deletion is asserted without reachability evidence. Third-party backend experiments below overlap the accepted inventory and cannot be added again.

Every accepted item uses this releasable sequence, with candidate-specific ordering below:

1. Capture current wire bytes, errors, ordering and safety decisions as consumer holdouts; move generic contracts with their subject.
2. Add the mechanism to an existing shelf owner, or create the named deep module. Publish a namespaced **package git tag**; app dependencies/vendor manifests pin the tag and provenance, never shelf workspace HEAD.
3. Adopt behind the app's existing interface in one release at a time. Run moved package contracts and the consumer's logic/real/e2e gates, including land/gate/close holdouts. None has run in this audit.
4. Delete the replaced implementation only after parity. Intentional behavior changes get a separate reviewed release. Rollback restores the old app/package pin and never rewrites live state to satisfy a new codec.

Runtime dependency cost is real: skills/task-loop/tl.py:1-6 declares Python >=3.15 and msgspec==0.22.0 in PEP 723. A new runtime dependency must also match pyproject.toml and be resolved by the script launcher. Delegate's _delegate/skills/delegate/route.py is a plain-Python bootstrap, so adding msgspec/pydantic/psutil means a launcher/distribution decision, not just an import. CLAUDE.md Conventions and .importlinter's hot-hook-path-is-light contract require PreToolUse to remain plain python3 with no msgspec or record imports. Test extras must never enter that path.

## Accepted extraction briefs

The interface blocks are **proposed shelf surfaces**, unless explicitly identified as existing above. They intentionally replace app-specific types with neutral values and injected callbacks. They are not claims that those APIs already ship.

### A01 — ✅ extract: Versioned records and schema machinery

**Shelf first.** No existing shelf package owns a strict versioned record codec or strict-output schema transformations. anyllm owns provider calls, not record serialization. Create any-record; keep its dataclass backend dependency-free and its msgspec backend optional.

**What it does.** Converts typed records to and from JSON, checks versions and tags, and generates or transforms JSON Schema.

**Exact donor/call-site manifest.** These are the implementation sites and tests to move or replace; they also name the existing adapter entry points to retain during adoption.

| File:lines | Count | Ownership |
| --- | ---: | --- |
| packages/kernel/src/tlkernel/wire.py:1-101 | 101 | application/launcher |
| _delegate/src/delegate/contracts/codec.py:1-229 | 229 | application/launcher |
| packages/kernel/src/tlkernel/schema.py:1-147 | 147 | application/launcher |
| _delegate/src/delegate/contracts/schema.py:1-104 | 104 | application/launcher |
| tests/contracts/test_wire.py:121-198 | 78 | test/support |
| tests/contracts/test_schema.py:83-117 | 35 | test/support |

**Volume:** 581 application/launcher + 113 test/support = **694** donor lines; **M 694, D 0, S 0**. Fixtures/goldens moving: **0**; app-specific records and their golden outputs remain consumer-owned. 

**Public interface** (at most six lines):

    Codec[T](type, *, backend, version=None, tag=None)
    codec.load(value) -> T; codec.dump(record) -> dict
    codec.schema() -> dict
    strict(schema); unstrict(value, schema); prune(value, schema)

**Consumers and adoption sites.** Task-loop wire.load/dump and answers.schema_for; delegate codec.from_json/to_json/from_tagged. Lifesim is prospective only; shelf packages with persisted records can adopt later.

**Contracts that make it ownable:**

- Move the listed Refusals/Wire and Generator tests using package-local probe records; keep application samples and answer-schema goldens in task-loop.
- Pin unknown-key refusal, missing keys, bool versus int, integer-valued float round trips, omission versus null, renamed fields and nested versions.
- Pin sorted sets, custom scalar hooks, union tags, input-copy isolation, and strict/unstrict round trips.
- Run consumer wire goldens unchanged against both tagged backends before switching a consumer.

**Production risk.** A changed accepted-answer set can make every worker fail validation; altered stored versions can destroy resumability. Delegate deliberately preserves an int in a float field, whereas task-loop converts it to float: retain two codec policies, not one coercion default.

**Releasable migration.** 1. Move the current two codecs and schema walkers behind separate backend adapters and move the generic tests. 2. Publish any-record with a tag and adopt delegate first, then task-loop with compatibility exports. 3. Only after parity, trial msgspec.json.schema and msgspec conversion as implementation replacements; their deletion savings are not additional to this inventory.

**Cost and replacement fit.** High; msgspec already costs task-loop a runtime pin, but must remain an optional extra for delegate. cattrs/pydantic would be additional dependencies without demonstrated parity.

### A02 — ✅ extract: Typed atomic documents and document sets

**Shelf first.** atomic-io already exposes atomic_write_json/bytes/text at _shelf/packages/atomic-io/src/atomic_io/__init__.py:21-78. It lacks typed read outcomes, codec injection and in-memory parity. Evolve it with a document module rather than invent another persistence package.

**What it does.** Reads a typed document as present, absent, corrupt or foreign-version, and replaces or deletes it atomically.

**Exact donor/call-site manifest.** These are the implementation sites and tests to move or replace; they also name the existing adapter entry points to retain during adoption.

| File:lines | Count | Ownership |
| --- | ---: | --- |
| packages/kernel/src/tlkernel/stores.py:44-121 | 78 | application/launcher |
| src/taskloop/stores/files.py:20-38 | 19 | application/launcher |
| src/taskloop/stores/memory.py:36-79 | 44 | application/launcher |
| tests/contracts/test_sealed_read.py:15-42 | 28 | test/support |
| tests/stores/suites.py:33-59 | 27 | test/support |

**Volume:** 141 application/launcher + 55 test/support = **196** donor lines; **M 196, D 0, S 0**. Fixtures/goldens moving: **0**; app-specific records and their golden outputs remain consumer-owned. 

**Public interface** (at most six lines):

    Document[T](path, *, decode, encode, version_error)
    doc.read() -> Present[T] | Absent | Torn | ForeignVersion
    doc.get() -> T | None; doc.need() -> T | None
    doc.write(value); doc.delete()
    DocumentSet(root, factory).of(key); .keys()

**Consumers and adoption sites.** Task-loop JsonStore and FileDocSet plus their memory equivalents; delegate StateStore/ConfigStore can subsequently use the transaction substrate while keeping retirement warnings and profiles local. Lifesim configuration readers are prospective.

**Contracts that make it ownable:**

- Move SealedRead and DocContract using a neutral versioned probe and a parameterized real/memory rig.
- Missing, unreadable, invalid JSON and stale-version files must remain four distinct outcomes.
- A failed encode/write/replace preserves the old file; repeated delete is harmless.
- get remains lossy and need remains strict, with the path in the refusal.

**Production risk.** Reading corrupt authoritative state as empty can replay work or lose owner decisions. Keep each caller's choice of get versus need and exact write permissions.

**Releasable migration.** 1. Add injected codecs and neutral read-result types to atomic-io. 2. Tag and adopt the in-memory and file implementations together; keep JsonStore as an app compatibility export. 3. Convert delegate transactions separately, preserving its intentional fallback-to-empty and warning policy.

**Cost and replacement fit.** Medium; no new runtime wheel beyond current shelf delivery.

### A03 — ✅ extract: Typed JSONL, bounded readers and retained append handles

**Shelf first.** jsonl-log already supplies JsonlLog.open, append_at, read/read_lines, Jsonl and cursor read_from/tail: _shelf/packages/jsonl-log/src/jsonl_log/__init__.py:63-108 and cursor.py:49-99. Missing are a public bytes-buffer parser, a byte budget, raw text tail, predicate compaction and a fork-safe append pool. Add these to this package.

**What it does.** Owns append, rotation, byte cursors, decoding, bounded tail reads and descriptor lifetime beneath application log records.

**Exact donor/call-site manifest.** These are the implementation sites and tests to move or replace; they also name the existing adapter entry points to retain during adoption.

| File:lines | Count | Ownership |
| --- | ---: | --- |
| packages/kernel/src/tlkernel/stores.py:122-161 | 40 | application/launcher |
| packages/kernel/src/tlkernel/rotating.py:1-21 | 21 | application/launcher |
| src/taskloop/stores/memory.py:81-122 | 42 | application/launcher |
| src/taskloop_dash/jsonl.py:14-19 | 6 | application/launcher |
| src/taskloop_dash/jsonl.py:32-62 | 31 | application/launcher |
| src/taskloop_dash/tails.py:36-51 | 16 | application/launcher |
| src/taskloop/adapters/applog.py:1-91 | 91 | application/launcher |
| _delegate/src/delegate/contracts/stores.py:118-135 | 18 | application/launcher |
| tests/contracts/test_jsonl.py:24-145 | 122 | test/support |
| tests/contracts/test_rotation.py:19-35 | 17 | test/support |
| tests/adapters/test_applog.py:1-126 | 126 | test/support |
| tests/adapters/real/test_applog.py:1-57 | 57 | test/support |
| tests/stores/suites.py:131-185 | 55 | test/support |

**Volume:** 265 application/launcher + 377 test/support = **642** donor lines; **M 642, D 0, S 0**. Fixtures/goldens moving: **0**; app-specific records and their golden outputs remain consumer-owned. 

**Public interface** (at most six lines):

    RecordLog(path, *, encode, decode, rotation).append(record)
    log.read_from(offset=0, limit=None, *, max_bytes=None) -> Page
    log.tail(n, before=None); parse_bytes(data, offset, decode)
    compact(path, *, decode, keep, encode)
    tail_lines(path, *, max_bytes, errors='replace')
    AppendPool(max_open=16).append(path, data); .close_all()

**Consumers and adoption sites.** Task-loop JsonlStore/RotatingJsonl and trail append calls; dashboard live polling and records tails; delegate HistoryStore compaction. Shelf logging users gain the same implementation. No evidenced lifesim JSONL caller.

**Contracts that make it ownable:**

- Move the listed cursor, rotation, append-pool and LogContract tests; use neutral record fixtures and package-owned real/memory rigs.
- Pin Unicode byte offsets, skipped complete bad records, torn final lines, truncation resets and bounded poll progress.
- Pin append offsets across rotation, keep count and the separate unfinished-text-tail semantics.
- Pin fork ownership, close-on-exec, inode replacement, descriptor eviction and short-write/error behavior.
- Predicate compaction preserves original bytes/order and never silently substitutes rotated-file age retention for row-age retention.

**Production risk.** Dropped or repeated events, stalled dashboard cursors, lost accounting and deadlocks around inherited descriptors. Preserve surrogateescape in applog; do not silently rotate logs that were unrotated.

**Releasable migration.** 1. Add buffer parsing and byte budgets; tag and move cursor tests. 2. Add typed facade and memory log; migrate engine/dashboard separately, retaining Beat filtering in dashboard. 3. Add AppendPool, then predicate compaction; migrate trail and delegate history in separate app releases.

**Cost and replacement fit.** Medium to high; existing shelf package, no logging/structlog/orjson dependency required.

### A04 — ✅ extract: Captured execution, detached spawn and recorded process handles

**Shelf first.** stream-proc already owns streamed runs, held spawn, start tokens and tree stops: _shelf/packages/stream-proc/src/stream_proc/__init__.py:19-32, runner.py:25-43 and hold.py:24-66. any-proc.call uses a marked JSON result and is not a drop-in captured process call. Evolve stream-proc.

**What it does.** Runs or records a process with captured output, periodic callbacks and PID-reuse-safe stopping.

**Exact donor/call-site manifest.** These are the implementation sites and tests to move or replace; they also name the existing adapter entry points to retain during adoption.

| File:lines | Count | Ownership |
| --- | ---: | --- |
| src/taskloop/adapters/procs.py:1-134 | 134 | application/launcher |
| _delegate/src/delegate/adapters/procs.py:32-53 | 22 | application/launcher |
| _delegate/src/delegate/adapters/procs.py:81-91 | 11 | application/launcher |
| tests/adapters/test_procs.py:1-32 | 32 | test/support |
| tests/adapters/real/test_procs.py:1-112 | 112 | test/support |
| tests/adapters/real/test_kill_tree.py:1-90 | 90 | test/support |

**Volume:** 167 application/launcher + 234 test/support = **401** donor lines; **M 401, D 0, S 0**. Fixtures/goldens moving: **0**; app-specific records and their golden outputs remain consumer-owned. 

**Public interface** (at most six lines):

    capture(argv, *, cwd, env, timeout, tick=None) -> Capture
    spawn(argv, *, cwd, env, stdin=None) -> Process
    RecordedProcess(pid, *, start, pgid=None)
    stop(process, *, grace) -> StopEvidence
    process_table() -> Mapping[int, Proc] | None

**Consumers and adoption sites.** Task-loop adapters.procs capture/spawn/stop_pid/table; delegate run_capture/spawn/Orphan. Lifesim run_tests_parallel.py:28-30 could use capture after packaging is settled.

**Contracts that make it ownable:**

- Move test_procs, real/test_procs and real/test_kill_tree, preserving subprocess integration as real tests.
- Large stdout plus stderr cannot deadlock; incomplete final output and timeout partial output survive.
- A callback exception, timeout or SIGTERM during spawn leaves no child tree behind.
- A recycled PID must never be signalled; an unreadable process table stays unknown.
- Pinned app adapters preserve task-loop exit 124 and delegate TimeoutExpired behavior.

**Production risk.** An unintended signal can kill the wrong factory process; leaked children retain editor locks. StopEvidence must report actual signal attempts; never infer SIGKILL solely from elapsed grace.

**Releasable migration.** 1. Publish recorded handles and capture as additions with moved real tests. 2. Adopt task-loop through its current adapter, retaining exit/error mapping. 3. Adopt delegate piped spawn and Orphan; keep Worker, WorkerEnd and worker_end aggregation in delegate.

**Cost and replacement fit.** High safety burden, existing stdlib-only package. psutil is an untested backend alternative, not a reason to retain generic app code.

### A05 — ✅ extract: Cancellable lock acquisition and a faithful lock fake

**Shelf first.** process-lock already provides ProcessLock.acquire(timeout, on_wait, reentrant), holder and held: _shelf/packages/process-lock/src/process_lock/__init__.py:80-162. Missing is cancellation during waits and a public behaviorally faithful memory fake. Evolve this package.

**What it does.** Serializes contenders across threads and processes while supporting timeout, observation and cancellation.

**Exact donor/call-site manifest.** These are the implementation sites and tests to move or replace; they also name the existing adapter entry points to retain during adoption.

| File:lines | Count | Ownership |
| --- | ---: | --- |
| src/taskloop/adapters/locks.py:24-33 | 10 | application/launcher |
| src/taskloop/adapters/locks.py:66-92 | 27 | application/launcher |
| src/taskloop/stores/memory.py:129-170 | 42 | application/launcher |
| tests/adapters/test_locks_mutex.py:1-36 | 36 | test/support |
| tests/stores/suites.py:188-249 | 62 | test/support |

**Volume:** 79 application/launcher + 98 test/support = **177** donor lines; **M 177, D 0, S 0**. Fixtures/goldens moving: **0**; app-specific records and their golden outputs remain consumer-owned. 

**Public interface** (at most six lines):

    ProcessLock.acquire(path, *, timeout, reentrant=False, check=None, on_wait=None)
    lock.release(); holder(path) -> Holder | None
    testing.MemoryLocks(clock=...).acquire(key, ...)

**Consumers and adoption sites.** Task-loop hold_path and memory lock table; delegate locked already uses reentrant=False and timed acquisition. Shelf process-lock consumers inherit cancellation; lifesim unity_slot is only a potential adopter pending its own lock-contract review.

**Contracts that make it ownable:**

- Move the mutex test and LockContract with neutral keys and holder metadata.
- Two threads in one PID exclude each other when non-reentrant; a child inherits no owning descriptor.
- A live kernel lock is never broken because a metadata PID looks dead; a killed holder releases through the kernel.
- Pin zero/finite/infinite timeout, once-only app waiting notification and cancellation ordering.

**Production risk.** Broken exclusion permits concurrent land/gate/resource use. The current memory fake's stale-record takeover is not proof that real flock may be broken: expose backend differences and preserve the app holdouts.

**Releasable migration.** 1. Add cancellation and memory testing support; retain existing ProcessLock semantics. 2. Tag and replace only the poll/mutex mechanism, adapting repeated on_wait to the app's once-only notification. 3. Keep .holder encoding, LockWhat, resource naming and factory messages in task-loop.

**Cost and replacement fit.** Medium; filelock adds a wheel and does not establish holder metadata/cancellation/stale-process parity.

### A06 — ✅ extract: One Git substrate and one real/fake contract

**Shelf first.** git-porcelain already owns RealRepo, RealWorktree, Repo/Worktree protocols and FakeRepo/FakeWorktree: _shelf/packages/git-porcelain/src/git_porcelain/real.py:54-174, api.py:305-361, testing.py:31-99. Its real_cache/real_env/real_parse and fake_* modules are existing homes for this mechanism. Missing behavior must extend those homes; do not create a second generic Git library.

**What it does.** Runs and parses Git operations, discovers checkout topology, caches filesystem-vouched reads and supplies an in-process Git double.

**Exact donor/call-site manifest.** These are the implementation sites and tests to move or replace; they also name the existing adapter entry points to retain during adoption.

| File:lines | Count | Ownership |
| --- | ---: | --- |
| src/taskloop/adapters/git.py:1-325 | 325 | application/launcher |
| src/taskloop/adapters/git_base.py:1-150 | 150 | application/launcher |
| src/taskloop/adapters/git_ops.py:1-96 | 96 | application/launcher |
| src/taskloop/adapters/gitrepo.py:1-91 | 91 | application/launcher |
| src/taskloop/adapters/gitmemo.py:1-100 | 100 | application/launcher |
| src/taskloop/adapters/treehash.py:1-104 | 104 | application/launcher |
| _delegate/src/delegate/adapters/git.py:1-36 | 36 | application/launcher |
| tests/support/gitsim/read.py:1-226 | 226 | test/support |
| tests/support/gitsim/status.py:1-70 | 70 | test/support |
| tests/support/gitsim/ctx.py:1-76 | 76 | test/support |
| tests/support/gitsim/model.py:1-276 | 276 | test/support |
| tests/support/gitsim/remote.py:1-114 | 114 | test/support |
| tests/support/gitsim/rebase.py:1-119 | 119 | test/support |
| tests/support/gitsim/__init__.py:1-200 | 200 | test/support |
| tests/support/gitsim/diffs.py:1-142 | 142 | test/support |
| tests/support/gitsim/write.py:1-245 | 245 | test/support |
| tests/support/gitsim/refs.py:1-113 | 113 | test/support |
| tests/support/gitsim/trees.py:1-102 | 102 | test/support |
| tests/support/gitsim/ignore.py:1-74 | 74 | test/support |
| tests/support/fakegit.py:1-101 | 101 | test/support |
| tests/ports/git_contract.py:1-473 | 473 | test/support |
| tests/ports/git_contract_land.py:1-184 | 184 | test/support |
| tests/adapters/test_git_read_failures.py:1-85 | 85 | test/support |
| tests/adapters/test_git_status.py:1-25 | 25 | test/support |
| tests/adapters/test_git_cleanup.py:1-42 | 42 | test/support |
| tests/adapters/real/test_git_memo.py:1-162 | 162 | test/support |

**Volume:** 902 application/launcher + 2829 test/support = **3731** donor lines; **M 1874, D 1857, S 0**. Fixtures/goldens moving: **0**; app-specific records and their golden outputs remain consumer-owned. The entire 1,857-line tests/support/gitsim subtree is the D allocation, not a second extraction counted elsewhere.

**Public interface** (at most six lines):

    Repo.open(path, *, env, run) -> Repo
    repo.worktrees(); repo.snapshot(base); repo.diff(a, b)
    repo.worktree(path) -> Worktree
    worktree.status(); .stage(paths); .record(message, ...)
    repo.push(...); worktree.rebase(...); tree_state(...)
    testing.FakeRepo(...); testing.bind_commands(fake, runner)

**Consumers and adoption sites.** Task-loop RealGit/LandGit, treehash and all their consumers; delegate repo_root/state observation. Lifesim changed.py:65-108 is an evidenced future consumer of read-only diff/topology primitives, while its gate groups remain local. Existing shelf Git users benefit immediately.

**Contracts that make it ownable:**

- Move both Git contract suites and the listed adapter tests; keep task-loop land/gate/close scenario tests as consumer holdouts.
- Run the same contract against actual Git and the package fake: NUL/newline paths, renames, detached and linked worktrees, alternate indexes and untracked files.
- Malformed records and failed predicates remain unknown/errors, never clean/absent; cache only successful vouched reads.
- Pin ref/config invalidation, packed refs and reftable fallback; compare tree hashes after a second same-status edit.
- Preserve hook execution, force-with-lease failures, pinned checkout environment and explicit verification flags.

**Production risk.** Critical: a false clean tree, stale ref, swallowed failure, altered hooks or changed lease can land the wrong content. Git method names mentioning land or slots do not make raw Git behavior app policy; routing those results to land decisions remains local.

**Releasable migration.** 1. Move read/parser/cache contracts to shelf and implement missing outcomes additively; publish a tag. 2. Adapt task-loop's existing Git port and compare read results, then migrate writes by operation family under unchanged land tests. 3. Replace gitsim algorithms with the shelf fake plus the minimal command binding; move the remaining generic contract tests and remove the duplicate simulator only after both implementations agree. 4. Adopt delegate observations, then lifesim reads.

**Cost and replacement fit.** High refactor, critical runtime risk, by far the largest volume. Of 3,731 gross lines, 1,857 are the duplicate simulator to delete after parity, 1,874 are mechanisms/contracts to transfer. A new shelf command-binding shim is replacement cost, not free.

### A07 — ✅ extract: Directory resolution, environment cleanup and layered configuration

**Shelf first.** app-dirs already exposes config_dir/state_dir/cache_dir/plugin_data_dir at _shelf/packages/app-dirs/src/app_dirs/__init__.py:36-68; child-env.scrub/scrub_current are at _shelf/packages/child-env/src/child_env/__init__.py:70-80. settings-base.resolve_config_path/resolve_env_refs and SecretStrippingYamlSource live at _shelf/packages/settings-base/src/settings_base/__init__.py:41-77. Missing: installed-plugin-path discovery, pure virtualenv removal and JSON mapping merge.

**What it does.** Resolves application storage roots and builds clean layered inputs without owning application schemas.

**Exact donor/call-site manifest.** These are the implementation sites and tests to move or replace; they also name the existing adapter entry points to retain during adoption.

| File:lines | Count | Ownership |
| --- | ---: | --- |
| src/taskloop/adapters/ident.py:14-21 | 8 | application/launcher |
| _delegate/src/delegate/app/env.py:33-42 | 10 | application/launcher |
| _delegate/src/delegate/app/env.py:57-62 | 6 | application/launcher |
| src/taskloop/adapters/childenv.py:16-26 | 11 | application/launcher |

**Volume:** 35 application/launcher + 0 test/support = **35** donor lines; **M 35, D 0, S 0**. Fixtures/goldens moving: **0**; app-specific records and their golden outputs remain consumer-owned. 

**Public interface** (at most six lines):

    installed_plugin_data(here: Path) -> Path | None
    config_dir(app, *, env, home, create=False) -> Path
    without_virtualenv(env: Mapping[str, str]) -> dict[str, str]
    merge_mapping(base, override) -> dict

**Consumers and adoption sites.** Task-loop ident.config_dir/childenv.without_venv; delegate env.plugin_data_dir/deep_merge. Lifesim script configuration is prospective. app-dirs and settings-base's current shelf consumers provide reconciliation opportunities.

**Contracts that make it ownable:**

- Installed cache path resolves the correct plugin/marketplace; a checkout yields no invented plugin data directory.
- Pin explicit override precedence, relative XDG handling and creation/mode behavior.
- Virtualenv cleanup removes only its own bin entry, preserving other PATH entries and the input mapping.
- Merge recursively copies base mappings and preserves current list/scalar replacement semantics.

**Production risk.** Moving state roots can split live state. app-dirs ignores relative XDG values while task-loop accepts them; retain a compatibility choice instead of relocating state silently. Delegate intentionally ignores the launching plugin's CLAUDE_PLUGIN_DATA.

**Releasable migration.** 1. Add the three missing operations to their existing package owners. 2. Tag and adopt virtualenv removal first, merge second, installed-path resolution last. 3. Keep task-loop path/layout methods, environment allowlists, hook injection, delegate profile routing and all defaults in the apps.

**Cost and replacement fit.** Low code volume; medium migration risk. platformdirs may choose native macOS folders and cannot silently replace the current POSIX/XDG layout; pydantic-settings adds an unnecessary runtime dependency here.

### A08 — ✅ extract: Time input and presentation dialects

**Shelf first.** timefmt already owns fmt_dur/fmt_span/fmt_until/human_count: _shelf/packages/timefmt/src/timefmt/__init__.py:28-97. due-schedule.parse_interval/schedule_is_due exist at _shelf/packages/due-schedule/src/due_schedule/__init__.py:31-110. Missing are absolute/relative future parsing, epoch-ms handling and next-weekly-local calculation.

**What it does.** Parses human time inputs and formats waits while keeping a caller-supplied clock.

**Exact donor/call-site manifest.** These are the implementation sites and tests to move or replace; they also name the existing adapter entry points to retain during adoption.

| File:lines | Count | Ownership |
| --- | ---: | --- |
| src/taskloop/domain/timespec.py:1-26 | 26 | application/launcher |
| _delegate/src/delegate/domain/time/spec.py:1-64 | 64 | application/launcher |
| src/taskloop_dash/tails.py:11-23 | 13 | application/launcher |

**Volume:** 103 application/launcher + 0 test/support = **103** donor lines; **M 103, D 0, S 0**. Fixtures/goldens moving: **0**; app-specific records and their golden outputs remain consumer-owned. 

**Public interface** (at most six lines):

    parse_time(value, *, now, dialect) -> float | None
    next_weekly(spec, *, now) -> float | None
    format_wait(seconds, *, style) -> str
    format_local(epoch, *, style) -> str

**Consumers and adoption sites.** Task-loop domain.timespec.parse_future and dashboard tails.parse_ts; delegate time.spec helpers. Existing shelf scheduling/formatting users can reuse extensions; no evidenced lifesim caller.

**Contracts that make it ownable:**

- Pin each dialect's seconds versus milliseconds cutoff, ISO timezone behavior and invalid-input contract.
- HH:MM and weekday requests roll forward exactly at equality; test DST folds and gaps explicitly.
- Preserve delegate <1m and spacing separately from existing timefmt strings.
- Pure functions use injected now and leave no host-clock-dependent test results.

**Production risk.** An early wake or a timezone mistake releases a hold at the wrong time. due-schedule's due predicate is not equivalent to returning a next reset timestamp.

**Releasable migration.** 1. Extract existing dialects unchanged with boundary tables. 2. Publish due-schedule/timefmt additions and migrate formatting before parsing. 3. Keep hold eligibility, reset policy and scheduling defaults in apps; consolidate dialects only in a separately reviewed behavior change.

**Cost and replacement fit.** Low to medium. datetime.fromisoformat already does ISO decoding; dateutil/dateparser are not needed for the supported grammar and would broaden accepted inputs.

### A09 — ✅ extract: Opaque sortable IDs and numeric dotted versions

**Shelf first.** No shelf ID or numeric-version package exists in the catalog. Use new opaque-id for the extracted implementation; keep numeric version parsing in the generic install helper of A16 rather than creating a second version library.

**What it does.** Generates/parses 26-character sortable random IDs and compares dotted numeric releases.

**Exact donor/call-site manifest.** These are the implementation sites and tests to move or replace; they also name the existing adapter entry points to retain during adoption.

| File:lines | Count | Ownership |
| --- | ---: | --- |
| packages/kernel/src/tlkernel/ids.py:31-84 | 54 | application/launcher |
| packages/kernel/src/tlkernel/ids.py:87-106 | 20 | application/launcher |
| tests/contracts/test_wire.py:202-209 | 8 | test/support |
| tests/contracts/test_wire.py:218-224 | 7 | test/support |

**Volume:** 74 application/launcher + 15 test/support = **89** donor lines; **M 89, D 0, S 0**. Fixtures/goldens moving: **0**; app-specific records and their golden outputs remain consumer-owned. 

**Public interface** (at most six lines):

    SortableId.new(now, *, entropy=None) -> SortableId
    SortableId.parse(text); SortableId.of(text)
    id.to_wire() -> str
    NumericVersion.parse(text) -> NumericVersion

**Consumers and adoption sites.** Task-loop RunId.new/parse/of and Version.parse, notably RunLocator.create and release/catalog.version_tuple. Delegate can consume release ordering later. Lifesim: no evidenced ID requirement.

**Contracts that make it ownable:**

- Move the listed ID and version tests with neutral type names.
- Pin zero/max timestamps, supplied entropy bytes, invalid alphabet, overflow and first-character bound.
- Pin lexical ordering and equality/hash/wire round trips; do not add monotonic same-millisecond behavior.
- Numeric versions reject v1, empty components and non-ASCII digits, preserving current tuple ordering.

**Production risk.** Changed ID bytes lose run lookup; changed version ordering changes rollback targets. uuid4/uuid7 are not wire-compatible; packaging.version admits a different language; python-ulid parity is untested.

**Releasable migration.** 1. Publish exact current generators/parsers as generic types and keep app aliases. 2. Adopt under tags and unchanged old-ID fixtures. 3. Trial python-ulid only behind the same wire contract; keep the app BeadId grammar and repo/loop key formulas local.

**Cost and replacement fit.** Low; a third-party ULID wheel is disproportionate unless its contract wins.

### A10 — ✅ extract: Safe local HTTP files, file caches and bind lifecycle

**Shelf first.** any-file already provides resolve_within and media_type at _shelf/packages/any-file/src/any_file/__init__.py:108-155. async-scope.asgi.bind_loopback/serve_asgi exist at _shelf/packages/async-scope/src/async_scope/asgi.py:39-197 but do not implement this synchronous multi-address server. llm-cache stores Completion values in SQLite, not filesystem-signature or per-call TTL values. Add local-http and file-cache, composing any-file; avoid forcing an ASGI rewrite.

**What it does.** Serves bounded allowed files within a root, caches computed values, and rolls back partial server binds.

**Exact donor/call-site manifest.** These are the implementation sites and tests to move or replace; they also name the existing adapter entry points to retain during adoption.

| File:lines | Count | Ownership |
| --- | ---: | --- |
| src/taskloop_dash/assets.py:1-36 | 36 | application/launcher |
| src/taskloop_dash/cache.py:1-72 | 72 | application/launcher |
| src/taskloop_dash/bind.py:96-108 | 13 | application/launcher |
| src/taskloop_dash/http.py:55-63 | 9 | application/launcher |
| tests/dash/test_dash_assets.py:1-61 | 61 | test/support |

**Volume:** 130 application/launcher + 61 test/support = **191** donor lines; **M 191, D 0, S 0**. Fixtures/goldens moving: **0**; app-specific records and their golden outputs remain consumer-owned. 

**Public interface** (at most six lines):

    StaticFiles(root, *, suffixes, deny, max_bytes).get(path)
    send_response(handler, response, *, headers)
    bind_all(addresses, port, handler) -> Servers
    FileCache(limit=500).get(path, loader, missing=None)
    TtlCache(clock).get(key, ttl, factory); .peek/.put/.drop/.clear

**Consumers and adoption sites.** Dashboard static_file, HTTP H.send, bind.open_servers and cache classes. Task-loop RunLocator's manifest cache is a later adapter target. Delegate snapshot caching is prospective; no confirmed lifesim HTTP consumer.

**Contracts that make it ownable:**

- Move test_dash_assets, substituting StaticFiles directly for app routing; retain app route tests.
- Encoded traversal, dotfiles, NULs, backslashes, symlink escape, suffix denial and byte caps reproduce current results.
- Failure binding a later address closes earlier servers; port zero is reused consistently.
- Pin cache missing-file eviction, loader failure, LRU eviction, per-call TTL and current duplicate-computation concurrency behavior.

**Production risk.** Serving files outside the root or binding a public address exposes factory state. Keep bind_refusal, Tailscale ranges, default ports, API routes and all POST authorization in the app.

**Releasable migration.** 1. Publish contained static files and file cache with moved tests. 2. Adopt cache/static reads under tags. 3. Extract bind rollback and response writing with callbacks; keep app allow-address checks before binding. Do not silently change oversized POST handling or add cache single-flight semantics.

**Cost and replacement fit.** Medium. Starlette/FastAPI add several dependencies and an async lifecycle; http.server already provides HTTP parsing. diskcache changes storage and concurrency semantics; it is not a drop-in FileCache.

### A11 — ✅ extract: Lazy CLI dispatch and namespace projection

**Shelf first.** verb-cli already exposes flags_of, to_argparse and kwargs_of in _shelf/packages/verb-cli/src/verb_cli/__init__.py. It lacks lazy invocation with injected context, but its stdlib implementation is an appropriate home for this dispatch seam.

**What it does.** Imports a command only when invoked and projects parsed namespace/context into its function arguments.

**Exact donor/call-site manifest.** These are the implementation sites and tests to move or replace; they also name the existing adapter entry points to retain during adoption.

| File:lines | Count | Ownership |
| --- | ---: | --- |
| skills/task-loop/tl.py:312-331 | 20 | application/launcher |

**Volume:** 20 application/launcher + 0 test/support = **20** donor lines; **M 20, D 0, S 0**. Fixtures/goldens moving: **0**; app-specific records and their golden outputs remain consumer-owned. 

**Public interface** (at most six lines):

    lazy_call(module, name, *, args=(), context=()) -> Callable
    invoke(handler, namespace, context) -> int

**Consumers and adoption sites.** Task-loop tl.py lazy/lazy_env/of_args; delegate verbs can adopt when handlers are given typed signatures. Lifesim script CLIs are prospective, not an asserted existing use.

**Contracts that make it ownable:**

- An unused command imports nothing; selected command imports once through normal Python caching.
- Preserve exceptions and integer exit conversion.
- One/multiple namespace fields and explicit context injection produce the same arguments.

**Production risk.** A changed lazy import boundary makes tl actor slow or drags heavy dependencies into a hook. Delegate CallParser.error's exit-zero bad_request answer is worker protocol and stays local.

**Releasable migration.** 1. Add context-agnostic lazy dispatch to verb-cli, retaining current invocation behavior. 2. Tag and replace the three wrappers. 3. Migrate repetitive parser declarations only after defining typed command signatures; no speculative additional line savings are counted.

**Cost and replacement fit.** Low for dispatch. Typer/Click do not remove command policy and would add runtime packaging/help/exit compatibility costs.

### A12 — ✅ extract: Browser formatting and escaped Markdown subset

**Shelf first.** timefmt has Python formatters but no browser ES module. any-markdown has Python sections/outline and chunk/budget APIs (_shelf/packages/any-markdown/src/any_markdown/sections.py:58-127), not this HTML renderer. Add browser exports to the owning packages rather than a new app-specific UI library.

**What it does.** Formats numeric/time values and renders a deliberately restricted, escaped Markdown subset.

**Exact donor/call-site manifest.** These are the implementation sites and tests to move or replace; they also name the existing adapter entry points to retain during adoption.

| File:lines | Count | Ownership |
| --- | ---: | --- |
| src/taskloop_dash/static/js/format.js:9-35 | 27 | application/launcher |
| src/taskloop_dash/static/js/format.js:47-58 | 12 | application/launcher |
| src/taskloop_dash/static/js/format.js:60-84 | 25 | application/launcher |

**Volume:** 64 application/launcher + 0 test/support = **64** donor lines; **M 64, D 0, S 0**. Fixtures/goldens moving: **0**; app-specific records and their golden outputs remain consumer-owned. 

**Public interface** (at most six lines):

    dur(seconds); age(timestamp, now); unit(seconds); tokens(count)
    pct(number); clock(timestamp); day(timestamp, now)
    esc(text); md(text) -> string

**Consumers and adoption sites.** Dashboard ES module imports. Other shelf/static-page consumers and lifesim browser tools are prospective; Python timefmt is conceptual reuse, not evidence that these exact browser dialects already have two consumers.

**Contracts that make it ownable:**

- Pin rounding at second/minute/hour/day and k/M boundaries, nulls, negatives and zero tokens.
- Pin local calendar-day labels and DST boundaries, not elapsed 24-hour approximations.
- Escaping precedes markup; scripts, quotes, malformed fences and nested marker text remain inert.
- Snapshot the currently supported paragraph/list/header subset and exact output.

**Production risk.** HTML injection or changed dashboard labels; markdown-it plus DOMPurify would accept different markup and need a checked-in offline JS distribution.

**Releasable migration.** 1. Publish browser modules with exact current strings/markup and package-local tests. 2. Pin and copy their tagged artifacts through the current no-build vendor path. 3. Keep MARK/MARK_TONE, bid and project-state decisions in the dashboard; evaluate broader Markdown support separately.

**Cost and replacement fit.** Low extraction; third-party renderer replacement untested. No Python dependency can execute in the page.

### A13 — ✅ extract: Shell text analysis beneath worker policy

**Shelf first.** No shelf shell parser exists. child-env.scrub handles environment values, not syntax. New shell-words should compose shlex.split and posixpath.basename; shlex is already used at these call sites and cannot alone parse shell control operators.

**What it does.** Unwraps shell -c layers and splits unquoted command pieces while identifying redirections and assignments.

**Exact donor/call-site manifest.** These are the implementation sites and tests to move or replace; they also name the existing adapter entry points to retain during adoption.

| File:lines | Count | Ownership |
| --- | ---: | --- |
| _delegate/src/delegate/domain/policy/matchers.py:26-37 | 12 | application/launcher |
| _delegate/src/delegate/domain/policy/matchers.py:73-126 | 54 | application/launcher |
| _delegate/src/delegate/domain/policy/matchers.py:129-135 | 7 | application/launcher |
| _delegate/src/delegate/domain/policy/shell.py:90-94 | 5 | application/launcher |

**Volume:** 78 application/launcher + 0 test/support = **78** donor lines; **M 78, D 0, S 0**. Fixtures/goldens moving: **0**; app-specific records and their golden outputs remain consumer-owned. 

**Public interface** (at most six lines):

    analyze(command, *, unwrap_depth=3) -> ShellText | ParseFailure
    analysis.commands -> tuple[tuple[str, ...], ...]
    analysis.has_substitution; analysis.has_output_redirect
    strip_assignments(words) -> tuple[str, ...]

**Consumers and adoption sites.** Delegate policy.matchers.pieces/unwrap and shell.after_assignments; task-loop hook parsing is a future consumer only if the package remains plain-stdlib Python. Lifesim command checks are prospective.

**Contracts that make it ownable:**

- Quoted/escaped separators, nested shell -c options, loops and malformed quotes reproduce current results.
- Descriptor redirects and /dev/null exclusions preserve current classification.
- Leading NAME=value assignments are distinguished from commands.
- Adversarial examples prove this is a heuristic analyzer, never a security sandbox or an authorization decision.

**Production risk.** An incorrect parse can bypass a worker guard or falsely block work. The app retains READ_CMDS, READ_GIT, secret-path policy, git ownership, allowed recipes and denial text.

**Releasable migration.** 1. Move syntax mechanics with no app imports and retain callback seams for domain filters. 2. Tag and switch pieces/unwrap behind the existing guard. 3. Compare every existing worker-policy fixture; bashlex/tree-sitter parsing may replace the backend only after malformed-input and security parity.

**Cost and replacement fit.** Medium; a third-party parser is not allowed in the plain hook without an explicit distribution/interpreter decision.

### A14 — ✅ extract: Agent event and transcript reading substrate

**Shelf first.** No shelf package reads these agent CLI streams or OpenCode sessions. anyllm's completion API does not expose CLI tool events or historical session storage; jsonl-log only supplies file/cursor mechanics. Create agent-stream, composing jsonl-log and stdlib sqlite3.

**What it does.** Decodes vendor stream events and reads session transcripts into neutral observations without choosing an execution outcome.

**Exact donor/call-site manifest.** These are the implementation sites and tests to move or replace; they also name the existing adapter entry points to retain during adoption.

| File:lines | Count | Ownership |
| --- | ---: | --- |
| src/taskloop/adapters/opencode.py:1-86 | 86 | application/launcher |
| _delegate/src/delegate/adapters/harness/claude.py:105-181 | 77 | application/launcher |
| _delegate/src/delegate/adapters/harness/codex.py:80-161 | 82 | application/launcher |
| _delegate/src/delegate/adapters/harness/opencode.py:171-248 | 78 | application/launcher |
| _delegate/src/delegate/adapters/harness/opencode.py:261-275 | 15 | application/launcher |
| tests/adapters/test_opencode.py:1-169 | 169 | test/support |

**Volume:** 338 application/launcher + 169 test/support = **507** donor lines; **M 507, D 0, S 0**. Fixtures/goldens moving: **0**; app-specific records and their golden outputs remain consumer-owned. 

**Public interface** (at most six lines):

    StreamReader(vendor, *, clock, on_denial=None)
    reader.feed(line) -> tuple[Observation, ...]
    reader.feed_log(line) -> tuple[Observation, ...]
    reader.facts() -> StreamFacts
    SessionStore(vendor, *, root).find(ref); .context(ref)

**Consumers and adoption sites.** Delegate Claude/Codex/OpenCode parse_line and parse_log_line; task-loop opencode_rows/context/transcript_of. Dashboard observes their normalized results. No evidenced lifesim agent-stream reader.

**Contracts that make it ownable:**

- Move test_opencode with injected roots and read-only temporary SQLite; add provider stream fixtures owned by this package.
- Torn/malformed/unknown events preserve current skip/Unknown behavior, ordering and provisional tool identity.
- Pin tool start/end matching, first result selection and duplicate message handling.
- Missing/locked/foreign-schema OpenCode databases remain empty/unknown and open strictly mode=ro.
- The generic package imports no delegate/taskloop types and never decides retry, success, worker denial or lane health.

**Production risk.** Incorrect event identity or terminal facts can end a paid run early or lose its answer. Keep launch permissions, WorkerEnd, summary outcome overrides and stop-reason mapping in delegate; _tool calls an injected denial observer rather than importing app sandbox policy.

**Releasable migration.** 1. Introduce package-neutral event/state records and move OpenCode readers with tests. 2. Tag and adopt task-loop reads. 3. Move one delegate vendor parser at a time behind an adapter mapping observations to HarnessEvents; retain supervisor/settlement holdouts. 4. Consolidate transcript discovery with explicit roots; no credential or login access is needed for this extraction.

**Cost and replacement fit.** High refactor, medium operational risk. Provider protocol decoding should be shared even though no general JSON library performs it.

### A15 — ✅ extract: Usage payload decoding and accounting folds

**Shelf first.** No shelf package owns vendor usage normalization. anyllm has completion usage but not CLI subscription-window payloads; jsonl-log stores the records without interpreting them. Put the decoders in agent-stream. Do not create a second agent-accounting library.

**What it does.** Normalizes vendor usage/cache counters and folds reported costs without selecting a lane.

**Exact donor/call-site manifest.** These are the implementation sites and tests to move or replace; they also name the existing adapter entry points to retain during adoption.

| File:lines | Count | Ownership |
| --- | ---: | --- |
| _delegate/src/delegate/adapters/harness/claude.py:40-71 | 32 | application/launcher |
| _delegate/src/delegate/adapters/harness/opencode.py:54-81 | 28 | application/launcher |
| _delegate/src/delegate/app/usage.py:85-100 | 16 | application/launcher |

**Volume:** 76 application/launcher + 0 test/support = **76** donor lines; **M 76, D 0, S 0**. Fixtures/goldens moving: **0**; app-specific records and their golden outputs remain consumer-owned. 

**Public interface** (at most six lines):

    decode_usage(vendor, payload) -> Usage | None
    fold_usage(vendor, requests) -> Usage | None
    decode_windows(payload, *, parse_time) -> tuple[Window, ...]
    with_price_source(usage, source) -> Usage

**Consumers and adoption sites.** Delegate Claude input_of/tokens_of/stream_usage/acct_of, OpenCode acct_close/acct_fold and usage.normalize_usage; task-loop/dashboard can consume the neutral output after their wire adapters. No demonstrated lifesim use.

**Contracts that make it ownable:**

- Cached reads/writes are included in total input exactly once; reasoning tokens are counted as currently reported.
- Unknown/missing cost stays unknown; an observed zero is not an invented free price.
- Duplicate or partial requests retain current fold behavior and recorded TTL provenance.
- Pin plan/windows wrapper variants, unmatched labels and malformed reset values.

**Production risk.** Bad accounting can exhaust budget or prematurely reject a lane. Keep price policy, thresholds, lane bindings, authentication caches and reader selection in delegate.

**Releasable migration.** 1. Extract payload decoding/folding with vendor fixtures to agent-stream. 2. Publish/tag and use adapters that retain the old dictionaries. 3. Adopt neutral usage types in task-loop only in a separate wire-contract release.

**Cost and replacement fit.** Medium. No pandas, pydantic or HTTP client is justified for these small pure decoders.

### A16 — ✅ extract: Installed release catalog, integrity manifests and exec teardown

**Shelf first.** app-dirs resolves directories but does not enumerate installed release artifacts. plugin-surface.load_surface discovers Python manifests, not installed plugin versions. dir-trust.folder_hash/TrustStore (_shelf/packages/dir-trust/src/dir_trust/__init__.py:38-58) hashes/grants trust, not per-file release manifests. Evolve app-dirs with installed-artifact discovery, dir-trust with integrity manifests, and stream-proc with exec teardown.

**What it does.** Lists valid installed artifacts, verifies their file hashes and closes resources before replacing a process.

**Exact donor/call-site manifest.** These are the implementation sites and tests to move or replace; they also name the existing adapter entry points to retain during adoption.

| File:lines | Count | Ownership |
| --- | ---: | --- |
| src/taskloop/app/release/catalog.py:12-54 | 43 | application/launcher |
| src/taskloop/app/release/manifest.py:1-38 | 38 | application/launcher |
| src/taskloop/app/release/reexec.py:73-76 | 4 | application/launcher |
| tests/release/test_manifest.py:22-53 | 32 | test/support |

**Volume:** 85 application/launcher + 32 test/support = **117** donor lines; **M 117, D 0, S 0**. Fixtures/goldens moving: **0**; app-specific records and their golden outputs remain consumer-owned. 

**Public interface** (at most six lines):

    InstalledArtifacts(root, *, plugin, marker, parse_version).versions()
    artifacts.previous(version); artifacts.installed(index, scope)
    IntegrityManifest(root, *, name).build(files); .verify()
    exec_replace(argv, env, *, before_exec=()) -> Never

**Consumers and adoption sites.** Task-loop release/catalog, release/manifest and reexec.exec_in_place; delegate installed-path discovery can share the catalog later. Existing shelf directory/trust/process users can reuse their respective extensions.

**Contracts that make it ownable:**

- Move the Manifest test methods; leave DoctorInstall and its Ownership expectation in task-loop.
- Exclude the manifest itself and unreadable inputs; report removed or altered files deterministically.
- Ignore half-copied release directories and invalid numeric versions; preserve installed scope and duplicate precedence.
- Close callbacks run before exec with exact argv/environment and propagate failures without pretending exec succeeded.

**Production risk.** Wrong version selection changes rollback; false integrity success hides a modified plugin; bad exec arguments lose the live process. Keep pin/rollback decisions, CODE, main-release selection, checkpoint handover and app environment markers local.

**Releasable migration.** 1. Add manifest building/checking and move tests; tag/adopt doctor compatibility. 2. Add parameterized installed catalog, depending on A09 numeric versions, and adopt reads only. 3. Add exec teardown after A03 pool lifecycle; keep reexec_args and all run handover decisions local.

**Cost and replacement fit.** Medium; no self-update framework or packaging.version is a proven replacement.

### A17 — ✅ extract: Process simulation and pytest guard mechanics

**Shelf first.** stream-proc has the real process contract but no public simulation/testing API; _shelf/packages/stream-proc/src/stream_proc/runner.py:25-43 defines the Result the fake already produces. Promote the generic simulation into stream_proc.testing with a pytest-only extra. Do not create another simulator package.

**What it does.** Answers process calls in memory and detects tests that accidentally spawn, fork or never exercise their declared real-process subject.

**Exact donor/call-site manifest.** These are the implementation sites and tests to move or replace; they also name the existing adapter entry points to retain during adoption.

| File:lines | Count | Ownership |
| --- | ---: | --- |
| tests/support/procsim.py:1-32 | 32 | test/support |
| tests/support/procsim.py:54-84 | 31 | test/support |
| tests/support/procsim.py:96-125 | 30 | test/support |
| tests/support/procsim.py:128-249 | 122 | test/support |
| tests/conftest.py:63-100 | 38 | test/support |
| tests/conftest.py:112-130 | 19 | test/support |
| tests/rules/test_procsim.py:1-71 | 71 | test/support |
| tests/rules/real/test_procsim.py:1-18 | 18 | test/support |

**Volume:** 0 application/launcher + 361 test/support = **361** donor lines; **M 361, D 0, S 0**. Fixtures/goldens moving: **0**; app-specific records and their golden outputs remain consumer-owned. 

**Public interface** (at most six lines):

    ProcessWorld(test_id, *, guarded, defaults=())
    world.register(argv, fake, *, prefix=False)
    world.install(exit_stack); world.check(must_spawn=False)
    exits(code, output=''); takes(seconds, ...); blocks(...)
    pytest_guard(*, kind_of, limits, serial, scale)

**Consumers and adoption sites.** Task-loop logic/real suites; delegate can use the same guard when tests are supplied; shelf stream-proc and other process packages can own their fakes. Lifesim tools/tests is an evidenced process-heavy test consumer, not yet an adopter.

**Contracts that make it ownable:**

- Move tests/rules/test_procsim.py and real/test_procsim.py with the implementation and generic fixture.
- Pin subprocess and stream-proc parity, env-prefix forwarding, captured output and timeout simulation.
- A caught spawn/fork error still fails teardown; a declared real test without I/O still fails.
- Scoped install restores every patched function and does not leak worlds between tests/workers.

**Production risk.** A weakened guard hides real processes inside fast tests and can run engine checks during tests. Keep default has-f/markers fixtures, the tl-nobd sentinel, serial membership and time budgets in task-loop.

**Releasable migration.** 1. Extract the listed mechanics with injected defaults/kind/limit policies and moved tests. 2. Publish a testing-extra tag and adopt the task-loop fixture without changing kind classification. 3. Offer the same contract to shelf and delegate; keep consumer-specific fake commands local.

**Cost and replacement fit.** Medium refactor, low production risk; runtime installs must not acquire pytest.

### A18 — ✅ extract: Container-aware memory availability

**Shelf first.** any-proc already owns CPU availability by affinity/cgroup in its catalog and process-limit helpers in _shelf/packages/any-proc/src/any_proc/run.py:92-130. Missing is the analogous memory-headroom observation. Extend that owner, pending its documented any-os reconciliation.

**What it does.** Reports usable host/container RAM without pretending host MemAvailable is the container limit.

**Exact donor/call-site manifest.** These are the implementation sites and tests to move or replace; they also name the existing adapter entry points to retain during adoption.

| File:lines | Count | Ownership |
| --- | ---: | --- |
| src/taskloop/app/release/suite.py:51-85 | 35 | application/launcher |
| tests/release/test_cgroup_memory.py:1-53 | 53 | test/support |

**Volume:** 35 application/launcher + 53 test/support = **88** donor lines; **M 88, D 0, S 0**. Fixtures/goldens moving: **0**; app-specific records and their golden outputs remain consumer-owned. 

**Public interface** (at most six lines):

    available_memory_mb(*, probe=None) -> int | None
    cgroup_memory_headroom_mb(*, probe=None) -> int | None

**Consumers and adoption sites.** Task-loop release/suite.available_mb and host_available_mb; lifesim run_tests_parallel.py:39 uses CPU-only pool sizing and is an evidenced future resource-limit consumer. any-proc limits/supervision can reuse the probe; delegate is prospective.

**Contracts that make it ownable:**

- Move test_cgroup_memory with injected fake filesystem probe.
- Pin memory.max='max', missing/malformed counters and cgroup-root paths.
- Clamp negative headroom to zero and combine known/unknown host and cgroup values correctly.
- Preserve current POSIX fallback behavior; cgroup v1 support is additive, not silently assumed.

**Production risk.** Overstated memory allows too many suite workers and can kill the running factory through OOM. Keep WORKER_BUDGET_MB and worker-count/refusal policy in task-loop.

**Releasable migration.** 1. Publish memory probes and moved tests. 2. Tag/adopt observation only. 3. Review affinity-aware CPU/worker-budget changes separately; do not mix a new resource policy into the extraction.

**Cost and replacement fit.** Low to medium; psutil.virtual_memory by itself does not establish the cgroup-headroom contract.

### A19 — ✅ extract: Finish atomic-write adoption

**Shelf first.** atomic_write_text already exists at _shelf/packages/atomic-io/src/atomic_io/__init__.py:51-60. No missing API and no new package.

**What it does.** Replaces the remaining hand-written temporary-file-plus-replace sequences with the shelf writer.

**Exact donor/call-site manifest.** These are the implementation sites and tests to move or replace; they also name the existing adapter entry points to retain during adoption.

| File:lines | Count | Ownership |
| --- | ---: | --- |
| src/taskloop/stores/call_state.py:47-48 | 2 | application/launcher |
| src/taskloop/stores/call_state.py:52-53 | 2 | application/launcher |
| src/taskloop/stores/call_state.py:66-69 | 4 | application/launcher |
| src/taskloop/adapters/storm.py:50-53 | 4 | application/launcher |
| src/taskloop_dash/serve.py:63-66 | 4 | application/launcher |
| src/taskloop_dash/readers/beads.py:73-76 | 4 | application/launcher |

**Volume:** 20 application/launcher + 0 test/support = **20** donor lines; **M 20, D 0, S 0**. Fixtures/goldens moving: **0**; app-specific records and their golden outputs remain consumer-owned. 

**Public interface** (at most six lines):

    atomic_write_text(path, text, *, fsync=False, keep_mode=True)

**Consumers and adoption sites.** Task-loop CallState.save/returned and write_storm; dashboard serve.start PID publication and Beads._share. Delegate already uses atomic-io; no additional savings are counted for completed adoption.

**Contracts that make it ownable:**

- Preserve existing JSON encoding/newline bytes and existing/new file permission behavior.
- Write/replace failure keeps the previous file and removes temporary debris.
- An injected crash after raw answer publication but before phase change remains recoverable.

**Production risk.** Changed mode or serialization can break state readers; answer publication must remain before checkpoint publication. Atomic replacement does not make storm's check-then-write a lock.

**Releasable migration.** 1. Pin bytes/modes as holdouts. 2. Replace dashboard cache and PID writes first, storm next. 3. Replace checkpoint writes last under unchanged save/returned sequencing. atomic_write_json's formatting must not be substituted implicitly.

**Cost and replacement fit.** Low; keep_mode fallback/umask behavior must be selected explicitly.

### A20 — ✅ extract: Retry sequence evaluation beneath retry policy

**Shelf first.** any-proc.Supervisor owns a restart budget/backoff (_shelf/packages/any-proc/src/any_proc/supervise.py:71-241), not a reusable pure rest-table evaluator. Evolve its scheduling mechanics rather than invent a tenacity wrapper per app.

**What it does.** Computes capped/jittered delays and repeating rest sequences from caller-provided parameters.

**Exact donor/call-site manifest.** These are the implementation sites and tests to move or replace; they also name the existing adapter entry points to retain during adoption.

| File:lines | Count | Ownership |
| --- | ---: | --- |
| src/taskloop/domain/lanes/retry.py:41-55 | 15 | application/launcher |
| src/taskloop/domain/lanes/pauses.py:86-88 | 3 | application/launcher |
| src/taskloop/domain/checks/retry.py:10-18 | 9 | application/launcher |

**Volume:** 27 application/launcher + 0 test/support = **27** donor lines; **M 27, D 0, S 0**. Fixtures/goldens moving: **0**; app-specific records and their golden outputs remain consumer-owned. 

**Public interface** (at most six lines):

    RetrySchedule(limit, rests).left(used); .rest(used)
    budgeted_waits(rests, *, total) -> tuple[float, ...]
    capped_jitter(attempt, *, base, cap, random) -> float

**Consumers and adoption sites.** Task-loop RetryPlan, pauses.delay and checks.lock_waits; any-proc restart backoff is a second generic consumer candidate. Delegate can use the mechanism while keeping lane health policy local.

**Contracts that make it ownable:**

- Empty rests mean zero; the last rest repeats; retry counts keep their current indexing.
- Clamp exponents before evaluation and preserve cap-before-jitter, including negative attempts.
- The wait sequence sums exactly to its budget with a clipped final element.
- Randomness and clock are injected, so parity tests never sleep.

**Production risk.** Changing retry indexing, cap/jitter ordering or delay totals changes paid attempts and factory load. ROWS, TABLE, reason permanence and compile/import retry eligibility remain app policy.

**Releasable migration.** 1. Move only the evaluator and add table-driven contracts. 2. Tag/adopt with current rows and constants passed explicitly. 3. Keep pause persistence, reroute/ask/fault actions and unknown-reason owner escalation local.

**Cost and replacement fit.** Low substrate volume; tenacity's stop/wait building blocks are possible, but its execution decorator does not own durable pause state or lane actions.

### A21 — ✅ extract: Repository analysis and test-output presentation

**Shelf first.** blueprint already detects/checks repositories through _shelf/packages/blueprint/src/blueprint/__main__.py:37-55 and runner.py:154 onward. It lacks these portable AST measurements and pytest-output projections. Extend blueprint analysis/testing modules; no separate lint framework.

**What it does.** Measures Python syntax/size, detects mutable globals and graph cycles, and projects pytest output into reports.

**Exact donor/call-site manifest.** These are the implementation sites and tests to move or replace; they also name the existing adapter entry points to retain during adoption.

| File:lines | Count | Ownership |
| --- | ---: | --- |
| src/taskloop/adapters/suiteout.py:1-43 | 43 | application/launcher |
| tests/rules/gate_rules.py:63-128 | 66 | test/support |
| tests/rules/gate_rules.py:150-161 | 12 | test/support |
| tests/rules/gate_rules.py:191-213 | 23 | test/support |
| tests/rules/gate_rules.py:217-254 | 38 | test/support |

**Volume:** 43 application/launcher + 139 test/support = **182** donor lines; **M 159, D 0, S 23**. Fixtures/goldens moving: **0**; app-specific records and their golden outputs remain consumer-owned. 

**Public interface** (at most six lines):

    measure(path) -> Metrics; mutable_globals(ast) -> tuple[Finding, ...]
    ratchet(actual, known, *, ceiling) -> tuple[Finding, ...]
    cycle(edges) -> tuple[str, ...] | None
    pytest_report(output) -> Report
    merge_reports(parts) -> tuple[str, bool]

**Consumers and adoption sites.** Task-loop structural gate and suite failure rendering; shelf blueprint's own repo checks. Lifesim tools/check_client_layers and test runner are prospective consumers after their concrete finding formats are adapted.

**Contracts that make it ownable:**

- Move measurement/ratchet/cycle/mutable-global mechanics and supply package-local AST snippets instead of task-loop paths.
- Docstrings/comments/decorators/nested definitions and same-stamp parsing obey current measurement contracts.
- Ratchets reject growth and require removal of fixed entries without embedding task-loop cap values.
- Graph failure returns a usable cycle; preserve deterministic rendering at the app adapter.
- Pytest warning sections, failed IDs, empty summaries and multi-part exit handling reproduce current reports.

**Production risk.** A wrong measurement or report can make release gates pass or hide failures. All numeric caps, forbidden-layer choices, regex placement rules, ratchet data and release acceptance stay local.

**Releasable migration.** 1. Publish parameterized metrics/reporting and migrate app-independent tests. 2. Adopt reporting first and compare full failure fixtures. 3. Replace the hand-written cycle DFS with graphlib.TopologicalSorter.prepare/CycleError, preserving app rendering. 4. Adopt measurement under unchanged gate thresholds.

**Cost and replacement fit.** Medium development-only change. Of 182 gross lines, 23 cycle-walker lines are replaced by stdlib graphlib; replacement/error-adapter lines remain a cost.

## Third-party decisions: extraction is not blocked on a library experiment

### U01 — ❓ untested: backend substitution tender

**Shelf first:** the accepted owners above are the interfaces. Extract current behavior first; a library may subsequently win those contracts. Local dependency declarations do not prove behavior parity, and the no-network/no-runtime constraint prevents verifying new third-party versions. The table records concrete replacement calls and their limits rather than recommending speculative dependencies.

| Backend under trial | Exact donor sites already counted | Call/interface under trial | Missing fit / decisive test | Extra approved lines |
| --- | --- | --- | --- | ---: |
| msgspec.json.schema / msgspec.convert | A01 schema.py:19-107; delegate codec.py:1-229 | Codec.schema/load/dump | Root-only v, strict-output shape, ABSENT, sorted sets, error paths and delegate int-preserving floats; compare both wire dialects and all app answer goldens | 0 |
| python-ulid | A09 ids.py:31-84 | SortableId.new/parse | Exact entropy/timestamp bytes, uppercase-only validation and no monotonic default; compare deterministic vectors and old run paths | 0 |
| filelock | A05 locks.py:66-92 | ProcessLock.acquire | Non-reentrant same-PID threads, holder hints, cancellation and no breaking a held kernel lock; real killed-holder and cancellation tests decide | 0 |
| psutil | A04 procs.py:90-128; A18 suite.py:51-85 | RecordedProcess / process_table / memory probe | PID birth identity, escaped process groups, macOS/Linux permissions and cgroup headroom; real recycled-PID and container contracts decide | 0 |
| tenacity | A20 retry.py:41-55; pauses.py:86-88; checks/retry.py:10-18 | RetrySchedule / capped_jitter | Does not persist Park or decide reroute/ask/fault; compare indexed rests, budget clipping and cap-before-jitter | 0 |
| platformdirs / pydantic-settings | A07 ident.py:14-21 and env.py:33-62; config.py:1-411 remains domain schema | Directory resolver / merge_mapping | Native macOS paths and source precedence can move live state; pydantic coercion/unknown-key behavior differs; root and invalid-config holdouts decide | 0 |
| cachetools / diskcache | A10 cache.py:1-72 | FileCache / TtlCache | Per-request TTL, peek timestamps, mtime/size validation, missing eviction and concurrency differ; threaded cache contract decides; disk persistence is not required | 0 |
| Starlette / FastAPI | A10 assets.py:1-36, http.py:55-63, bind.py:96-108 | StaticFiles / send_response / bind_all | Dotfile/deny policy, partial-bind rollback, synchronous lifecycle and body/error semantics are not supplied by a naive route rewrite | 0 |
| bashlex / tree-sitter-bash | A13 matchers.py:26-37,73-135 and shell.py:90-94 | analyze(command) | shlex is words, not a shell AST; full parsers may accept syntax the old guard rejects; malformed/adversarial fixtures and hook interpreter cost decide | 0 |
| markdown-it + DOMPurify; rich/humanize | A12 format.js:9-84 and A08 time/spec.py:1-64 | md/esc and format_wait | Expanded markup and changed rounding/width/ANSI are behavior changes; snapshot escaping, exact text and offline delivery | 0 |
| orjson / structlog / logging handlers | A01 wire dumps, A03 applog.py:1-91 | Codec.dump / AppendPool.append | Encoding/error/ordering changes; structured logging does not provide fork-safe bounded descriptor ownership; byte/descriptor contracts decide | 0 |
| watchfiles | A10 FileCache and A06 filesystem-vouched Git memo | cache invalidation | Notifications are not proof of complete invalidation on every filesystem; overflow/rename/missed-event recovery must retain polling correctness | 0 |

**Consumers:** exactly the relevant A-candidate consumers; no additional consumer multiplier. **Candidate volume:** overlapping trial ranges only, **0 additional M/D/S**. **Risk:** each trial can change the running factory behavior named in its parent brief. **Migration:** publish extracted behavior first; run the stated backend tender against pinned old/new implementations; adopt only passing backends in separate app releases. Every new runtime wheel incurs the launcher/hook costs stated above.

**Three common backend contract requirements:**

- Identical accepted/rejected input sets and externally consumed error/result shapes.
- Identical persisted bytes or an explicitly approved format-version change with old-version holdouts.
- Same timeout, cancellation, unknown-state and safety behavior under real failure injection.

### U02 — ❓ untested: larger engine test-helper split

**Shelf first:** stream_proc.testing (A17), git-porcelain.testing and blueprint testing helpers are the intended owners; no new general test-util package. Candidate paths are tests/support/engine_case.py:77-132 (56), :227-233 (7), :277-293 (17), :693-700 (8): **88 test/support lines**, outside accepted totals. These include process liveness, shell/argument helpers, thread-local sleep control, template-repository copying and test-cell expansion.

**What it does / interface:** supplies portable test setup operations while the app keeps EngineTest, delegate scripts and worker fixtures.

    testing.process_gone(pid); testing.without_shims(fn)
    testing.no_sleep_on_current_thread()
    testing.clone_template(template, destination)
    testing.expand_cells(owner, cell, cases)

**Consumers:** task-loop today; shelf package suites and delegate/lifesim tests are prospective. **Contracts to decide:**

- Moving helpers imports no taskloop or app test module.
- Repository templates retain isolated remotes/indexes under concurrent tests.
- Thread-local sleep substitution never spins unrelated threads or leaks patches.
- Test expansion preserves distinct collected IDs and failure reporting.

**Volume:** 0 approved; 88 pending. Some ranges also contain engine-specific skip rules, so **88 is a gross spike envelope, not a promised movable count**. **Risk:** false liveness and shared test repositories can mask real factory races. **Migration:** separate neutral helpers and consumer data, prove the four scenarios, release under the relevant existing package tags, then count the exact removable ranges. A large helper file is not grounds to refuse the generic parts.

### U03 — ❓ untested: browser-check mechanics under the scenario catalog

**Shelf first:** static-page-check already provides offline asset checks (_shelf/packages/static-page-check/src/static_page_check/__init__.py); it does not drive an iframe/browser. No existing shelf browser driver is evidenced. The donor is dev/dash_check.html:1-582 (**582-line file**), with generic iframe/read-only-fetch mechanics visible at :15-40; scenario predicates remain dashboard policy.

**What it does / proposed interface:**

    BrowserProbe(page, *, viewport, theme, read_only=True)
    probe.load(url); probe.inspect(callback); probe.findings()

**Consumers:** task-loop dev checks now; shelf static-page consumers/lifesim browser tooling are potential. **Contracts to decide:**

- A read-only probe refuses every mutating fetch before it reaches a live server.
- Repeated hash-only routes still produce the intended fresh-document lifecycle.
- Viewport/theme/load completion remain deterministic in headless execution.

**Volume:** 0 approved; the 582-line file is an envelope and overlaps the remaining-files table, not an extra removal promise. **Risk:** a browser check could write live bead state. **Migration:** isolate mechanics from scenario names/DOM expectations, compare old/new browser checks, publish a browser testing API or a Playwright adapter only after offline distribution is proven. A Playwright rewrite may reduce custom mechanics but cannot delete the scenarios.

### U04 — ❓ untested: eliminate checked-in shelf delivery copies

**Shelf first:** these are already shelf packages, not newly discovered reusable code: atomic-io, jsonl-log, process-lock, child-env, stream-proc, git-porcelain, static-page-check, app-dirs and timefmt. Their public APIs were checked in the accepted briefs. **Missing:** a proven offline, tagged distribution path for every launcher and the plain hook.

**What it does / proposed delivery interface:**

    load_pinned_package(name, *, tag, content_hash)
    verify_offline_install(manifest) -> list[Problem]

**Consumers:** both apps' launchers; package-source location changes without introducing a new runtime capability. Exact Python files and wc counts:

| File:lines | Lines |
| --- | ---: |
| _delegate/skills/delegate/_vendor/timefmt/__init__.py:1-97 | 97 |
| _delegate/skills/delegate/_vendor/app_dirs/__init__.py:1-90 | 90 |
| _delegate/skills/delegate/_vendor/atomic_io/__init__.py:1-91 | 91 |
| _delegate/skills/delegate/_vendor/jsonl_log/cursor.py:1-143 | 143 |
| _delegate/skills/delegate/_vendor/jsonl_log/__init__.py:1-228 | 228 |
| _delegate/skills/delegate/_vendor/jsonl_log/_append.py:1-26 | 26 |
| _delegate/skills/delegate/_vendor/jsonl_log/_retention.py:1-28 | 28 |
| _delegate/skills/delegate/_vendor/child_env/__init__.py:1-93 | 93 |
| skills/task-loop/_vendor/process_lock/__init__.py:1-237 | 237 |
| skills/task-loop/_vendor/static_page_check/__init__.py:1-136 | 136 |
| _delegate/skills/delegate/_vendor/stream_proc/tree.py:1-106 | 106 |
| _delegate/skills/delegate/_vendor/stream_proc/procmac.py:1-234 | 234 |
| _delegate/skills/delegate/_vendor/stream_proc/runner.py:1-180 | 180 |
| _delegate/skills/delegate/_vendor/stream_proc/procfs.py:1-107 | 107 |
| _delegate/skills/delegate/_vendor/stream_proc/__init__.py:1-32 | 32 |
| _delegate/skills/delegate/_vendor/stream_proc/proctable.py:1-76 | 76 |
| _delegate/skills/delegate/_vendor/stream_proc/hold.py:1-64 | 64 |
| skills/task-loop/_vendor/atomic_io/__init__.py:1-91 | 91 |
| _delegate/skills/delegate/_vendor/process_lock/__init__.py:1-237 | 237 |
| skills/task-loop/_vendor/child_env/__init__.py:1-93 | 93 |
| skills/task-loop/_vendor/git_porcelain/errors.py:1-42 | 42 |
| skills/task-loop/_vendor/git_porcelain/real_read.py:1-301 | 301 |
| skills/task-loop/_vendor/git_porcelain/fake_ignore.py:1-74 | 74 |
| skills/task-loop/_vendor/git_porcelain/fake_ops.py:1-152 | 152 |
| skills/task-loop/_vendor/git_porcelain/testing.py:1-99 | 99 |
| skills/task-loop/_vendor/git_porcelain/fake_write.py:1-216 | 216 |
| skills/task-loop/_vendor/git_porcelain/lfs.py:1-94 | 94 |
| skills/task-loop/_vendor/git_porcelain/real_done.py:1-44 | 44 |
| skills/task-loop/_vendor/git_porcelain/real_write.py:1-381 | 381 |
| skills/task-loop/_vendor/git_porcelain/__init__.py:1-163 | 163 |
| skills/task-loop/_vendor/git_porcelain/fake_merge.py:1-103 | 103 |
| skills/task-loop/_vendor/git_porcelain/fake_flow.py:1-174 | 174 |
| skills/task-loop/_vendor/git_porcelain/real.py:1-241 | 241 |
| skills/task-loop/_vendor/git_porcelain/porcelain.py:1-263 | 263 |
| skills/task-loop/_vendor/git_porcelain/ignore_rules.py:1-43 | 43 |
| skills/task-loop/_vendor/git_porcelain/api.py:1-448 | 448 |
| skills/task-loop/_vendor/git_porcelain/real_env.py:1-83 | 83 |
| skills/task-loop/_vendor/git_porcelain/fake.py:1-315 | 315 |
| skills/task-loop/_vendor/git_porcelain/fake_diff.py:1-170 | 170 |
| skills/task-loop/_vendor/git_porcelain/history.py:1-369 | 369 |
| skills/task-loop/_vendor/git_porcelain/fake_read.py:1-221 | 221 |
| skills/task-loop/_vendor/git_porcelain/fake_store.py:1-231 | 231 |
| skills/task-loop/_vendor/git_porcelain/real_parse.py:1-149 | 149 |
| skills/task-loop/_vendor/git_porcelain/real_cache.py:1-135 | 135 |
| skills/task-loop/_vendor/stream_proc/procfs.py:1-107 | 107 |
| skills/task-loop/_vendor/stream_proc/__init__.py:1-32 | 32 |
| skills/task-loop/_vendor/stream_proc/proctable.py:1-76 | 76 |
| skills/task-loop/_vendor/stream_proc/hold.py:1-69 | 69 |
| skills/task-loop/_vendor/stream_proc/procmac.py:1-234 | 234 |
| skills/task-loop/_vendor/stream_proc/runner.py:1-180 | 180 |
| skills/task-loop/_vendor/stream_proc/tree.py:1-106 | 106 |
| skills/task-loop/_vendor/jsonl_log/cursor.py:1-143 | 143 |
| skills/task-loop/_vendor/jsonl_log/__init__.py:1-228 | 228 |
| skills/task-loop/_vendor/jsonl_log/_append.py:1-26 | 26 |
| skills/task-loop/_vendor/jsonl_log/_retention.py:1-28 | 28 |

**Contract requirements:**

- A clean offline install executes tl, delegate and the plain hook with the exact tagged artifact hashes.
- Runtime dependencies remain consistent between PEP 723 and project declarations; imports cannot be shadowed by another plugin's vendor root.
- The plain hook retains its supported interpreter and dependency-free import graph.
- Missing artifact fails explicitly; rollback restores the previous entire package set.

**Volume:** **8,129 duplicate delivery lines pending, 0 approved**. They are counted in the denominator but not in accepted M/D/S. **Risk:** a factory restart without network fails to import its engine. **Migration:** implement and test distribution while retaining copies; release both launchers with provenance checks; remove copies only after clean offline-install and rollback proofs. Deleting copies is packaging reduction, not another extraction of their shelf implementations.

## Refused domain moves

### R01 — ❌ refuse: factory policy and its consumer evidence

**Shelf first:** no existing generic package should acquire these rules. The accepted substrate packages expose codecs, documents, processes, syntax and Git outcomes. Their apps continue to interpret those outcomes. This refusal applies to the listed residual files/ranges, not to generic mechanisms already selected above.

**What it does:** defines the factory's authority, worker contract, gate/land/close eligibility, routing and owner interaction. **Target:** retain in task-loop/delegate. **Public interface retained:**

    Beads / RepoProfile / ConfigDir / AskStore
    RetryPlan policy rows; PauseRule reason table
    worker guard decisions; delegate worker-run contract
    dashboard projections of app state

| File or residual range | Residual lines | Named rule preventing extraction |
| --- | ---: | --- |
| src/taskloop/adapters/bd.py:1-276 | 276 | bd CLI normalization, claim/close fencing, actor propagation and Dolt rejection interpretation are the Beads protocol, not generic JSON subprocess policy |
| src/taskloop/adapters/bdcreate.py:1-36 | 36 | follow-up descriptions, required lint sections and the one retry after bd lint refusal |
| src/taskloop/adapters/bdsafe.py:1-22 | 22 | which failed Beads reads/writes may be treated as missing or an attempted operation |
| packages/kernel/src/tlkernel/config.py:1-411 | 411 | stage/gate registration, cross-lane read restrictions, resources, worker budgets, retired profile keys and slot preparation |
| packages/kernel/src/tlkernel/paths.py:1-288 | 288 | the engine's run/slot/lock/ask/checkpoint directory layout; generic root resolution is A07 |
| packages/kernel/src/tlkernel/stores.py:1-559 excluding accepted ranges above | 441 | AskStore answer/amend/consume/park lifecycle and concrete run/status/repo store families; A02/A03 move the document/log mechanisms |
| src/taskloop/domain/lanes/retry.py:1-58 excluding accepted ranges above | 43 | which worker failure kinds retry and whether exhaustion asks, faults or reroutes; A20 moves the evaluator |
| src/taskloop/domain/lanes/pauses.py:1-103 excluding accepted ranges above | 100 | unknown reasons require an owner; durable Park attempts, hashes and retry-at decisions; A20 moves only delay arithmetic |
| src/taskloop/domain/checks/retry.py:1-27 excluding accepted ranges above | 18 | deterministic failures do not retry; imports and lock failures receive different eligibility |
| _delegate/src/delegate/domain/policy/shell.py:1-109 excluding accepted ranges above | 104 | git belongs to the coordinator, read commands are allowlisted, engine-only recipes and process-kill permissions stay worker policy |
| _delegate/src/delegate/domain/policy/matchers.py:1-137 excluding accepted ranges above | 64 | which paths count as secret accesses, and which exclusion/heredoc cases the worker guard tolerates; A13 moves syntax only |
| _delegate/src/delegate/app/cockpit.py:1-239 | 239 | lane readiness/resting/spend/login state, fallback explanation and next-worker routing projection |
| _delegate/skills/delegate/contract.json:1-1749 | 1749 | worker-run v3 stop scopes, permanence, reason/fact grammar and response flags |

**Volume:** 3,791 explicitly adjudicated residual lines retained; **0 moved/deleted/replaced**. This is not a claim that every other residual line is policy.

**Consumers:** their respective apps and the app's end-to-end tests; shelf must never import them. **Contract tests retained:**

- A bead with an unlanded task branch cannot silently close; ownership fencing and Dolt failure behavior stay unchanged.
- Unknown worker stop reasons require an owner; retry counts and lane reroutes preserve recorded decisions.
- Read-only/engine-only worker guard cases and worker-run v3 response goldens stay identical.
- Gate registry/resource/cross-lane validation and owner answer consumption preserve their app-specific rules.

**Production risk:** transferring these rules into an ostensibly generic package makes a package update change factory policy across consumers. **Migration order:** do not move the rules; inject them into the accepted generic mechanisms, then run the app holdouts for every pin bump. There is no source/test relocation for this refusal.

## Exactly what remains below the 50% target

After the accepted gross removals, **135,833 lines remain in the apps**. Their measured distribution is below; compatibility code/new consumer tests would make the actual post-migration number higher.

| Root | Remaining old lines | Why they remain in this inventory |
| --- | ---: | --- |
| src | 44,390 | Policy/state/view records, app orchestration and mechanisms not yet given a counted split |
| tests | 70,956 | Consumer scenario assertions/fixtures/goldens, app fakes, and unproven helper splits |
| skills | 7,411 | Worker/owner operating contract, CLI command policy and already-shared vendor delivery |
| dev | 2,051 | App release/browser scenarios and helper splits not yet proven |
| _delegate/src | 6,865 | Routing/health/worker policy and remaining uncounted mechanisms |
| _delegate/skills | 4,160 | Worker contract/routing data and already-shared vendor delivery |

These are residual categories, **not blanket refusals**. Accepted range manifests above plus their complements in the measured inventory define the residual set. U02/U03 are explicit next investigations. Meeting 50% would require an additional 64,017 measured lines with similarly concrete generic boundaries or deliberate deletion of app behavior; this audit has not demonstrated those boundaries.

### The 25 largest remaining files, individually judged

Sizes are remaining old lines after accepted ranges, sorted descending. Original file extents are cited so a reader can locate evidence even where a split reduced the residual.

| Rank | File:original extent | Remaining | Verdict and exact reason / deciding test |
| ---: | --- | ---: | --- |
| 1 | tests/dash/golden/closes.json:1-2927 | 2,927 | ❌ refuse — bead-close view golden locks budget/ask/phase transitions; retain the app's expected close projection |
| 2 | tests/fixtures/dash/snapshot.json:1-2341 | 2,341 | ❌ refuse — dashboard snapshot schema and loop/resource/lane projections are app wire policy |
| 3 | tests/contracts/golden/records.json:1-1826 | 1,826 | ❌ refuse — golden records name RunTrace, outcomes, asks and app versions; move generic codec tests, not these contracts |
| 4 | _delegate/skills/delegate/contract.json:1-1749 | 1,749 | ❌ refuse — delegate worker-run v3 protocol, stop scopes and permanence are the worker contract |
| 5 | tests/fixtures/dash/mock-8b.json:1-1045 | 1,045 | ❌ refuse — authored mock bead columns, look/park states and stage history encode dashboard semantics |
| 6 | tests/loop/real/test_loop.py:1-915 | 915 | ❌ refuse — live loop claim/slot/heartbeat/recovery behavior; assertions remain consumer integration tests |
| 7 | tests/run/test_engine_run.py:1-828 | 828 | ❌ refuse — engine worker/run lifecycle and land/close outcomes; neutral process/Git fakes move underneath it |
| 8 | tests/run/test_stages.py:1-817 | 817 | ❌ refuse — plan/write/review/verify stage sequencing and transitions are the run state machine |
| 9 | tests/support/narrow_hosts.py:1-777 | 777 | ❌ refuse — typed FakeWaitsHost/OutboundHost and peers enumerate app host responsibilities; process/Git mechanisms move from their own owners |
| 10 | tests/support/engine_case.py:1-765 | 765 | ❓ untested — U02 explicitly tests an 88-line helper envelope; EngineTest and worker fixtures remain app policy |
| 11 | tests/land/test_engine_land_1.py:1-752 | 752 | ❌ refuse — landing/rebase/branch and gate expectations are factory land semantics, not a Git contract |
| 12 | tests/run/test_stages_visual.py:1-717 | 717 | ❌ refuse — visual shot ownership, other-family judging, render retries, resume/replan and claims |
| 13 | tests/land/test_stages_land.py:1-706 | 706 | ❌ refuse — stage landing, follow-up bd lint retries, claim takeover and engine-only flags |
| 14 | skills/task-loop/SKILL.md:1-674 | 674 | ❌ refuse — skill's coordinator/worker/slot/close operating rules are product behavior, not a library |
| 15 | tests/run/test_engine_units.py:1-652 | 652 | ❌ refuse — engine execution/worker/check and outcome scenarios must remain app holdouts |
| 16 | tests/land/test_race_invariants.py:1-640 | 640 | ❌ refuse — land race invariants define factory delivery authority; generic Git lock tests move separately |
| 17 | tests/contracts/samples.py:1-600 | 600 | ❌ refuse — sample instances enumerate app log/event/outcome kinds; replace package tests with neutral probes |
| 18 | tests/rules/gate_rules.py:1-726 | 587 | ❓ untested — 139 portable analysis lines are already A21; remaining 587 include app signal/shell/probe/layer rules and vendor tests; an AST-rule/config split needs identical planted-rule diagnostics before counting more |
| 19 | dev/dash_check.html:1-582 | 582 | ❓ untested — U03 separates iframe/probe mechanics from dashboard DOM/scenario requirements; browser parity decides, 0 extra savings booked |
| 20 | tests/e2e/test_release.py:1-570 | 570 | ❌ refuse — complete release/install/manifest/marketplace behavior is a product flow; package contracts do not replace this holdout |
| 21 | packages/kernel/src/tlkernel/dash.py:1-562 | 562 | ❌ refuse — bead columns, markers, owner causes, phase mapping and app POST/view records are dashboard protocol |
| 22 | tests/land/test_stack.py:1-549 | 549 | ❌ refuse — land-stack PR ordering, gates and delivery invariants remain factory policy |
| 23 | tests/plan/test_engine_plan.py:1-546 | 546 | ❌ refuse — planner judgments, selected checks and stage acceptance define planning behavior |
| 24 | tests/support/dash_fixtures.py:1-527 | 527 | ❌ refuse — builder maps mock bead/stage/cause data into app contract records, so fixtures must remain with that contract |
| 25 | tests/fixtures/delegate3/skills/delegate/contract.json:1-525 | 525 | ❌ refuse — embedded old delegate worker contract is compatibility evidence; deleting it needs an explicit supported-version retirement, not library extraction |

No dashboard golden, worker contract JSON, schema answer fixture or replay fixture is claimed as a movable generic test. A package must have its own neutral fixture corpus; the factory keeps holdouts proving that those package capabilities still implement its specific rules.

## Totals

**No implementation lines actually moved during this review.** These are gross, non-overlapping migration allocations.

| Verdict/accounting | Application/launcher | Tests/support | Total | % of 143,632 |
| --- | ---: | ---: | ---: | ---: |
| ✅ selected gross old lines leaving apps | 3,263 | 4,536 | **7,799** | **5.43%** |
| Of those: M transferred mechanisms/contracts | 3,263 | 2,656 | **5,919** | **4.12%** |
| Of those: D duplicate gitsim replaced by shelf fake | 0 | 1,857 | **1,857** | **1.29%** |
| Of those: S replaced by stdlib graphlib | 0 | 23 | **23** | **0.02%** |
| ✅ accepted fixture/golden moves | 0 | 0 | **0** | **0%** |
| ❌ R01 explicitly retained residuals | — | — | **3,791 retained; 0 savings** | 0% savings |
| ❓ U02 generic helper envelope | 0 | 88 | **88 pending, not approved** | 0.06% envelope |
| ❓ U03 browser harness file envelope | 582 | 0 | **582 pending, not approved** | 0.41% envelope |
| ❓ U04 existing shelf vendor distribution copies | 8,129 | 0 | **8,129 pending, not approved** | 5.66% envelope |
| ❓ U01 backend alternatives | — | — | **0 additional; overlapping parent inventory** | 0% additional |

M+D+S = 5,919+1,857+23 = **7,799**. Test/support classifications reflect donor location even when the donor contains library-worthy Python. The 88/582 pending envelopes include app-specific content and must not be added wholesale. Even the fully proven removal of all 8,129 vendor copies would produce only **15,928 gross lines (11.09%)**, still 55,888 short of half. It would be a delivery change, not another discovery of shared functionality.

| Candidate | M | D | S | Gross total |
| --- | ---: | ---: | ---: | ---: |
| A01 | 694 | 0 | 0 | 694 |
| A02 | 196 | 0 | 0 | 196 |
| A03 | 642 | 0 | 0 | 642 |
| A04 | 401 | 0 | 0 | 401 |
| A05 | 177 | 0 | 0 | 177 |
| A06 | 1874 | 1857 | 0 | 3731 |
| A07 | 35 | 0 | 0 | 35 |
| A08 | 103 | 0 | 0 | 103 |
| A09 | 89 | 0 | 0 | 89 |
| A10 | 191 | 0 | 0 | 191 |
| A11 | 20 | 0 | 0 | 20 |
| A12 | 64 | 0 | 0 | 64 |
| A13 | 78 | 0 | 0 | 78 |
| A14 | 507 | 0 | 0 | 507 |
| A15 | 76 | 0 | 0 | 76 |
| A16 | 117 | 0 | 0 | 117 |
| A17 | 361 | 0 | 0 | 361 |
| A18 | 88 | 0 | 0 | 88 |
| A19 | 20 | 0 | 0 | 20 |
| A20 | 27 | 0 | 0 | 27 |
| A21 | 159 | 0 | 23 | 182 |

## Top 10

Rank uses **removable donor lines per unit of operational risk**, then concrete consumer reach and refactor cost. It is not a fabricated numerical probability. Testing-only moves rank early; Git's much larger volume warrants a parallel implementation track only when the coordinator chooses one. Prospective consumers are marked and do not count as established adoption. All pin/tag and parity steps above still apply.

| Rank | Candidate | Lines / evidenced consumers | Cost | Risk | First independently releasable implementation brief |
| ---: | --- | --- | --- | --- | --- |
| 1 | A17 process simulation/guards | 361; task-loop, shelf process contracts; delegate/lifesim prospective | Medium | Low production | Add stream_proc.testing ProcessWorld with injected defaults and move both procsim test modules; publish testing-extra tag before adapting conftest |
| 2 | A03 JSONL/readers/append pool | 642; task-loop, dashboard, delegate | Medium–high | Medium–high | Publish public buffer parser plus max_bytes, move cursor tests, adopt dashboard poll adapter; pool and history compaction follow in separate releases |
| 3 | A06 Git substrate + duplicate fake removal | 3,731; task-loop and delegate, lifesim prospective | High | Critical | Port GitContract + read-failure cases to git-porcelain, extend read/parser/cache outcomes, pin and compare read-only adapter first; delete gitsim last |
| 4 | A01 record/schema backends | 694; task-loop and delegate | High | High | Publish both current codec dialects behind injected Codec with neutral probes; adopt delegate before task-loop; do not change schema backend yet |
| 5 | A14 agent streams/transcripts | 507; task-loop and delegate | High | Medium–high | Move OpenCode session reader plus test_opencode into agent-stream, tag and adopt reads; migrate vendor event parsers one at a time |
| 6 | A21 analysis and suite reporting | 182; task-loop and shelf blueprint | Medium | Low production | Add blueprint's parameterized AST/report projections, adopt failure-report formatting first, then graphlib cycle adapter under unchanged gate constants |
| 7 | A02 typed documents | 196; task-loop, delegate prospective transaction adopter | Medium | Medium | Add typed Document/read outcomes and memory fake to atomic-io, move neutral SealedRead/DocContract, retain JsonStore compatibility export |
| 8 | A04 captured/recorded processes | 401; task-loop and delegate | High | High | Add stream-proc recorded handles/capture and move three process test modules; preserve each app's timeout/exit mapping |
| 9 | A10 static HTTP/files/cache | 191; dashboard, task-loop cache prospective | Medium | Medium | Publish contained StaticFiles plus move asset contract; pin/adopt read serving without changing bind authorization or API routing |
| 10 | A16 installed artifacts/integrity | 117; task-loop, shelf artifact users prospective | Medium | Medium | Add integrity manifests to dir-trust, move generic Manifest methods, pin/adopt verification before changing version discovery or exec teardown |

A05 lock cancellation is an early dependency where a migration needs it, despite its lower volume/risk rank. A19's 20-line cleanup can ship independently; it does not justify delaying the larger extractions. A07/A08/A09/A11/A12/A13/A15/A18/A20 are accepted follow-on scope with exact manifests, not postponed refusals.

## Beads to file

These are implementation briefs to file later, **not issues created during this read-only audit**. One entry per distinct extraction/adoption; multi-owner candidates are split so each package can release independently. Required acceptance is the candidate's contracts plus the unchanged consumer holdouts, with tagged pins and rollback.

- **Extract versioned record and schema backends to any-record (A01)** — Publish both existing wire dialects and move neutral codec/schema contracts; preserve app goldens.
- **Extend atomic-io with typed documents and matching memory stores (A02)** — Introduce four read outcomes and injected codecs; migrate JsonStore/FileDocSet through compatibility exports.
- **Extend jsonl-log with typed bounded readers, compaction and append pools (A03)** — Move cursor/pool/log contracts, preserve byte offsets and add missing APIs before app adoption.
- **Extend stream-proc with capture and recorded handles (A04)** — Move generic process adapters/tests; preserve timeout mappings and actual signal evidence.
- **Add cancellable process-lock acquisition and its memory fake (A05)** — Remove duplicate wait machinery while retaining live-lock exclusion and app holder encoding.
- **Converge Git adapters and tests on git-porcelain (A06)** — Move real/fake contracts, extend missing Git outcomes, then delete the duplicate gitsim after parity.
- **Add installed-plugin directory discovery to app-dirs (A07)** — Preserve delegate precedence and task-loop relative-XDG compatibility without moving state.
- **Promote pure virtualenv removal into child-env (A07)** — Preserve PATH bytes and keep app allowlist/hook policy local.
- **Add JSON mapping layering to settings-base (A07)** — Isolate merge machinery without importing profile schemas or requiring the YAML backend at runtime.
- **Extend due-schedule with existing human-time parsing dialects (A08)** — Pin relative/absolute/weekly boundaries and local-time behavior.
- **Extend timefmt with delegate wait/local presentation dialects (A08)** — Preserve current strings before considering format unification.
- **Extract opaque sortable IDs with stable wire bytes (A09)** — Move generator/parser and neutral deterministic ID tests; retain BeadId and app path keys.
- **Publish bounded local HTTP static serving and bind lifecycle (A10)** — Compose any-file, move asset tests, and keep address/API authorization local.
- **Extract file-signature and per-call TTL caches (A10)** — Preserve LRU, missing-file and concurrent-loader behavior; no persistence change.
- **Add lazy context-neutral CLI invocation to verb-cli (A11)** — Replace tl wrappers while preserving deferred imports and app exit semantics.
- **Publish browser time/count exports from timefmt (A12)** — Preserve rounding and ship tagged offline ES modules.
- **Publish the escaped browser Markdown subset from any-markdown (A12)** — Preserve exact safe markup; keep app state markers/project labels local.
- **Extract syntax-only shell analysis to shell-words (A13)** — Preserve the current heuristic grammar and keep worker authorization rules in delegate.
- **Extract neutral vendor streams and session readers to agent-stream (A14)** — Start with read-only OpenCode tests, then migrate vendor parsers behind HarnessEvent adapters.
- **Move usage normalization/folds into agent-stream (A15)** — Pin cache-token, unknown-cost and reset-time facts without transferring lane thresholds or authentication policy.
- **Add parameterized installed-artifact catalogs to app-dirs (A16)** — Preserve marker/scope/version precedence; keep pin and rollback policy local.
- **Add per-file integrity manifests to dir-trust (A16)** — Move generic Manifest contracts and preserve doctor compatibility.
- **Add close-before-exec lifecycle to stream-proc (A16)** — Compose tagged append-pool cleanup and preserve exact argv/environment handover.
- **Promote process simulation and guard mechanics to stream_proc.testing (A17)** — Move process guard tests and inject task-loop-specific defaults/budgets.
- **Add container-aware memory probes to any-proc (A18)** — Move cgroup tests and leave worker-budget/refusal policy in the app.
- **Finish atomic-io adoption at remaining temporary-write sites (A19)** — Preserve bytes/modes and answer-before-checkpoint order.
- **Extract pure rest-table and capped-jitter evaluation (A20)** — Preserve retry indexing and keep pause reasons/actions app-owned.
- **Extend blueprint with parameterized analysis/reporting helpers (A21)** — Move portable AST mechanics, use graphlib for cycles and preserve all app gate thresholds.
