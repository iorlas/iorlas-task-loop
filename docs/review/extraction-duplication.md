# Extraction review — C: duplication, second pass

**Extract the remaining substrate, including the refactors needed to expose it. This review identifies 7,069 gross lines to retire from task-loop and delegate: 5,032 moved into shelf, 2,034 deleted as duplicate implementations, and 3 replaced at the call site by Python formatting.** That is **4.92% of the requested 143,632-line denominator**, not 50%. Removing the already extracted vendored distributions could retire another 8,129 lines, but that is an **untested distribution change**, not another extraction. Even both together reach only **10.58%**.

The previous review's 654-line recommendation was too narrow. In particular, the parallel git simulator, generic contract tests, provider readers, architecture gate, and browser harness must be counted and split. A difficult compatibility refactor is still an extraction. Conversely, moving the worker contract, bead lifecycle or land decisions into a package would merely relocate the applications.

## Measurement and meaning of the numbers

Inspected the shelf agreement, context, constitution and catalog first, then the existing extraction reviews and the cited implementations. All paths below are relative to this checkout. Ranges are inclusive. Counts are physical lines, including comments and blanks, obtained with `wc -l`; selected spans were measured with `sed -n 'A,Bp' FILE | wc -l`. These are **donor ranges to retire**, not predictions of the final diff: replacement imports, callback adapters and genericized fixtures will consume some lines. No claim of net repository shrinkage includes those unknown replacement costs.

The denominator command was run separately on each existing root:

```sh
rg --files ROOT -g '*.py' -g '*.js' -g '*.html' -g '*.json' -g '*.md' | xargs wc -l
```

| Root | Lines |
| --- | ---: |
| `src` — includes `src/taskloop` and `src/taskloop_dash` | 46,727 |
| `tests` — includes fixtures and goldens with the requested extensions | 75,492 |
| `skills` — includes the current shelf vendor distribution | 7,431 |
| `dev` | 2,051 |
| Task-loop subtotal | **131,701** |
| `_delegate/src` | 7,771 |
| `_delegate/skills` | 4,160 |
| Delegate subtotal | **11,931** |
| **Task-loop + delegate denominator** | **143,632** |

There is no `_delegate/tests` or `_delegate/dev` in this supplied tree. Delegate fixtures embedded in task-loop's tests are included there, once. The requested extension filter excludes `.jsonl`, `.css`, YAML, shell scripts and TOML; it includes Markdown under the named roots, not documentation elsewhere. `_lifesim_tools/*.py` is **2,532 lines**, measured separately; its tests and scripts supply reuse evidence but earn **no credit against the two-application target**. Shelf implementation and tests also earn no credit. Hidden ignored files were not inventoried by this `rg --files` command.

`M` means donor lines move into a package, `D` means a parallel implementation disappears in favor of an existing/shared implementation, and `R` means direct stdlib replacement. Test-support machinery counts as tests, not runtime source. All candidate ranges in the accounting are disjoint. Where two donors are retained initially as compatibility implementations inside one package, both are M; eventual consolidation earns no second credit.

✅ is an extraction recommendation requiring the stated contracts, **not a claim that tests have run**. ❓ is a specific unresolved experiment, with zero approved retirement. ❌ names an application rule that must stay. Proposed APIs are marked as such; they are not claims about existing exports.

## Release conditions shared by every extraction

1. First introduce a seam in the app with its current implementation. Capture both donors' behavior, including different errors, serialization bytes, timeout boundaries, permissions and ordering. Differences are compatibility defects until a test establishes a deliberate dialect.
2. Publish shelf contracts and implementation under a new immutable package tag. Shelf imports no consumer app. Generic fixtures must define synthetic records and policies; app records and production examples remain consumer holdouts.
3. Pin the tag and resolved revision independently in each application. Current vendoring already records `shelf_tag`, `shelf_commit` and `tree_hash` in `dev/vendor.json:1`; `dev/vendor.py:12-25` describes tag-based copying and eventual direct dependencies. A checkout of shelf is not a production dependency. Do not hand-edit vendor files.
4. Release one adapter and one consumer at a time. Differential comparisons are read-only or test-only; never run two real commits, state mutations or signals to compare implementations. Preserve mixed-version lock paths, state bytes and identifiers.
5. Retain application holdouts for gate authorization, land refusals, close eligibility, worker answer interpretation and owner pin precedence. A changed outcome is a separate behavior release, not an extraction side effect. Rollback restores the previous dependency pin and compatible adapter through the owner's release process.

No tests or applications were executed for this documentation review. No git, tracker, network or credential operations were performed. The read sandbox initially failed to create a namespace; the exact escalated read succeeded. The analysis used source reads only; the sole intended repository mutation is this document.

## C01 — ✅ Extract git substrate and delete the second simulator

**Shelf first:** `_shelf/packages/git-porcelain/src/git_porcelain/__init__.py:1` already exposes `RealRepo`, `RealWorktree`, `run_git`, `status`, `head`, `fetch`, `push`, `show_at` and typed failures. `testing.py:1` exposes `FakeRepo`, `FakeWorktree`, `FakeRemote`, `hermetic_env` and `git`. `real_env.py:46-69` already owns checkout discovery and pinning. Evolve **git-porcelain**; do not create another git package. Missing contracts include the donors' exact absence/error distinctions, legacy operations, argv-level simulation compatibility, and filesystem-backed memo invalidation.

**Copies / exact retirement:**

| Donor | Lines | Disposition |
| --- | ---: | --- |
| `src/taskloop/adapters/git.py:1-325` | 325 | M |
| `src/taskloop/adapters/git_base.py:1-150` | 150 | M |
| `src/taskloop/adapters/git_ops.py:1-96` | 96 | M |
| `src/taskloop/adapters/gitmemo.py:1-100` | 100 | M |
| `src/taskloop/adapters/gitrepo.py:1-91` | 91 | M |
| `_delegate/src/delegate/adapters/git.py:8-10,13-17,20-24` | 13 | D |
| `tests/ports/git_contract.py:1-473` | 473 | M |
| `tests/ports/git_contract_land.py:1-184` | 184 | M |
| `tests/adapters/real/test_git_memo.py:1-162` | 162 | M |
| `tests/support/gitq.py:1-23` | 23 | D |
| `tests/support/gitsim/__init__.py:1-200`, `ctx.py:1-76`, `diffs.py:1-142`, `ignore.py:1-74` | 492 | D |
| Same directory: `model.py:1-276`, `read.py:1-226`, `rebase.py:1-119`, `refs.py:1-113` | 734 | D |
| Same directory: `remote.py:1-114`, `status.py:1-70`, `trees.py:1-102`, `write.py:1-245` | 531 | D |

These implementations run git, parse its answers, locate/pin checkouts and simulate repository behavior. Total **3,374 = M 1,581 + D 1,793**, including **2,599 test/support lines**. `_lifesim_tools/changed.py:65-66` is another subprocess wrapper; its two lines are outside these totals.

**Differences / best base:** shelf's typed real/fake protocols are the destination; task-loop's contract suite is the compatibility authority for its extra operations. Delegate discovers the current worktree top level; task-loop's `repo_root` identifies the shared repository. Those are different operations, not interchangeable names. Task-loop distinguishes unreadable repositories from missing revisions and validates NUL records. Its simulator intercepts subprocess argv, whereas shelf's fake is a port implementation. Replace consumers of the simulator with injected ports; preserve a temporary argv bridge until the last caller moves. Memoized config/ref answers must retain conservative invalidation and never turn a failure into a cached absence.

**Proposed consolidated surface:**

```python
Repo.open(path, *, env, pinned=True) -> Repo
Repo.identity(); Repo.worktrees(); Repo.worktree(path)
Worktree.snapshot(base); Worktree.diff(a, b); Worktree.record(...)
Repo.observe(operation, *args) -> typed_result
FakeRepo; FakeRemote; testing.contract_suite(factory)
```

**Consumers:** task-loop, delegate and lifesim git helper scripts; shelf already has its own real/fake consumers. A dashboard is part of task-loop, not another application multiplier.

**Contracts that move with the implementation:**

- Run the two port suites against both shelf real and fake backends after replacing app DTOs with package DTOs; preserve literal pathspecs, rename records and CAS deletion.
- Distinguish empty, detached, missing ref, inaccessible repository and malformed output; never authorize an action from an unknown read.
- Preserve pinned versus ambient checkout identity, packed-ref and config changes, reftable refusal and memo invalidation.
- Prove the fake refuses unsupported operations and cannot reach real subprocesses; keep real/fake parity for conflicts, remotes and worktrees.

**Risk / cost:** critical / high: wrong checkout, stale tree evidence or changed failure interpretation can invalidate land. The package performs operations; **the app retains whether a tree may land, which checks count, retry policy and whether a bead may close**.

**Releasable migration:** publish discovery/error compatibility → replace delegate reads → replace task-loop read methods and memoization → move port tests → migrate simulator users to injected shelf fakes → switch writes one operation family at a time → remove `gitsim` and `gitq`. Land/race integration suites remain in task-loop throughout.

## C02 — ✅ Extract versioned record machinery; retain two backends until convergence is proved

**Shelf first:** no catalog package supplies strict versioned Python records. `lean-wire` is a TSV codec and `dom-schema` is HTML extraction. Create **any-record**, using existing **msgspec** for its msgspec backend and the existing dataclass codec for compatibility. Stdlib `dataclasses.asdict` alone cannot replace validation.

**Copies:** `src/taskloop/contracts/wire.py:1-101` (**101**) and `_delegate/src/delegate/contracts/codec.py:1-229` (**229**). Both implement typed records, tags, aliases, scalar hooks, root versions and strict decoding. **M 330; D/R 0.** No app record declarations or goldens are credited.

**Differences / best base:** task-loop's msgspec backend hides more implementation; delegate's dataclass backend supplies frozen and mutable decorators, `ABSENT`, sorted set encoding and integer-preserving float decoding (`codec.py:172-195`). A forced msgspec rewrite is unnecessary for extraction. Package both existing backends first, then tender convergence against differential tests. App `Refused` presentation stays local.

```python
record; mutable; Rec; Tagged; ABSENT
load(type_or_union, data) -> object
dump(record) -> dict
replace(record, **changes) -> object
StaleRecord(found, want); CodecError
```

**Consumers:** task-loop and delegate; no demonstrated lifesim typed-record demand.

**Contracts:**

- Both backends reject unknown keys, bool-as-int, missing required values and foreign root versions.
- Pin absent versus null, mutable records, aliases, nested tags, sorted sets and scalar hooks.
- Pin integer-versus-float round trips and diagnostic paths separately where donors differ.
- Keep `tests/contracts/test_wire.py:55-198`, its app samples and `tests/contracts/golden/records.json` as consumer holdouts; add synthetic backend contracts rather than moving factory types.

**Risk / cost:** high / high: unreadable state or rejected worker replies. **Order:** extract without changing backend → tag → adopt delegate → adopt task-loop → remove app implementations → consider backend unification in a later release. Tests are required, not a reason to leave the substrate embedded.

## C03 — ✅ Extract schema generation, strict transforms and their generic test machinery

**Shelf first:** no Python-record schema package exists in the catalog. Create **record-schema**, composing C02; use msgspec's schema support only after its output passes the donor fixtures. Do not confuse `dom-schema` with JSON Schema generation.

**Copies:** `src/taskloop/contracts/schema.py:1-147` (**147**) and `_delegate/src/delegate/contracts/schema.py:1-104` (**104**). They recursively construct record schemas and strict structured-output variants. Move generic tests/helpers from `tests/contracts/test_schema.py:31-39` (**9**) and `:83-117` (**35**), plus `tests/contracts/test_response_format.py:19-64` (**46**). **341 = M 237 + D 104**; **90 test lines** move.

Task-loop is the richer base: TypedDict, aliases, annotations, `unstrict` and `prune`; delegate contributes dataclass field descriptions, omission sentinels and configurable tag names. Inspection must be a backend interface, not an import of either app. Existing walkers do not generally recurse through every `anyOf` shape; extraction must not silently fix that.

```python
schema_of(record_type, *, inspect) -> dict
strict(schema) -> dict
unstrict(value, schema) -> object
prune(value, schema) -> object
testing.strict_errors(schema); testing.nullable_errors(contract, sent)
```

**Consumers:** both apps; potential shelf LLM users are not counted demand.

**Contracts:**

- Dataclass and msgspec inspectors preserve required order, aliases, tags, descriptions and root versions.
- Nullability and defaults retain both donors' current output, including unsupported-type failures.
- Strict rewriting copies inputs; pruning and null removal preserve response acceptance.
- Generic test records replace `enums.Step`; answer/schema fixtures remain task-loop holdouts at `test_schema.py:42-80`.

**Risk / cost:** high / medium: required-field drift can stall every worker. **Order:** tag transforms and test helpers → adopt delegate → adopt task-loop → move generation behind inspectors → delete delegate's parallel walker only after parity and reachability checks. No speculative dead-code credit is assumed.

## C04 — ✅ Extract codec-injected JSON documents and transactions

**Shelf first:** `atomic-io` already exports `atomic_write_bytes/text/json` at `_shelf/packages/atomic-io/src/atomic_io/__init__.py:21-79`; process-lock already provides exclusion. Neither owns typed document outcomes or transactions. Create **json-document** over those packages, not another atomic writer.

**Copies / volume:** `src/taskloop/contracts/stores.py:44-120` (**77**); `_delegate/src/delegate/contracts/stores.py:61-65` (**5**), `:91-101` (**11**), `:183-190` (**8**); `src/taskloop_dash/tails.py:22-33` (**12**); generic tests `tests/contracts/test_sealed_read.py:18-42` (**25**). **138 = M 121 + D 17**, including 25 test lines.

These read and atomically replace documents, optionally under a read/modify/write lock. Task-loop's four-result reader is the best base. Delegate intentionally defaults damaged state after warnings; dashboard readers default to empty. Keep those caller choices. Delegate compact JSON/private modes differ from task-loop indent-1 writes. Inject encoding and error translation; keep retired-state warnings and profile selection in the app.

```python
Document(path, *, decode, encode, classify_error)
Document.read() -> Present | Missing | Damaged | ForeignVersion
Document.write(value); Document.delete()
Document.transaction(*, lock, missing) -> ContextManager
```

**Consumers:** task-loop stores/dashboard and delegate. Lifesim report readers usually fail loudly and are not automatic adopters.

**Contracts:**

- Missing, unreadable, damaged JSON, invalid encoding and foreign versions remain distinguishable.
- Serialization/replacement failure preserves the old file; codec bytes and mode match each donor.
- Concurrent transactions lose no updates; an exception in the body commits nothing.
- Genericize `NetPause` in the moved tests; keep reexec tests at `test_sealed_read.py:45-59` local.

**Risk / cost:** high / medium: reading corrupt authoritative state as empty can overwrite owner intent. **Order:** pure read outcomes → tagged writer → delegate tolerant adapter → task-loop strict adapter → transactions last. The app retains all ask transitions and state-default decisions.

## C05 — ✅ Evolve jsonl-log into the single typed log, tail, retention and append-pool substrate

**Shelf first:** `_shelf/packages/jsonl-log/src/jsonl_log/__init__.py:27-32` already exports `Jsonl`, `JsonlLog`, `Entry`, cursor operations and one-write append primitives. `cursor.py:57` provides byte-cursor reading. Missing: byte budgets, predicate compaction under the writer lock, typed skipped-row accounting, bounded raw tails and a fork-aware unrotated handle pool. Evolve **jsonl-log**.

**Disjoint donor ranges:**

| Donor | Lines |
| --- | ---: |
| `src/taskloop/contracts/stores.py:123-168` | 46 |
| Same file `:212-224` | 13 |
| `src/taskloop/contracts/rotating.py:1-21` | 21 |
| `src/taskloop_dash/jsonl.py:14-62` | 49 |
| `src/taskloop_dash/tails.py:36-51` | 16 |
| `src/taskloop/adapters/applog.py:1-91` | 91 |
| `_delegate/src/delegate/contracts/stores.py:40-47,118-135` | 26 |
| `tests/contracts/test_jsonl.py:24-146` | 123 |
| `tests/contracts/test_rotation.py:19-35` | 17 |
| `tests/adapters/test_applog.py:29-82` | 54 |
| `tests/adapters/real/test_applog.py:1-57` | 57 |

This is **513 = M 438 + D 75**, including **251 test lines**. D is dashboard's 49-line duplicate reader plus delegate's 26-line append/read/compaction copy. App log records, usage cutoffs and all engine-wiring assertions stay local.

**Differences / best base:** shelf byte spans plus task-loop's pool are the base. Dashboard polls cap input at 1 MiB; the shelf limit counts accepted records. Incremental reads require a newline; whole-file readers accept a valid unterminated last record. Delegate decodes with replacement and reconstructs newlines; task-loop compaction preserves raw spans. Shelf rotation expires files, not individual rows. The pool accepts already framed text and must not suddenly rotate or add JSON framing. Its PID/inode checks and close-on-exec behavior are substantial substrate, not application policy.

```python
Log(path, *, encode, decode, rotation=None)
Log.append(value); Log.read_from(offset=0, *, limit=None, max_bytes=None)
Log.tail(n, before=None) -> Page
compact(path, *, decode, keep, lock, encode=None) -> Compaction
AppendPool(limit=16).append(path, bytes); close_all()
tail_lines(path, *, max_bytes) -> list[str]
```

**Consumers:** task-loop engine/dashboard and delegate history/live files; shelf already owns the primitive. No lifesim log consumer was established.

**Contracts:**

- UTF-8 byte offsets, skipped complete rows, truncation, replacement, torn tails and stat/open disappearance retain both donors' behavior.
- Budget overflow has a defined outcome; an oversized line must not silently turn a bounded poll into an unlimited read. Fix any existing stall separately.
- Compaction and append share exclusion; retained bytes, equality cutoffs and no-op rewrites are pinned per adapter.
- Pool reuse, replacement detection, LRU eviction, fork separation and exec closure pass the moved unit and real-process tests.

**Risk / cost:** high / medium: lost history, hidden live events or inherited descriptors. **Order:** raw tail and pool contracts → pool tag/adoption → typed cursor/page API → dashboard adapter → delegate reader → compactor → remove wrappers. Keep `test_applog.py:85-121` and `test_rotation.py:37-41` as app wiring holdouts.

## C06 — ✅ Finish stream-proc capture and recorded-process ownership

**Shelf first:** `_shelf/packages/stream-proc/src/stream_proc/__init__.py:14-18` exports `run`, `Result`, `alive`, `proc_start`, `stop_tree`, `TermHold` and `popen_held`. Existing `any-proc` has a different one-shot marked-JSON runner and daemon supervisor. Evolve **stream-proc** with capture and recorded handles.

**Copies:** `src/taskloop/adapters/procs.py:23-68` (**46**) and `:91-115` (**25**); `_delegate/src/delegate/adapters/procs.py:37-50` (**14**) and `:83-91` (**9**). Move `tests/adapters/real/test_procs.py:39-108` (**70**) and `tests/adapters/real/test_kill_tree.py:1-90` (**90**). **254 = M 231 + D 23**, including **160 test lines**.

These capture streamed output and represent persisted process identities for tree stopping. Task-loop's timed-wait handle is the base; delegate's orphan handle polls once. Task-loop rebinds a missing token to the current process, delegate retains `None`. Capture returns timeout status 124 in task-loop and raises `TimeoutExpired` in delegate. Preserve both at app adapters. Delegate's stdin-piped worker spawn (`procs.py:31-34`) exposes a further shelf capability gap, but earns no extra lines here.

```python
capture(argv, *, input=None, tick=None, **run_options) -> Captured
RecordedProcess(pid, start)
RecordedProcess.poll(); RecordedProcess.wait(timeout=None)
stop_recorded(pid, start, *, grace) -> StopReport
```

**Consumers:** both apps. Lifesim `unity_slot.py:43-65` forwards signals to an owned child; it needs an explicit child-only/Windows contract before adopting tree semantics.

**Contracts:**

- PID/token mismatch causes no root or group signal; unavailable process tables remain unknown, not empty.
- Capture drains stdout/stderr without deadlock and preserves final torn text, signal return values, timeout output and tick ordering.
- SIGTERM during spawn, escaped descendants and TERM-resistant children leave no owned survivor unreported.
- Unknown token rebinding and timed versus immediate wait remain explicit compatibility choices.

**Risk / cost:** critical / medium: signaling an unrelated process or leaving workers alive. **Order:** recorded identity contracts → tag handles → delegate orphan adapter → task-loop handle → capture API → adapters retaining old timeout/result conventions. Worker/WorkerEnd records and worker outcome classification remain in delegate.

## C07 — ✅ Evolve process-lock waiting and thread exclusion; do not trust stale PID hints

**Shelf first:** `_shelf/packages/process-lock/src/process_lock/__init__.py:104-161` has `ProcessLock.acquire/release`; `holder` and `held` are public. It already uses kernel-released flock. Missing from the app's desired higher-level contract: once-only wait notification, cancellation checks and compatibility with its separate holder sidecar. Evolve **process-lock**, parameterizing callbacks rather than importing `LockRecord`.

**Copies:** `src/taskloop/adapters/locks.py:25-31` (**7**) and `:65-91` (**27**); `_delegate/src/delegate/contracts/stores.py:27-37` (**11**); `tests/adapters/test_locks_mutex.py:1-36` (**36**). **81 = M 70 + D 11**. These provide same-process exclusion and timed acquisition. Lifesim's `_lifesim_tools/unity_slot.py:25-41` is another **17 lines**, outside the denominator, with Windows byte-range behavior.

Use shelf as the lock authority; move task-loop's wait mechanics as an additive API. A dead PID in a holder hint must never authorize unlinking or breaking a held inode. Lifesim counting slots and Windows support are missing, so its direct migration remains untested; that does not block extracting the POSIX mechanism now.

```python
ProcessLock.acquire(path, *, timeout=None, reentrant=False,
                    on_wait=None, check=None) -> ProcessLock
holder(path) -> Holder | None
```

**Consumers:** task-loop and delegate; lifesim only after Windows/counting parity.

**Contracts:**

- Two threads and two processes exclude each other; failed acquisition releases the thread mutex.
- Waiting notification occurs once; cancellation and timeout preserve app exception translation.
- Death releases ownership; stale records cannot break a live flock, and the lock inode is never replaced.
- A separate future Windows test proves far-offset byte locks leave labels readable and counting slots bounded.

**Risk / cost:** critical / medium: simultaneous landers or a permanently wedged resource. **Order:** moved mutex regression → additive tagged acquisition → delegate adapter → task-loop wait engine; retain sidecar encoding, lock paths and resource/land naming locally.

## C08 — ✅ Extract file-signature and TTL caches

**Shelf first:** `http-cache` is a persistent conditional-HTTP cache and `llm-cache` stores completions; neither provides these local cache objects. `git-porcelain/real_cache.py` contains related file-signature machinery, but no suitable public general cache. Create **any-cache**, then let git-porcelain reconcile its internal implementation separately.

**Donor:** `src/taskloop_dash/cache.py:1-72`, **M 72**. It owns bounded parsed-file caches and synchronized TTL values. Related reimplementations appear in `src/taskloop/contracts/locator.py:104-119` and `src/taskloop/adapters/gitmemo.py:1-100`; the latter is already counted in C01 and neither earns additional C08 credit.

Dashboard is the base for the general API. It uses `(mtime, size)`; locator uses nanoseconds; git caches use inode/device and dependency sets. Signature selection must be explicit. Builds currently happen outside the mutex, so concurrent duplicate builds are possible; extraction must not silently promise single-flight behavior.

```python
TtlCache(clock).get(key, ttl, make)
TtlCache.peek(key); put(key, value); drop(key); clear()
FileCache(limit=500, *, signature).get(path, load, missing=None)
```

**Consumers:** task-loop dashboard/locator; git-porcelain is a potential package consumer. No demonstrated delegate or lifesim adoption.

**Contracts:**

- Expiry equality, injected clocks and timestamp-bearing `peek` retain behavior.
- Missing files evict entries, file replacement changes configurable signatures, and LRU eviction is bounded.
- Loader failures do not populate a result; concurrency behavior is documented and pinned.

**Risk / cost:** medium / low: stale dashboard facts. **Order:** move unchanged cache → tag → dashboard adoption → locator adapter → evaluate git internal reuse without double-counting C01.

## C09 — ✅ Extract time input dialects instead of forcing one grammar

**Shelf first:** `timefmt` formats values; `_shelf/packages/due-schedule/src/due_schedule/__init__.py` exposes `schedule_is_due` for interval/cron schedules. Neither supplies owner-entered timestamps. Create **any-time** for the real input grammars.

**Copies:** `src/taskloop/domain/timespec.py:1-26` (**26**); `_delegate/src/delegate/domain/time/spec.py:28-64` (**37**); `src/taskloop_dash/tails.py:10-19` (**10**). **M 73**. They parse ISO, epochs, relative durations and local weekly times.

Task-loop's parser supplies the richer future-time grammar, delegate supplies epoch-ms/weekly forms. They differ on decimal durations, leading plus, seconds units, zero, bools, epoch thresholds, naive zones, invalid clock values and errors versus `None`. The deep module has named public dialects; it must not hide these differences in an undocumented mode flag.

```python
parse_future(text, now_datetime) -> float
parse_until(value, now_epoch) -> float | None
to_epoch(value, *, milliseconds=False, zero_is_missing=False)
next_weekly(spec, now_epoch) -> float | None
```

**Consumers:** both apps and dashboard. Lifesim demand unproven.

**Contracts:**

- Parameterized donor corpora retain accepted/rejected forms and error conventions.
- Preserve naive/local/offset interpretation, DST and next-day/next-week equality.
- Millisecond thresholds, zero, negative and malformed inputs remain explicit per operation.

**Risk / cost:** high / medium: wrong hold or retry time. **Order:** unchanged dialect fixtures → tag distinct operations → delegate → dashboard → task-loop; unify syntax only in a separate behavior release.

## C10 — ✅ Consolidate formatting; keep CLI command policy local

**Shelf first:** `_shelf/packages/timefmt/src/timefmt/__init__.py:28-109` exports `fmt_dur`, `fmt_span`, `fmt_until`, `human_count`. It lacks the donors' exact spacing/rounding and a browser implementation. Evolve **timefmt** with additive formats and a small shipped JS module. `_shelf/packages/verb-cli/src/verb_cli/__init__.py:103-145` already offers `flags_of`, `to_argparse`, `kwargs_of`; it does not encode these applications' verbs.

**Copies:** `_delegate/src/delegate/domain/time/spec.py:9-17` (**9**); `src/taskloop_dash/static/js/format.js:9-35` (**27**); `src/taskloop/cli/loop.py:48-50` (**3**) and `:111-113` (**3**). **42 = M 39 + R 3**. They format spans/ages/counts and one fixed-width row. Replace the tiny row wrapper with its existing stdlib format expression at the caller; no table library is necessary to remove it.

Delegate uses `<1m` and spaced day/hour text; shelf clamps negatives and returns `0m`; JS rounds, has a one-unit variant and token-count minimums. Preserve named forms and JS/Python rounding differences. The Python shelf implementation is the base; browser functions stay JavaScript, not a Python service call.

```python
fmt_span(seconds, *, style="compact") -> str
fmt_ago(now, then, *, style) -> str
human_count(value, *, style) -> str
# JS exports: dur, age, unit, tokens
```

**Consumers:** task-loop and delegate; other shelf users already use timefmt. No lifesim formatter adoption proved.

**Contracts:**

- Golden boundaries at 0/59/60 seconds, hours, days and count magnitude transitions.
- Preserve negative/null handling, spaces, padding and exact CLI text.
- Cross-language fixtures explicitly retain JS rounding and minimum-token-count behavior.

**Risk / cost:** low / low. **Order:** additive tag → delegate formatter → CLI age → JS module → remove row wrapper. ANSI/markdown escaping are separate formats: `format.js:3-7` marker semantics and bead abbreviation stay app-owned. No interactive TUI was established; cockpit views are application projections, not a terminal framework to move wholesale.

## C11 — ✅ Extract installation facts and numeric versions; retain update authority

**Shelf first:** `_shelf/packages/app-dirs/src/app_dirs/__init__.py:36-77` exports config/state/cache roots and `plugin_data_dir(env)`. It does not derive a plugin's own data directory from its installed cache path. `plugin-surface` loads manifests, not installed releases. Evolve **app-dirs** for cache-path facts and create a small **numeric-version** primitive; do not create a factory self-update service.

**Copies / volume:** `src/taskloop/contracts/ids.py:87-106` (**20**), `src/taskloop/app/loop/versions.py:19-22` (**4**), `:31-42` (**12**), `_delegate/src/delegate/app/env.py:33-41` (**9**), and `src/taskloop/contracts/paths.py:10-12` (**3**). **48 = M 41 + D 7**. These parse dotted numeric versions, fingerprint a specified file set and derive installation/config roots.

Use `Version` as the numeric base, preserving its ASCII-only validation; `version_key` currently accepts a broader `isdigit` grammar. Delegate must derive its own plugin data path and intentionally ignores ambient `CLAUDE_PLUGIN_DATA`. Task-loop accepts relative XDG roots; shelf ignores them. Those are adapter compatibility requirements, not permission to choose a new state directory. File lists/patterns are app parameters to the fingerprint operation.

```python
NumericVersion.parse(text) -> NumericVersion
fingerprint(files) -> str
installed_plugin(path) -> PluginLocation | None
config_dir(app, *, env, home, compatibility=None) -> Path
```

**Consumers:** both apps; version/installation tooling elsewhere in shelf is potential demand.

**Contracts:**

- ASCII versus Unicode numeric input, malformed parts and version ordering retain donor behavior.
- Cache-path identity sanitization and missing paths match delegate fixtures; lookup creates nothing unless requested.
- Fingerprint is identical for the same ordered file set and invalidates a same-version reinstall.
- Relative/empty XDG and foreign plugin-data env values cannot silently move authoritative state.

**Risk / cost:** high / medium: wrong version or apparently empty state. **Order:** numeric parsing → fingerprint → cache-path facts → compatibility root adapters. Owner pin precedence, bad-version persistence, rollback eligibility and when to reexec remain local in `versions.py:45-109`; C05 provides descriptor cleanup before exec. No release-clone or update-authority code moves under this candidate.

## C12 — ✅ Extract the existing ULID primitive; ❓ replacing it with a third party is untested

**Shelf first:** no catalog ULID package exists. `any-file` slugging is not an opaque time-sortable identifier. Create **sortable-id** from the actual implementation; tender **python-ulid** only after compatibility tests, not from remembered API claims.

**Donor:** `src/taskloop/contracts/ids.py:31-84` (**54**) and `tests/contracts/test_wire.py:202-208` (**7**): **M 61**. It generates/parses 26-character Crockford IDs from milliseconds and 80 entropy bits. This corrects the first pass's claim that no manual ULID existed. Delegate's UUID uses (`app/run.py:101,184`) name different identities and must not change format just to create a second consumer.

```python
SortableId.new(now_seconds, entropy=None) -> SortableId
SortableId.parse(text) -> SortableId
SortableId.of(text) -> SortableId | None
SortableId.to_wire() -> str
```

**Consumers:** task-loop; delegate and other shelf users are prospects, not duplicate-demand multipliers. This is a justified extension beyond the strict duplication lens.

**Contracts:**

- Exact output for fixed timestamps/entropy, lexical ordering and wire round trips.
- Uppercase alphabet, length and leading-digit validation preserve existing accepted names.
- Overflow, negative timestamps and malformed entropy pin current behavior before any validation change.

**Risk / cost:** high / low: unreadable run directories or identity collisions. **Order:** move implementation unchanged → tag → retain `RunId` app alias/seam → migrate call sites. A third-party backend earns retirement only after differential fixtures pass; **zero extra R credit** is claimed. Repository/bead/check identity rules and the gate's `RunKey` stay in task-loop.

## C13 — ✅ Extract shell lexical mechanics; refuse shared authorization

**Shelf first:** no catalog shell-analysis package exists. Stdlib `shlex` is already used; it does not retain enough separator provenance for both donor policies by itself. Create **shell-words** over shlex and the existing quote-aware splitter.

**Copies:** `src/taskloop/hook/rules.py:13-16` (**4**); `_delegate/src/delegate/domain/policy/matchers.py:26-37` (**12**) and `:73-126` (**54**). **70 = M 66 + D 4**. These unwrap shell invocations and split/tokenize command pieces. Delegate is the richer base; task-loop's punctuation tokenization is a compatibility operation. Quoted separators, newline handling and malformed quoting differ.

```python
words(command) -> list[str]
unwrap(command, depth=3) -> str
pieces(command) -> list[list[str]] | None
split_unquoted(command) -> list[str]
```

**Consumers:** task-loop hook and delegate guards. Lifesim argv launchers need no shell parser.

**Contracts:**

- Quoted/escaped `;`, `&&`, pipes and newlines retain provenance through splitting.
- Nested shell `-c`/`-lc`, wrappers and depth exhaustion match both donors.
- Malformed quoting preserves each caller's allow/refuse behavior; lexing does not decide authorization.
- Read-only and writer policy fixtures run unchanged as consumer holdouts.

**Risk / cost:** high / medium: false allows or refusal loops. **Order:** differential lexer fixtures → tagged primitive → delegate tokenizer → task-loop hook tokenizer. Keep command allowlists, secret-path rules, allowed recipe runners and kill authority in the apps; the counted spans' loop/redirect mechanics become generic parser options.

## C14 — ✅ Extract provider observations: transcripts, context, usage and rate-limit transport

**Shelf first:** `anyllm` wraps model providers, not local CLI event logs; `jsonl-log` supplies byte transport, not provider interpretation. No catalog package owns these readers. Create **agent-observation**, composing C05 and stream-proc. This package knows vendor formats, **not lane routing, worker completion policy or factory stop reasons**.

**Concrete split / count:**

| Donor span | Lines | Generic responsibility |
| --- | ---: | --- |
| `src/taskloop/adapters/opencode.py:1-69,85-86` | 71 | Read-only session facts and transcript search result |
| `src/taskloop/adapters/context_size.py:1-43` | 43 | Last reported context from transcript formats |
| `_delegate/src/delegate/adapters/harness/claude.py:21-72,105-166` | 114 | Vendor text, token arithmetic and event decoding |
| `_delegate/src/delegate/adapters/harness/codex.py:91-137` | 47 | Vendor events and transport-failure facts |
| `_delegate/src/delegate/adapters/harness/opencode.py:171-249,261-276` | 95 | Stream/log parsing and provisional tool correlation |
| `_delegate/src/delegate/adapters/codex_account.py:1-134` | 134 | Bounded JSON-RPC limit query and rollout usage facts |
| `_delegate/src/delegate/app/usage.py:41-47,85-100` | 23 | Vendor bucket/usage normalization |
| `_delegate/src/delegate/adapters/statusline.py:1-30` | 30 | Provider status-file decoding/writing |
| `tests/adapters/test_opencode.py:39-85,111-120,132-137` | 63 | Synthetic SQLite fixture and reader assertions |

**M 620**, of which 63 are tests/fixtures. Public DTOs must replace `delegate.contracts.events` imports, and source roots/mappings must be injected. This counts genericized donor spans, not permission to import delegate from shelf.

**Differences / best base:** delegate's event decoders are richer; task-loop supplies read-only SQLite/context facts. Task-loop's Claude transcript lookup chooses the last sorted match, delegate chooses the first. Context readers use different tail budgets and token-zero fallbacks. Codex distinguishes last-turn context from cumulative thread usage; Claude fresh input excludes neither cache reads nor cache writes until normalized. Provider formats require explicit versioned fixtures. Preserve locator choice/budget and unknown-cost semantics separately. Family-to-provider mapping stays in task-loop's `opencode.py:72-84`; lane price overrides stay in delegate's accounting policy.

```python
Observations(provider, *, roots, read, run, clock)
Observations.events(lines) -> Iterator[ProviderEvent]
Observations.context(ref) -> int | None
Observations.usage(ref, *, since=None) -> Usage | None
Observations.limits() -> LimitsRead
Observations.transcript(ref, *, selection) -> str | None
```

**Consumers:** task-loop and delegate; shelf's LLM packages are prospective consumers. No lifesim demand proved.

**Contracts:**

- Same synthetic Claude/Codex/OpenCode streams yield the donor facts, with stable malformed/unknown-event behavior and tool start/end correlation.
- SQLite fixture tests cover missing/locked/changed schemas, last assistant with tokens and newer part timestamps; reads never write the DB.
- Distinguish per-turn, cumulative, resumed-thread and child-thread usage; preserve unknowns instead of inventing zero cost.
- JSON-RPC ignores unrelated notifications, respects an absolute deadline, handles partial lines/EOF and always reaps its owned child.
- Transcript selection and bounded tails preserve both donors' existing results. No contract test needs live credentials or real account files.

**Risk / cost:** high / high: bad context facts trigger fresh sessions; bad usage facts affect routing. App adapters must keep those decisions local. First-result-wins, final-answer grace, worker-denial enforcement, summaries and lane spend thresholds are **not** moved.

**Order:** synthetic observation DTOs/fixtures → pure token and event readers → tag → task-loop context adapter → delegate parser adapters → read-only transcript lookup → JSON-RPC transport → usage normalization. Use supplied files and fake runners in contracts; credential acquisition is outside the package and outside this review.

## C15 — ✅ Extract local HTTP transport and constrained static serving

**Shelf first:** `static-page-check` exposes `import_problems`, `page_problems`, `pin_problems`, `colour_problems`, `budget_problems`; it validates assets, not serves them. `http-fetch` is a client. Create **local-http**, retaining stdlib `http.server` underneath.

**Copies / volume:** `src/taskloop_dash/assets.py:1-36` (**36**), `src/taskloop_dash/http.py:50-86` (**37**) and `src/taskloop_dash/bind.py:96-108` (**13**): **M 86**. They constrain static paths, encode HTTP responses, parse bodies and bind an address set atomically. `dev/dash_check.py:97-104` is another server lifecycle, counted separately in C21.

Use the production static path checks and all-or-none bind as the base. App paths, `/api/version` payload, write verbs and authorization move behind injected route callbacks. MIME allowlists, deny names, body budget and headers are options, not factory defaults. Current POST reading truncates to MAX_BODY rather than declaring overflow; keep or change that only through a named contract. Bind policy is not the binding mechanism.

```python
StaticFiles(root, *, types, deny, max_bytes).get(path) -> Response
handler(get, post, *, headers, max_body) -> Handler
bind_all(addresses, port, handler) -> BoundServers
```

**Consumers:** task-loop dashboard and its development server; shelf HTTP-serving consumers are prospects. Delegate has no server to migrate.

**Contracts:**

- URL decoding, NUL/backslash/dot segments, symlink escape, MIME denial and size limits preserve static refusals.
- Query handling, conditional headers, malformed/oversized bodies and error serialization retain current transport behavior.
- Partial multi-address bind closes every prior listener; port zero is reused consistently.

**Risk / cost:** medium / medium: unreachable dashboard or unintended exposure. **Order:** static reader → tag/adopt → generic handler callbacks → bind lifecycle. Loopback/Tailscale restrictions, installed-copy checks and POST command decisions stay local in `bind.py:20-93` and app routes. No dashboard view, golden or worker contract is counted as transport.

## C16 — ✅ Extract process simulation and golden helper substrate, not the factory world

**Shelf first:** git-porcelain already owns its fake (C01). Stream-proc has real-process tests but no exported deterministic subprocess simulator. Add **stream-proc.testing**; add the generic golden helper under the record package's testing extra. Do not invent another catch-all testing package.

**Donors:** `tests/support/procsim.py:54-86` (**33**) and `:102-249` (**148**), `tests/rules/test_procsim.py:1-71` (**71**), `tests/rules/real/test_procsim.py:1-18` (**18**), `tests/contracts/test_wire.py:47-52` (**6**). **M 276**, all test/support lines.

These simulate argv calls, timeout/stop output and process guards, and compare/update goldens. Task-loop's simulator is the base; shelf's existing real/fake testing practices are the second implementation pattern. Inject default commands and registration scope. Keep `has-f`, conflict-marker behavior, fixture paths and the engine's default registry in task-loop. `tests/support/engine_case.py` is not a portable fixture just because it owns temp directories.

```python
ProcessWorld(*, defaults, allow_real=False)
ProcessWorld.install(stack); register(argv, fake); calls(argv)
ProcessWorld.check(*, must_spawn=False)
exits(code, out=""); takes(seconds, ...); blocks(...)
golden(path, produced, *, update=False)
```

**Consumers:** task-loop now; delegate/lifesim test suites and stream-proc are credible adopters, but no absent delegate suite is credited.

**Contracts:**

- Subprocess and stream-proc calls return the same registered result without spawning; env prefixes and text/bytes/check modes agree.
- Wall limits and blocking cancellation require no real sleep; registration and teardown cannot leak between tests.
- Unregistered Popen/fork fails in guarded tests; real tests must actually spawn or open the declared resource.
- Golden comparison defaults to read-only, names the failing path, and updates only under explicit caller control.

**Risk / cost:** medium / medium: a lying fake can mask a factory regression. **Order:** publish simulator contracts → adapt app registry → move guard tests → adopt existing suites → migrate golden helper. Keep real process contracts alongside it; no runtime pytest dependency.

## C17 — ✅ Extract the architecture gate engine and its planted scenarios

**Shelf first:** `_shelf/packages/blueprint/src/blueprint/concerns/cli_parse.py:35-80` demonstrates the same source-scanning/planted-rule pattern, but blueprint's public unit is a concern/context check, not a reusable AST/ratchet engine. Create **source-audit**, then adapt blueprint separately. Reuse stdlib `ast`, `tokenize` and graph algorithms rather than growing another parser.

**Counted split in `tests/rules/gate_rules.py`:** `:63-173` (**111**), `:174-215` (**42**), `:217-278` (**62**), `:350-391` (**42**), `:415-475` (**61**), `:477-503` (**27**) and `:536-620` (**85**): **M 530**, all test/tooling lines. **196 lines of this file remain**. It scans source, measures SLOC, compares ratchets, finds import cycles, validates configurable AST patterns and exercises planted violations.

Task-loop supplies the richer scanner/testing base. `_lifesim_tools/check_design.py:73-74` and its `tests/test_check_design.py:43-69` repeat finding collection and synthetic-tree runner mechanics, but its ontology rules do not use Python AST and are not claimed as moved. Shelf blueprint supplies another source-checking consumer pattern. Parameterize scan roots, caps, skipped directories, forbidden names/calls, layer names, allowed edges, placement literals and diagnostics. The app retains every actual rule value and its repository-wide enforcement assertions. Mixed functions are refactored around those parameters; current constants are not a shelf dependency.

```python
SourceTree(root, *, scan, exclude).files() -> Iterator[Source]
Source.measure() -> Measurement
audit(tree, rules) -> list[Finding]
ratchet(actual, baseline, *, ceiling) -> list[Finding]
testing.planted(files, rules) -> list[Finding]
```

**Consumers:** task-loop immediately; blueprint and lifesim's lint harness are prospective adopters, so they do not inflate the ranked consumer count.

**Contracts:**

- Move planted SLOC/decorator/nested-definition, stale-ratchet, mutable-global and import-cycle scenarios; synthetic policy names replace app package names.
- Parameterized forbidden-call/argv scans ignore prose and exempt paths without hiding executable violations.
- Findings retain stable file/line attribution, deterministic order and diagnostic distinction between growth and a baseline entry that must disappear.
- Different consumer rule tables produce different results from the same generic engine, without importing any app.

**Risk / cost:** low production / high refactor cost: a weak gate can admit later regressions, but this extraction does not execute land. **Order:** measurements and findings → tag → ratchets → AST checks → planted harness → app enforcement adapters. Keep current caps and ratchet contents unchanged; the shelf constitution does not impose task-loop's size caps on shelf.

## C18 — ✅ Extract structural config overlay; keep profile semantics in apps

**Shelf first:** `_shelf/packages/settings-base/src/settings_base/__init__.py:41-88` exports environment-reference resolution, config-path lookup and a YAML settings source. It does not provide delegate's JSON overlay semantics. Add a format-independent **overlay** operation there, using C02/msgspec for typed validation in adapters. Adding pydantic-settings/platformdirs wholesale would not remove application schema rules.

**Donor:** `_delegate/src/delegate/app/env.py:57-62`, **M 6**. It deep-copies defaults and recursively overlays mapping values; task-loop's schema/default loaders and shelf settings sources are related loading machinery, not identical merge algorithms. This is a small extension beyond proven cross-app duplicates and earns only its six measured lines.

```python
overlay(defaults: dict, overrides: dict | None) -> dict
```

**Consumers:** delegate now; settings-base's existing users are potential adopters. Task-loop should adopt only where it actually has overlay semantics.

**Contracts:**

- Nested mappings merge, scalars/lists replace, and defaults remain unmodified.
- Pin whether newly inserted mutable override values are shared, matching the donor before changing copy semantics.
- Null/empty override behavior matches current input handling.

**Risk / cost:** low / low for the mechanism; profile replacement would be high risk. **Order:** add/tag helper → replace delegate function → leave `load_routing`, retired-key warnings, `profile` exclusion and lane overrides local. Task-loop already calls msgspec; its remaining validators express application rules, adjudicated below.

## C19 — ✅ Extract activity deadlines and exponential delay; retain rest/reason tables

**Shelf first:** stream-proc already owns idle/wall timeouts; `_shelf/packages/any-proc/src/any_proc/__init__.py:3-15` describes a supervisor with capped restart backoff. Neither exposes delegate's sleep-adjusted activity tracker or task-loop's precise jitter formula. Evolve **stream-proc** for activity tracking and **any-proc** for the delay primitive, not for factory retry policy.

**Donors:** `_delegate/src/delegate/app/watch.py:95-133` (**39**) and `src/taskloop/domain/lanes/pauses.py:86-88` (**3**): **M 42**. They track first-event/silence deadlines excluding long poll gaps and compute capped exponential delay with jitter. The source spans are implementation portions; app class wrappers and threshold tables remain.

Delegate's activity tracker and task-loop's bounded exponent are the bases. Generic idle timing must not inherit Claude/Codex thresholds, final-answer grace or the factory rule that unknown reasons require an owner. Backoff caps before jitter; changing that order changes the maximum wait.

```python
Activity(first_event_s, silence_s, *, clock, sleep_gap_s, beat_s)
Activity.touch(); Activity.poll() -> Deadline | None
delay(base_s, cap_s, attempt, *, random, jitter=(0.8, 1.2)) -> float
```

**Consumers:** delegate and task-loop respectively; shelf process runners already have related mechanisms. No extra app-policy tests are counted as moved.

**Contracts:**

- First-event and silence strict inequalities, sticky deadlines, suspension adjustment and heartbeat throttling match delegate.
- Attempt zero, negative/large attempts, random endpoints and cap-before-jitter match task-loop exactly.
- App holdouts retain unknown-reason owner wake, per-reason history and final-answer/tool-in-flight rules.

**Risk / cost:** high / medium: premature worker termination or retry storms. **Order:** pure clocks/random fixtures → tagged tracker/delay → delegate tracker adapter → task-loop delay call. Keep `watch.py:22-37,46-86,135-148`, `StuckWatch`'s red-round decisions and the pause table local. Vendor reset prose (`harness/reset_parse.py:22-67`) is further parsing evidence, not another counted retry engine.

## C20 — ❓ Delete vendored distributions only after installed-plugin bootstrap parity

**Shelf first:** these are already promoted packages, not newly found source. The task-loop pins are in `dev/vendor.json:1`; `dev/vendor.py:12-25` explicitly describes removing this workaround when plugins depend directly on shelf. Current delegate also has a `_vendor` tree.

**Copies / count:** `rg --files skills/task-loop/_vendor _delegate/skills/delegate/_vendor -g '*.py' | xargs wc -l` reports **8,129 lines**. This measured directory inventory is the candidate scope; do not claim those lines as another C01–C19 implementation. Task-loop packages include atomic-io, child-env, git-porcelain, jsonl-log, process-lock, static-page-check and stream-proc; delegate additionally uses app-dirs/timefmt. Their public APIs are the existing APIs cited above, not a new vendor framework.

```python
# Proposed distribution contract, not a runtime wrapper API:
# Each launcher imports the dependency pinned by package tag/revision.
# The installed plugin and offline development entrypoints resolve identically.
```

**Consumers:** both applications; shelf is the canonical implementation. Best base is the released shelf artifact, never an edited vendor copy. The important behavioral difference is distribution: delegate's `skills/delegate/route.py:1-12` is a plain Python launcher; task-loop's plugin uses a script bootstrap. Removing files without supplying pinned dependencies breaks installed consumers even if unit tests pass in a developer environment.

**Deciding contracts:**

- Launch every supported installed-plugin entrypoint in a clean environment with only declared dependencies and immutable pins.
- Prove plain-Python, script and offline/no-resolver paths either work as promised or receive an explicitly approved distribution change.
- Cold start, import identity and all existing real/fake smoke contracts match the vendored release.
- Preserve reproducible provenance and rollback; do not silently select a global package version.

**Risk / cost:** high / high. **Approved retirement: 0; conditional D 8,129.** First produce a tested distribution plan, then publish/bootstrap one consumer, then remove its vendor tree. Do not delete caches or installed plugin files during development. Removing `dev/vendor.py` or vendor guards could yield further lines, but they are deliberately uncredited here and overlap app release checks.

## C21 — ✅ Extract browser-test driving and layout checks

**Shelf first:** `static-page-check` performs source/asset checks; it does not drive a browser or own viewport tests. No catalog package supplies the observed harness. Create **page-harness**, with an optional testing adapter to local-http and stream-proc. Keep the browser dependency behind the testing surface; no runtime app needs it.

**Donors:** `dev/dash_check.html:10-53` (**44**) and `:55-101` (**47**), `dev/dash_check.py:97-104` (**8**) and `:107-119` (**13**): **M 112**. These create a sized iframe, drive UI actions, collect failures/layout facts and run headless Chrome. The HTML retains **491 lines**, including its scenario definitions and the app-specific hidden-selector constant at line 54.

Use the existing iframe strategy as the base; it handles Chrome's minimum window width. `_lifesim_tools/tests/test_check_design.py:43-69` has the analogous synthetic-runner pattern, but no browser behavior and no extra browser-consumer credit. Refactor hidden selectors, font/tap bounds, exempt widget selectors, write interception response and the `/dev/writes` fetch into injected options/callbacks. App UI rules and scenarios remain in the app.

```python
Browser(executable, *, profile, timeout).run(url, viewport) -> Result
serve_fixture(handler) -> ContextManager[BaseURL]
# JS: harness(frame, options) -> {load, click, type, checkLayout, failures}
```

**Consumers:** task-loop's dashboard test/development flow; other static-page projects are prospects, not established demand.

**Contracts:**

- Phone-size iframe dimensions work even when Chrome cannot size the outer window that small.
- Generic action/layout fixtures distinguish hidden content, overflow, small targets and exempt widgets under supplied rules.
- Timeout, browser-console errors and fixture-server cleanup remain observable; browser failure does not leave owned processes.
- Read-only interception blocks writes while preserving GETs, with the app supplying its response shape.

**Risk / cost:** low production / medium implementation: a false-green browser gate. **Order:** JS helper with synthetic page contracts → tag/adopt → browser runner → fixture-server context manager → keep task-loop scenarios in the remaining HTML. A future Playwright backend is a tender against these contracts, not an unverified claim of line savings.

## Explicit refusals after the substrate splits

These are refusals of the application rules, not excuses to keep their generic engines embedded. The four additional counted groups below are disjoint from the extraction ledger and the largest-file table.

### C22 — ❌ Refuse moving the bead client wholesale as a shared factory policy

`src/taskloop/adapters/bd.py:1-276`, **276 retained lines**, knows bead claim/unclaim, heartbeat, close fencing, actor identity and Dolt sync refusal. Shelf has no matching public bd client; generic subprocess capture exists in stream-proc. A future raw service transport could be separated, but this review has not established a second app implementation or a concrete generic transport retirement span. The application's rule is **a bead's lifecycle writes belong to the actor, and a close with assignee fencing must preserve its refusal semantics**. Keep `BdStore.show/find/claim/unclaim/close` as the local interface; task-loop is the only demonstrated consumer.

Required holdouts: malformed reads never become absence; rejected sync text under exit zero remains failure; assignee fencing and close side effects retain order. **M/D/R 0; no wholesale migration.** Do not relocate `bdcreate`'s follow-up prose/filler or `closeguard`'s work/land evidence policy under a generic client name. Any future transport extraction must keep these adapters and their holdouts local.

### C23 — ❌ Refuse one worker shell-authorization policy

`src/taskloop/hook/rules.py:19-56` (**38**) and `_delegate/src/delegate/domain/policy/shell.py:1-109` (**109**) are **147 retained lines** after C13. Task-loop forbids process killing by name; delegate additionally enforces coordinator-only git, read-only command sets and engine-only recipes. These are **different worker authority rules**. Shelf's child-env and stream-proc APIs provide mechanisms, not permission decisions. Retain `deny_reason(tool, args)`, `git_write(command)`, `read_only_problem(command)` and `writer_problem(command, engine_only)` in their apps.

Required holdouts: quoted text does not become an executed command; coordinator git mutations remain refused; read/writer recipe and own-PID exceptions remain unchanged. **M/D/R 0.** Migrate only the C13 lexer behind these unchanged interfaces. Consumers are the two apps, not evidence that one authorization rule is valid for both.

### C24 — ❌ Refuse the factory path catalog

`src/taskloop/contracts/paths.py:15-288`, **274 retained lines**, defines state locations for runs, slots, asks and owner pins. C11 extracts root facts; app-dirs has `config_dir/state_dir/cache_dir` but cannot decide these filenames. The rule is **run/slot/bead records have distinct persistent identities, and the owner's pin has a distinct writer**. Keep `ConfigDir`, `RunFiles`, `RepoDirs` app-owned. Task-loop and its dashboard are one consumer.

Required holdouts: exact legacy locations; read-only lookup creates nothing; pin/owner-request ownership remains distinct. **M/D/R 0.** Adopt C11 below these classes, without moving the catalog into shelf.

### C25 — ❌ Refuse engine profile rules and their schema as reusable configuration

`src/taskloop/contracts/config.py:1-411`, **411 retained lines**, defines and validates engine profiles. Msgspec/any-record supply decoding, settings-base supplies plumbing, but cannot decide **checks read only within their lane, resource needs must be declared, IDs must not collide after environment mangling, and container checks require a valid container configuration**. Retain `load(data, say_to)`, `graph_problem(checks)` and `resource_problem(engine)` locally. Consumers are task-loop and its profile tools, not delegate's unrelated lane settings.

Required holdouts: retired keys warn without mutation; invalid graph/resource/container settings refuse before execution; committed profile precedence and diagnostic paths remain exact. **M/D/R 0.** C02 changes the codec dependency and C18 supplies a generic overlay where actually needed; neither moves these policy rules. Delegate's enabled/offered lane profile decisions and `app/usage.py` spend/out thresholds are likewise retained, without additional refusal line credit.

## Exactly what the largest remaining files represent

After the counted retirements, these are the **25 largest remaining files** in the measured tree, ranked by retained physical lines. Each is ❌ for wholesale movement because of the named application rule. Generic process/git/codec/test-driving mechanisms used by these files have the extraction seams above. No entire integration suite or factory golden is credited just because its lower-level dependency moves.

For these refusal rows, target is the current app, public interface is the existing test/fixture or contract schema, and consumers are that app's engine/dashboard/tests. The common contract obligations are: preserve current decode/fixture shape; preserve each named domain outcome; retain the suite as a consumer holdout while its mechanisms migrate. Migration is dependency substitution beneath the row, with **zero additional moved/deleted lines**. Risk is changed land/gate/close or worker behavior; cost/risk is not the refusal reason.

| Rank | File and re-read evidence | Retained lines | Verdict and named rule |
| --- | --- | ---: | --- |
| 1 | `tests/dash/golden/closes.json:1-12` | 2,927 | ❌ Closed-bead cards, outcomes and closure evidence are task-loop views. |
| 2 | `tests/fixtures/dash/snapshot.json:1-12` | 2,341 | ❌ Snapshot joins projects, loops and lanes under the dashboard contract. |
| 3 | `tests/contracts/golden/records.json:1-12` | 1,826 | ❌ Exact factory record identities, including RunTrace and epic state. |
| 4 | `_delegate/skills/delegate/contract.json:1-12` | 1,749 | ❌ Worker answer/stop contract, scopes and permanence vocabulary. |
| 5 | `tests/fixtures/dash/mock-8b.json:1-12` | 1,045 | ❌ Specific bead/slot/lane board scenarios and their expected presentation. |
| 6 | `tests/loop/real/test_loop.py:1-12` | 915 | ❌ Loop pick/run/stop lifecycle and ownership. |
| 7 | `tests/run/test_engine_run.py:1-12` | 828 | ❌ Resume, stop and run-budget outcomes. |
| 8 | `tests/run/test_stages.py:1-12` | 817 | ❌ Ordered factory stage handoffs. |
| 9 | `tests/support/narrow_hosts.py:1-12` | 777 | ❌ Typed fakes of engine slice contracts, including outbound land ownership. |
| 10 | `tests/support/engine_case.py:1-12` | 765 | ❌ Composition of the factory's bead, stage, check and worker world; generic fakes are C01/C16. |
| 11 | `tests/land/test_engine_land_1.py:1-12` | 752 | ❌ Land, push, rebase and conflict-resolution outcomes. |
| 12 | `tests/run/test_stages_visual.py:1-12` | 717 | ❌ Visual-stage eligibility, resume counting and bead claims. |
| 13 | `tests/land/test_stages_land.py:1-12` | 706 | ❌ Stale-tree, slot-hygiene and follow-up land rules. |
| 14 | `skills/task-loop/SKILL.md:1-12` | 674 | ❌ The task-loop method and its actor/worktree lifecycle. |
| 15 | `tests/run/test_engine_units.py:1-12` | 652 | ❌ Failure briefs, worker validation and confirmation outcomes. |
| 16 | `tests/land/test_race_invariants.py:1-12` | 640 | ❌ A bead is not claimed/run twice; land and claim races retain their fences. |
| 17 | `tests/contracts/samples.py:1-12` | 600 | ❌ Filled instances of application record families; synthetic codec fixtures move instead. |
| 18 | `tests/e2e/test_release.py:1-12` | 570 | ❌ Release-clone ownership, suite eligibility and launcher reexec behavior. |
| 19 | `src/taskloop/contracts/dash.py:1-12` | 562 | ❌ Wire projection of factory facts and owner writes, not HTTP substrate. |
| 20 | `tests/land/test_stack.py:1-12` | 549 | ❌ Ordered branch/PR landing and stop-on-first-failure receipt rules. |
| 21 | `tests/plan/test_engine_plan.py:1-12` | 546 | ❌ Planning/replanning decisions and accepted plans. |
| 22 | `tests/support/dash_fixtures.py:1-12` | 527 | ❌ Converts the domain board scenarios to its contract records. |
| 23 | `tests/fixtures/delegate3/skills/delegate/contract.json:1-12` | 525 | ❌ Frozen external worker-contract compatibility; it is not a duplicate to delete with the current contract. |
| 24 | `src/taskloop/contracts/ports.py:1-12` | 511 | ❌ Factory requests/results and coordinator authority; generic backend protocols replace implementation below it. |
| 25 | `tests/loop/real/test_loop_more.py:1-12` | 495 | ❌ Loop network/health/stop/self-update outcomes and owner handoff. |

These total **23,016 lines**. Other specifically counted refusals C22–C25 total **1,108**, giving **24,124 refused lines**. `gate_rules.py` falls to 196 after C17 and `dash_check.html` to 491 after C21, so neither belongs in this largest-25 list. The table does not label the rest of the repository as domain: **104,310 lines remain unadjudicated at extraction-span precision**. Inventorying and searching them is not evidence that they can or cannot move. A different architectural lens must account for them independently; do not add this review's ranges to another lens without overlap removal.

## Totals

| Candidate | M | D | R | Approved gross retirement |
| --- | ---: | ---: | ---: | ---: |
| C01 git and simulator | 1,581 | 1,793 | 0 | 3,374 |
| C02 records | 330 | 0 | 0 | 330 |
| C03 schema and testing | 237 | 104 | 0 | 341 |
| C04 JSON documents | 121 | 17 | 0 | 138 |
| C05 JSONL/log substrate | 438 | 75 | 0 | 513 |
| C06 processes/capture | 231 | 23 | 0 | 254 |
| C07 locks | 70 | 11 | 0 | 81 |
| C08 caches | 72 | 0 | 0 | 72 |
| C09 time parsing | 73 | 0 | 0 | 73 |
| C10 formatting | 39 | 0 | 3 | 42 |
| C11 install/version facts | 41 | 7 | 0 | 48 |
| C12 sortable IDs | 61 | 0 | 0 | 61 |
| C13 shell mechanics | 66 | 4 | 0 | 70 |
| C14 provider observations | 620 | 0 | 0 | 620 |
| C15 HTTP/static | 86 | 0 | 0 | 86 |
| C16 process/golden testing | 276 | 0 | 0 | 276 |
| C17 architecture gate | 530 | 0 | 0 | 530 |
| C18 config overlay | 6 | 0 | 0 | 6 |
| C19 deadlines/backoff | 42 | 0 | 0 | 42 |
| C21 browser harness | 112 | 0 | 0 | 112 |
| **✅ total** | **5,032** | **2,034** | **3** | **7,069** |

Of the accepted retirement, **4,037 lines are under tests**: **2,257 moved** tests/fixtures/support and **1,780 deleted** simulator/support lines. The remaining **3,032** are source/development code: M 2,775, D 254, R 3. Application goldens remain consumer-owned; no generic test package imports their types. Shelf gains its own implementation/test lines, so repository-volume reduction is not ecosystem code deletion.

| Verdict inventory | Lines adjudicated | Approved retirement | % of 143,632 |
| --- | ---: | ---: | ---: |
| ✅ extract | 7,069 | 7,069 gross | 4.92% |
| ❓ vendor distribution experiment | 8,129 | 0 | 5.66% conditional |
| ❌ named domain refusals | 24,124 | 0 | 16.80% retained |
| **Adjudicated span coverage** | **39,322** | **7,069** | **27.38%** |
| Remaining without span-level verdict | 104,310 | 0 claimed | 72.62% |

The 50% target is **71,816 lines**. This accepted list falls short by **64,747**. Accepting C20 as well would retire **15,198**, still short by **56,618**. The shortfall is not justified by risk or caller count: all identified generic substrate above is recommended for extraction. It reflects this duplication lens's evidence and the large mass of app-specific tests/contracts/fixtures, plus the substantial remainder not adjudicated here. Do not manufacture 50% by moving domain goldens or counting already promoted vendor code twice.

## Top 10

Ranking uses gross lines × demonstrated application consumers, divided by ordinal **cost × risk**. Cost: 1 small adoption, 2 additive API, 3 substantial refactor. Risk: 1 presentation/dev-only, 2 cache/test fidelity, 4 persisted/worker compatibility, 8 git/process/lock authority. These are prioritization weights, not measured engineering days or failure probabilities. Prospective consumers earn no multiplier. Mechanism-specific safety contracts remain prerequisites regardless of rank.

| Rank | Candidate / concrete next package | Lines × apps | Cost / risk | Weighted leverage | First releasable result |
| --- | --- | ---: | --- | ---: | --- |
| 1 | C01 git-porcelain convergence | 3,374 × 3 | 3 / 8 | 421.8 | Discovery/error compatibility tag and a delegate read adapter; move the listed port contracts before writes. |
| 2 | C17 source-audit | 530 × 1 | 3 / 1 | 176.7 | Source measurements/ratchets plus planted synthetic tests; local app rule tables unchanged. |
| 3 | C05 jsonl-log evolution | 513 × 2 | 2 / 4 | 128.3 | Unrotated fork-safe append pool with the listed 54-line unit and 57-line real tests. |
| 4 | C14 agent-observation | 620 × 2 | 3 / 4 | 103.3 | Read-only context/usage facts on synthetic streams/SQLite; app stop/routing policies remain adapters. |
| 5 | C03 record-schema | 341 × 2 | 2 / 4 | 85.3 | Pure strict transforms/test helpers, then backend inspectors. |
| 6 | C10 timefmt formats | 42 × 2 | 1 / 1 | 84.0 | Exact delegate spacing/boundary fixtures and additive formatter tag. |
| 7 | C16 stream-proc.testing | 276 × 1 | 2 / 2 | 69.0 | Explicit ProcessWorld registry with guard contracts and app default fixtures injected. |
| 8 | C21 page-harness | 112 × 1 | 2 / 1 | 56.0 | Generic iframe/action/layout JS on a synthetic page; app scenarios retained. |
| 9 | C02 any-record | 330 × 2 | 3 / 4 | 55.0 | Two compatibility backends under one tagged facade; no immediate codec rewrite. |
| 10 | C04 json-document | 138 × 2 | 2 / 4 | 34.5 | Four-way reader and synthetic sealed-read contracts before transactional adoption. |

C01's third demonstrated consumer is the existing lifesim git wrapper, although its lines are excluded from the target accounting. C03 can publish transforms before C02, but generation needs its inspector boundary. C05/C14 must use C06's ownership contracts for any changed subprocess behavior. These are dependency constraints, not permission to alter land/gate/close decisions in a bulk refactor.

## Beads to file

Titles and acceptance briefs only; no tracker commands are authorized in this documentation-only run. One bead per extraction/package change; C11/C16/C19 name multiple existing package surfaces and should retain their independent release pins inside the same coordinated migration brief.

- **Converge application git adapters and simulator on git-porcelain** — C01: port the exact listed real/fake contracts, preserve unknown-read and checkout identity behavior, then delete the 1,757-line simulator after injected-port migration.
- **Promote strict versioned records with dataclass and msgspec compatibility backends** — C02: keep absent/null, mutability, scalar and wire-version behavior identical before any backend convergence.
- **Promote record schemas and strict-output contract helpers** — C03: move the listed 90 generic test/helper lines; retain all factory answer goldens as holdouts.
- **Compose atomic-io and process-lock into codec-injected JSON documents** — C04: prove four read outcomes, exact bytes/modes and rollback-safe transactions against both app adapters.
- **Evolve jsonl-log for typed pages, bounded tails, compaction and append pooling** — C05: deliver additive tagged APIs with the listed 251 test lines and preserve writer/compactor exclusion.
- **Evolve stream-proc for captured runs and recorded process identities** — C06: prove token mismatch prevents all signals and preserve both timeout/report conventions.
- **Evolve process-lock for cancellation-aware once-notified acquisition** — C07: move thread exclusion and its 36-line regression; keep holder sidecars and authority in apps; gate Windows adoption separately.
- **Promote instance-owned TTL and file-signature caches** — C08: preserve LRU, missing-file eviction, signatures and concurrent-build behavior before adopting locator/git internals.
- **Promote exact owner-time input dialects** — C09: preserve task-loop, delegate and dashboard grammars through named operations and DST/boundary fixtures.
- **Finish timefmt adoption and ship browser formatting dialects** — C10: preserve exact rounding/spacing and replace only the measured tiny table wrapper with stdlib formatting.
- **Promote numeric versions and installed-plugin path facts** — C11: preserve grammar/root compatibility and fingerprint bytes; owner pin and reexec eligibility stay local.
- **Promote the existing Crockford sortable ID implementation** — C12: preserve exact entropy/time fixtures and legacy parser acceptance; third-party replacement requires a separate passing tender.
- **Promote quote-aware shell lexical mechanics** — C13: pin both donors' malformed/quoted behavior while leaving all worker authorization predicates in their apps.
- **Promote vendor transcript, context, usage and limit observations** — C14: introduce provider DTOs and synthetic fixtures; inject roots/runners and retain lane/worker policies locally.
- **Promote constrained static serving and local HTTP transport** — C15: preserve traversal/body/header/bind behavior through route callbacks; keep public-bind decisions in task-loop.
- **Publish stream-proc process simulation and record golden helpers under testing extras** — C16: migrate the measured 276 lines with isolated registries, no-spawn guards and explicit golden update control.
- **Promote parameterized AST/ratchet auditing and planted contract scenarios** — C17: migrate the exact 530 lines while app rule values, ratchets and enforcement assertions remain local.
- **Add the observed JSON config-overlay primitive to settings-base** — C18: pin recursive merge/copy semantics; avoid a broad settings-framework rewrite or schema-policy move.
- **Expose sleep-adjusted activity tracking and capped jitter delay** — C19: preserve strict deadlines and cap-before-jitter; keep provider thresholds and factory reason/rest tables in apps.
- **Prove pinned installed-plugin dependency bootstrap before removing vendor distributions** — C20, experiment: clean/offline/plain-Python entrypoint parity and rollback provenance are required before claiming 8,129 deletion lines.
- **Promote browser iframe driving and configurable layout checks** — C21: move the 112 measured lines behind synthetic page contracts, retaining task-loop selectors, bounds, scenarios and write semantics as supplied options.
