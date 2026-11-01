# B1 — aggressive substrate extraction, second pass

The extraction plan below transfers **10,284 measured lines** to shelf ownership and removes **8,362 measured duplicate lines**: **18,646 / 143,632 = 12.98%** of the requested task-loop + delegate inventory. Another **1,488 lines of .log fixtures** move with the diagnostics package, outside that extension-filtered denominator. Within `src/taskloop` alone, **3,737 / 40,917 = 9.13%** is allocated to extraction. This is substantially broader than a source-only helper survey, but it does **not** substantiate the owner's 50% target.

Default verdict is **✅ extract**, including mixed modules that require substantial refactoring. The boundaries below retain only application decisions: who may claim/close a bead, what makes a gate authoritative, when to land, slot/lane/run routing, worker permissions and the app's wire contract. Many small helpers belong in an existing package even when moving them is not a large volume win. A backend's external vocabulary (git/bd/vendor events) is permitted in its own adapter library; task-loop's decisions about that backend are not.

These are **gross existing donor spans**, not an implemented deletion diff or a guarantee of net application shrinkage. New imports, callback adapters, dependency declarations and local compatibility wrappers must be subtracted from actual savings. M means ownership/mechanism transferred, including tests; D means an old implementation/copy proposed for deletion after replacement. No newly written shelf lines, imagined delegate tests, or future consumers are counted as donor volume. No unproven stdlib/third-party swap is booked. C26's 8,129 lines are already shelf implementations; that deployment deduplication is explicitly separate from newly capitalized code.

## Evidence, scope and line accounting

Shelf AGENTS.md, CONTEXT.md, constitution, doctrine and catalog were consulted before the donor review. Article VII permits aggressive promotion; Articles VI/VIII require reuse first and reconciliation. Shelf must never import an application. This review only reads in-tree files and writes this document. No source/test edits, git, tracker commands, runtime checks, network access or credential-file reads were performed. No beads have been filed.

The inventory command was:

```sh
rg --files src tests skills dev _delegate/src _delegate/skills \
  -g '*.py' -g '*.js' -g '*.html' -g '*.json' -g '*.md' | xargs wc -l
```

It counted **1,257 files / 143,632 physical lines**, including blanks/comments, dashboard JS/HTML, checked-in vendors, JSON fixtures/goldens and skill/dev material. The supplied delegate tree has no tests/ or dev/ tree; those missing files contribute zero. `_shelf` and `_lifesim_tools` are evidence/consumer searches, not donor denominator. CSS, JSONL, .log and other extensions are not in the owner's stated denominator. C09 separately counts all seven `tests/fixtures/checklogs/*.log` files with wc: 1,488 lines; they remain available to app integration tests as package test data or copied test artifacts.

Whole-file sizes below come from wc; **all 101 selected subranges were separately checked with `sed -n 'START,ENDp' FILE | wc -l`** (94 original ranges plus seven final mixed-module ranges). Ranges are inclusive and disjoint across candidates. The manifest below names the exact files/spans and transferred tests, rather than assigning an arbitrary percentage of a mixed module. Inventory coverage is not a claim that every one of the other 124,986 lines received a full forensic reread.

| Counted tree | Physical lines |
|---|---:|
| engine | 40,917 |
| dashboard | 5,810 |
| tests | 75,492 |
| skills | 7,431 |
| dev | 2,051 |
| delegateSource | 7,771 |
| delegateSkills | 4,160 |

## Module walk: size before boundary

The recursive directory counts were taken before selecting candidates. Every family has a decision; C-numbers below identify the measured exceptions to a refusal of wholesale export. Names in the application column are the particular rules retained, not an argument that refactoring is too risky.

| Engine family | Lines | Verdict and split |
|---|---:|---|
| root | 17 | ❌ keep app bootstrap/lazy-import selection; C26 replaces vendor distribution. |
| adapters | 3,720 | ✅ move generic git, process, log, lock, bd transport, links and file observations; ❌ keep actor identity, worker integration, check authority and slot checks. |
| contracts | 7,293 | ✅ move codec/schema/store mechanism and generic git/process/bd vocabulary; ❌ keep record schemas, worker answers, gate keys, run/slot/lane types and path names. |
| stores | 653 | ✅ move document/log backends and ticket publication; ❌ keep Ask/Checkpoint lifecycle, call recovery and app store composition. |
| cli | 1,078 | ❌ verbs and their rendering/exit meanings are app behavior; C22 removes generic dispatch from the launcher. |
| hook | 223 | ❌ session registration, pre-push admission and pre-tool authorization are app rules; shell syntax is C29, not an exported authorization policy. |
| app root | 1 | ❌ package marker has no reusable mechanism. |
| app/asks | 732 | ❌ ask intake, answer consumption, owner wake and bead parking. |
| app/checks | 1,786 | ❌ receipt authority, producer dependencies, lane/resource allocation and gate success; execution/diagnostic mechanisms go to C07/C09/C20/C21/C27. |
| app/doctor | 77 | ❌ profile checks; generic artifact verification is C17. |
| app/land | 2,837 | ❌ commit/rebase/push/cleanup decisions and land/gate ordering; all underlying git primitives are C01. |
| app/launch | 1,247 | ✅ raw tail and external bd contract fake (C04/C28); ❌ factory startup, loop ownership and dashboard address/port selection. |
| app/look | 694 | ❌ shot ownership, evidence provenance and owner/judge acceptance. |
| app/loop | 1,733 | ✅ install-file fingerprint C17; ❌ bead selection, settling, pin precedence, bad-version fallback and network adoption. |
| app/plan | 945 | ❌ planner acceptance, stage cap, assumptions and send-back decisions. |
| app/prune | 119 | ❌ which completed runs/evidence may be deleted; generic row/file age mechanics are C04/C21. |
| app/reconcile | 456 | ❌ matching beads/leases/branches and deciding lost or reclaimable work. |
| app/release | 1,143 | ✅ manifest, prepared exec, resource facts and isolated execution C17/C20/C21; ❌ clone ownership, release gate, pinning and publication. |
| app/report | 604 | ❌ scorecards/reflection windows and recurring-cause filing. |
| app/review | 611 | ❌ which findings block, settle, skip or become follow-ups. |
| app/run | 6,028 | ❌ stage state, recovery, outcome/close ordering and worker contract. Generic process/clock/I/O below those seams is extracted, not the workflow. |
| app/slots | 1,017 | ❌ slot leases, ownership/reset authority and worker adoption; kernel lock/ticket mechanisms C05/C06/C07. |
| app/track | 287 | ❌ app provenance/event vocabulary and close/claim verbs. |
| app/wire | 865 | ❌ command composition, owner actions and actor-specific effects. |
| app/write | 888 | ❌ writer/review/check rounds, new-test obligations and handoff. |
| domain root | 731 | ✅ future-time input C15; ❌ brief/outcome/stuck/effect/slot rules. |
| domain/asks | 379 | ❌ question classification, recurrence and ask acceptance. |
| domain/beads | 267 | ❌ bead lint and park/reopen rules. |
| domain/checks (recursive) | 1,339 | ✅ diagnostics, bounded reporting, globs C09/C27; ❌ gate input authority, scheduling, flaky/import retry and registry lint. |
| domain/land | 41 | ❌ push-result application decisions. |
| domain/lanes | 870 | ✅ supplied-table arithmetic C16; ❌ retry reasons, owner-vs-clock wakes, lane caps/reroute/pins and durable Park state. |
| domain/look | 25 | ❌ visual-flow names. |
| domain/plan | 298 | ❌ acceptance text, stored plan and bead/brief interpretation. |
| domain/prompts | 435 | ❌ worker instructions; a template renderer is not ownership of the instructions. |
| domain/reconcile | 361 | ❌ lost/adopted work and app reconciliation facts. |
| domain/report | 354 | ❌ factory failure fingerprints and reflection policy. |
| domain/review | 740 | ❌ finding severity, skipping, settlement and follow-up routing. |
| domain/write | 23 | ❌ what counts as a test change for the writer. |

The engine family totals reconcile to 40,917 (app 22,070; domain 5,863). Dashboard's 5,810 extension-filtered lines split into generic transport/cache/tails/browser primitives (443 measured source lines) and app APIs/read models/UI. Delegate's 7,771 source lines split into 1,400 allocated substrate lines and 6,371 remaining lines: the decoder/codec/observation mechanics move, while routing, holds, lane readiness, worker access, settlement and published contract remain local. These decisions explicitly reject exporting entire app trees under a generic 'workflow engine' name.

## Releasable migration contract

Every candidate follows this order: preserve existing behavior in donor holdouts; transfer/add package contracts with no app imports; publish a namespaced shelf tag; pin that tag in the app's actual release/dependency mechanism; replace one seam; release the app; delete the obsolete implementation after parity. A new shelf working-tree copy is not adoption. The current vendoring entry points are `src/taskloop/__init__.py:10–13` and `_delegate/src/delegate/__init__.py:6–9`; tl.py's inline dependency list is `skills/task-loop/tl.py:1–5`, so adding a pyproject dependency alone does not fix deployment.

Keep land/gate/close integration tests, worker contract goldens, recovery/rollback cases and app-specific error/exit mapping local. No step may turn unreadable into empty, a stale receipt into authority, or reexec into a second close. Compatibility defects or desired safety corrections receive explicit follow-up changes and releases, never an incidental semantic change hidden inside extraction. No package may acquire app dependencies by importing its fake fixtures.

## Candidate briefs

Public interfaces below are **target surfaces**, at most six lines each. Existing APIs are named separately in reuse-first notes; proposed additions are not misrepresented as released. Tests listed in each manifest are the exact donor tests to transfer or split; synthetic records/config replace app fixtures in the shelf suite. Where no existing test span is assigned, the contract cases below must be added before adoption, and no imagined tests receive volume credit. Consumers described as prospective are opportunities, not evidence of existing use.

### C01 — ✅ extract: Git plumbing and contract fakes

**Reuse first / target.** Existing: `_shelf/packages/git-porcelain/src/git_porcelain/api.py:305–448` exposes `Repo`/`Worktree`; `real_env.py:36–83` pins checkout environment, `real_cache.py:97–116` validates memo entries, and `testing.py:61–93` provides hermetic real-git setup. Reuse `RealRepo`, `FakeRepo`, `FakeWorktree` and the shared contract suite. Missing: parity for every legacy read/error, literal-path operation, guarded ref deletion and the argv-level simulator bridge. Evolve this package; do not create another git implementation.

**Behavior.** Owns repository identity, lossless porcelain decoding, worktree operations, snapshots, ref races and matching real/fake behavior.

| Donor span | Lines | Operation |
|---|---:|---|
| `src/taskloop/adapters/git.py:1–325` | 325 | M |
| `src/taskloop/adapters/git_base.py:1–150` | 150 | M |
| `src/taskloop/adapters/git_ops.py:1–96` | 96 | M |
| `src/taskloop/adapters/gitmemo.py:1–100` | 100 | M |
| `src/taskloop/adapters/gitrepo.py:1–91` | 91 | M |
| `src/taskloop/adapters/treehash.py:1–104` | 104 | M |
| `src/taskloop/contracts/gitfacts.py:1–91` | 91 | M |
| `src/taskloop/adapters/landlock.py:34–46` | 13 | M |
| `tests/support/gitsim/diffs.py:1–142` | 142 | M |
| `tests/support/gitsim/write.py:1–245` | 245 | M |
| `tests/support/gitsim/refs.py:1–113` | 113 | M |
| `tests/support/gitsim/trees.py:1–102` | 102 | M |
| `tests/support/gitsim/ignore.py:1–74` | 74 | M |
| `tests/support/gitsim/model.py:1–276` | 276 | M |
| `tests/support/gitsim/remote.py:1–114` | 114 | M |
| `tests/support/gitsim/rebase.py:1–119` | 119 | M |
| `tests/support/gitsim/__init__.py:1–200` | 200 | M |
| `tests/support/gitsim/status.py:1–70` | 70 | M |
| `tests/support/gitsim/ctx.py:1–76` | 76 | M |
| `tests/support/gitsim/read.py:1–226` | 226 | M |
| `tests/ports/git_contract.py:1–473` | 473 | M |
| `tests/ports/git_contract_land.py:1–184` | 184 | M |
| `tests/adapters/test_git_read_failures.py:1–85` | 85 | M |
| `tests/adapters/test_git_status.py:1–25` | 25 | M |
| `tests/adapters/test_git_cleanup.py:1–42` | 42 | M |
| `tests/adapters/real/test_git_memo.py:1–162` | 162 | M |
| `tests/adapters/real/test_git_push_env.py:1–59` | 59 | M |
| `tests/adapters/test_remote_lock_key.py:1–42` | 42 | M |
| `tests/support/fakegit.py:1–101` | 101 | D |
| `tests/support/fake_slot_git.py:1–109` | 109 | D |
| `tests/support/gitq.py:1–23` | 23 | D |
| `src/taskloop/contracts/ports.py:141–374` | 234 | M |

**Volume:** 4,033 M; 233 D; 0 proved third-party replacement lines.

**Public interface**

```text
repo = RealRepo(path, env=env, identity=identity)
repo.identity(); repo.sync(); repo.worktrees()
wt = repo.worktree(path)
wt.health(); wt.snapshot(base); wt.diff(a, b)
wt.record(message, paths='own'); wt.rebase_onto(base)
# Compatibility facade maps old Git calls to these intent operations.
```

**Consumers.** Task-loop; delegate's repository observations; lifesim `_lifesim_tools/changed.py:66–100` and `check_diff_coverage.py:38–40`; shelf's existing git consumers and tests. The lifesim gate's selection rules remain in the game.

**Owning contract tests**

- Run the transferred GitContract and LandContract cases against real and fake drivers, including newline filenames and incomplete NUL records.
- A failed query remains unknown/error, never clean, no branch, or an empty remote; config redirection and reftable disable unsafe memoization.
- Check literal staging, throwaway-index snapshots, ref-lock retry, lease-protected deletion, rebase conflicts and hook rejection against real git.
- The simulator bridge must fail on unsupported argv and share the shelf fake's state, rather than becoming a second fake.

**Factory risk / cost:** 4/5: a false clean/absence or a widened pathspec can lose work or authorize land. Keep land/gate/close holdouts in the app. Cost L (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** First port the operation contracts and missing negative cases; release a git-porcelain tag. Add a compatibility facade with the old exceptions and signatures. Replace reads, then snapshots, then branch/ref writes in separate app releases. Move the 1,757-line gitsim bridge under the package's testing extra, backed by the same fake model. Remove the three old fake/helper files only after their callers use the replacement.

### C02 — ✅ extract: Typed records, schemas and golden harness

**Reuse first / target.** No shelf package currently owns this codec. `llm-wobble` (`_shelf/packages/llm-wobble/src/llm_wobble/__init__.py:295`, `parse_with_policy`) repairs per-field LLM input and is not a strict record codec. `json-match` (`.../json_match/__init__.py:39`, `dig`; public `matches`) supplies assertions, not versioned serialization. Target: new `typed-json`, using msgspec underneath and retaining a temporary dataclass bridge.

**Behavior.** Encodes strict, versioned records and tagged unions, derives contract/strict schemas, and supplies reusable wire/golden test machinery.

| Donor span | Lines | Operation |
|---|---:|---|
| `src/taskloop/contracts/wire.py:1–101` | 101 | M |
| `src/taskloop/contracts/schema.py:1–147` | 147 | M |
| `_delegate/src/delegate/contracts/codec.py:1–229` | 229 | M |
| `_delegate/src/delegate/contracts/schema.py:1–104` | 104 | M |
| `tests/contracts/test_wire.py:28–52` | 25 | M |
| `tests/contracts/test_wire.py:121–198` | 78 | M |
| `tests/contracts/test_schema.py:80–116` | 37 | M |
| `tests/contracts/test_response_format.py:19–65` | 47 | M |

**Volume:** 768 M; 0 D; 0 proved third-party replacement lines.

**Public interface**

```text
class Record: ...  # frozen, keyword-only, strict fields
load(type_or_union, data) -> T
dump(record) -> dict
schema(type_or_union, *, strict=False) -> dict
normalize(data, schema, *, omit_optional_null=False) -> object
testing.golden(path, produced, *, update=False) -> None
```

**Consumers.** Task-loop and delegate immediately; shelf packages with JSON contracts. Lifesim's typed JSON/report scripts are a prospective consumer, with no additional lines credited.

**Owning contract tests**

- Preserve field aliases, nested version omission, tags, exact missing/unknown-key failures, bool/int distinction and scalar wire hooks.
- Compare both codecs on dataclass/Struct probe records, ABSENT versus null, enums, tuples and unions.
- Pin schema required/nullable behavior and copy semantics; move generic strict-schema walkers and refusal tests with synthetic records.
- Golden update is explicit, has a caller-supplied path, and never imports the app's samples or rewrites app goldens.

**Factory risk / cost:** 2/5 with the old wire bytes held fixed; a codec or schema drift otherwise breaks recovery or changes worker answers. Cost M (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Release the existing mechanisms as a package with both input models supported. Pin and replace task-loop's wire/schema imports, then delegate's. Keep application records, answer schemas, samples and JSON goldens local. Convert delegate dataclasses only in a later release; a msgspec migration is not permission to change its wire.

### C03 — ✅ extract: Typed document and memory stores

**Reuse first / target.** Existing `atomic-io` (`_shelf/packages/atomic-io/src/atomic_io/__init__.py:28`, `atomic_write_bytes`, and public `atomic_write_json`) supplies replacement writes; `jsonl-log` supplies bytes/cursors. Neither supplies typed read outcomes, keyed documents, locked transactions or memory parity. Add `typed-json.document`/`typed-json.testing` to C02's package, rather than another JSON encoder.

**Behavior.** Owns typed document reads, atomic replacement, keyed collections, typed log pages and faithful memory backends.

| Donor span | Lines | Operation |
|---|---:|---|
| `src/taskloop/contracts/stores.py:44–160` | 117 | M |
| `src/taskloop/stores/files.py:20–38` | 19 | M |
| `src/taskloop/stores/memory.py:36–123` | 88 | M |
| `src/taskloop/stores/api.py:15–38` | 24 | M |
| `_delegate/src/delegate/contracts/stores.py:91–101` | 11 | M |
| `tests/stores/suites.py:33–59` | 27 | M |
| `tests/stores/suites.py:131–179` | 49 | M |

**Volume:** 335 M; 0 D; 0 proved third-party replacement lines.

**Public interface**

```text
Document(path, codec).read() -> Present | Absent | Torn | ForeignVersion
Document.get() -> T | None
Document.need() -> T | None
Document.write(value); Document.delete()
Documents(path_of, codec).of(key); Documents.keys()
transaction(document, lock) -> ContextManager[T]
```

**Consumers.** Task-loop's many store families; delegate state/config transactions; shelf tools persisting typed state.

**Owning contract tests**

- A file that exists but is torn or foreign stays distinguishable from a missing file; get and need retain their different contracts.
- A failed replacement leaves the old document and no temporary file; the chosen fsync and mode remain explicit.
- One suite runs against file and memory stores, including wire round trips, cursor skipping and torn tails.
- A transaction locks the full read-modify-write interval and does not publish after its body raises.

**Factory risk / cost:** 4/5: confusing absent with unreadable can overwrite owner state or restart a closed operation. Cost M (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Move generic document/log protocols and backends with a synthetic-record suite; tag. Replace one cache family first, then authoritative stores. Pass decoder, refusal mapping and lock as dependencies. Retain AskStore transitions, ledger semantics, file-family constructors and fake_stores composition in task-loop.

### C04 — ✅ extract: JSONL handles, cursors, retention and tails

**Reuse first / target.** Existing `_shelf/packages/jsonl-log/src/jsonl_log/__init__.py:84` (`JsonlLog`) and `cursor.py` (`Jsonl`, `Entry`, `read_from`, `tail`) already cover append/rotation/cursors; `expire` covers file age. Missing: a fork-aware bounded handle pool, public byte-buffer parsing, bounded reads with a progress cursor, raw text tail/follow, and predicate-based row compaction. Evolve jsonl-log, not a second log package.

**Behavior.** Consolidates append handles, typed cursor adapters, capped tail readers, raw following and age-based row retention.

| Donor span | Lines | Operation |
|---|---:|---|
| `src/taskloop/adapters/applog.py:1–91` | 91 | M |
| `src/taskloop/contracts/rotating.py:1–21` | 21 | M |
| `src/taskloop_dash/jsonl.py:1–62` | 62 | M |
| `src/taskloop_dash/tails.py:36–52` | 17 | M |
| `src/taskloop/adapters/runner.py:28–41` | 14 | M |
| `src/taskloop/app/launch/factory.py:60–71` | 12 | M |
| `_delegate/src/delegate/contracts/stores.py:118–138` | 21 | M |
| `tests/contracts/test_jsonl.py:24–146` | 123 | M |

**Volume:** 361 M; 0 D; 0 proved third-party replacement lines.

**Public interface**

```text
Log(path, codec, *, rotate_bytes, keep, handles=None)
Log.append(record) -> int
Log.read_from(offset, *, max_bytes=None, limit=None) -> Page
Log.tail(n, *, before=None) -> Page
compact(path, keep_row, *, lock) -> int
tail_lines(path, *, bytes_limit, follow=False) -> Iterator[str]
```

**Consumers.** Task-loop engine and dashboard; delegate history; shelf audit logs; game build-output readers.

**Owning contract tests**

- Move JsonlTest: multibyte byte offsets, a completed corrupt line, torn final UTF-8, truncation and backward pagination.
- After fork, exec or file replacement the correct handle is reopened; LRU closure and explicit close_all retain their behavior.
- A bounded read advances only past complete lines and does not silently skip an overlong line; a raw tail drops its cut first line.
- Row compaction and append share the same lock, preserve retained raw rows, and do not lose an append.

**Factory risk / cost:** 3/5: log loss, repeated live events, cursor stalls or inherited handles across reexec. Cost M (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Extend and tag the existing package, moving the cursor tests first. Replace dashboard reads with a decoder/predicate adapter (Beat filtering stays local). Adopt handle pooling, then typed rotation, then delegate compaction, each in its own release. Keep HISTORY_DAYS, UsageHistory selection and all retention eligibility in the app.

### C05 — ✅ extract: Cancellable process locks

**Reuse first / target.** Existing `_shelf/packages/process-lock/src/process_lock/__init__.py:104–162`, `ProcessLock.acquire(timeout, on_wait, label, meta, reentrant)` and `holder`, already use kernel flock. Missing: cancellation/check callback and exact one-time notification/sidecar compatibility. Use non-reentrant acquisition for thread exclusion; remove the extra mutex implementation after parity.

**Behavior.** Owns cancellable waits and holder observations for a process lock, with equivalent test locks.

| Donor span | Lines | Operation |
|---|---:|---|
| `src/taskloop/adapters/locks.py:23–43` | 21 | M |
| `src/taskloop/adapters/locks.py:58–100` | 43 | M |
| `src/taskloop/stores/memory.py:129–170` | 42 | M |
| `tests/adapters/test_locks_mutex.py:1–36` | 36 | M |
| `tests/stores/suites.py:188–250` | 63 | M |

**Volume:** 205 M; 0 D; 0 proved third-party replacement lines.

**Public interface**

```text
ProcessLock.acquire(path, *, timeout=None, reentrant=False,
                    check=None, on_wait=None, label=None, meta=None)
holder(path) -> Holder | None
lock.release()
# App maps Holder to LockRecord and LockHeldError to LockTimeout.
```

**Consumers.** Task-loop, delegate, lifesim `_lifesim_tools/unity_slot.py:24`; shelf process-lock users.

**Owning contract tests**

- Two threads and two processes exclude each other; an OSError or cancellation never strands the local mutex.
- Waiting notification is once where requested; timeout and cancellation keep the old timing/error mapping.
- SIGKILL releases flock; a dead holder record cannot break a live kernel-held lock.
- Dashboard holder reads do not acquire/create locks; fake and real contention contracts agree.

**Factory risk / cost:** 3/5: concurrent land or a permanent wait. There is no stale-pid takeover algorithm to move from this adapter: kernel ownership is already authoritative. Cost M (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Add cancellation/notification compatibility to process-lock and tag it. Adapt holder metadata without changing the existing .holder reader contract. Replace hold_path, then its memory counterpart. Keep resource_holders filtering, LockWhat, filenames and the land-lock key in the app.

### C06 — ✅ extract: Durable ordered tickets

**Reuse first / target.** Process-lock owns exclusion, not durable arrival tickets; its public API is cited in C05. JsonStore/atomic-io supply records/replacement, not link-if-absent sequence allocation. Target: `process-lock.queue`, reusing those mechanisms and injecting codec, payload and rank.

**Behavior.** Allocates durable monotone tickets with exclusive publication, ordered observation and dead-owner cleanup.

| Donor span | Lines | Operation |
|---|---:|---|
| `src/taskloop/stores/files.py:40–98` | 59 | M |
| `src/taskloop/stores/memory.py:173–197` | 25 | M |

**Volume:** 84 M; 0 D; 0 proved third-party replacement lines.

**Public interface**

```text
Queue(root, *, codec, alive, rank, stale_tmp_s)
Queue.take(payload, owner, *, now) -> Ticket
Queue.line() -> list[Ticket]
Queue.drop(sequence) -> None
```

**Consumers.** Task-loop slot waits immediately; lifesim Unity/editor queues are prospective; other process-lock clients.

**Owning contract tests**

- Concurrent takers publish different whole tickets with increasing sequence numbers, even after the visible queue empties.
- A crash before linking leaves only a temporary file; age cleanup does not remove a newly created ticket.
- The injected rank preserves priority then arrival; opaque payload fields never affect generic allocation.
- Real and memory queues agree on removal and dead-owner filtering.

**Factory risk / cost:** 3/5: two sessions could believe they have the same turn, or a waiter could disappear. Cost M (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Extract the file and memory allocation engines with an app-supplied Ticket codec and ranking callback. Tag; adapt FileTickets behind its old interface. Keep priority assignment, bead association and slot eligibility local. Ticket.alive currently checks PID only: adding a start-time fence is an explicit follow-up behavior change, not a silent migration.

### C07 — ✅ extract: Process capture and recorded identities

**Reuse first / target.** Existing `_shelf/packages/stream-proc/src/stream_proc/__init__.py:14–18` exports run, stop_tree, alive, proc_start, table and popen_held. Missing: capture as a result, recorded-process handles, richer stop facts, stdin-capable streaming, a sleep-adjusted activity clock and compatible process protocols. Extend stream-proc; any-proc's one-shot marked-JSON runner is a different contract.

**Behavior.** Finishes the common process facade, captured execution, PID/start fencing and activity deadlines without worker-specific outcomes.

| Donor span | Lines | Operation |
|---|---:|---|
| `src/taskloop/adapters/procs.py:1–134` | 134 | M |
| `src/taskloop/adapters/pidcheck.py:1–16` | 16 | M |
| `_delegate/src/delegate/adapters/procs.py:38–51` | 14 | M |
| `_delegate/src/delegate/adapters/procs.py:82–91` | 10 | M |
| `_delegate/src/delegate/app/watch.py:94–138` | 45 | M |
| `tests/adapters/real/test_procs.py:39–108` | 70 | M |
| `src/taskloop/contracts/ports.py:376–398` | 23 | M |
| `src/taskloop/contracts/ports.py:421–511` | 91 | M |

**Volume:** 403 M; 0 D; 0 proved third-party replacement lines.

**Public interface**

```text
capture(argv, *, cwd, env, input=None, timeout, tick=None) -> Captured
spawn(argv, *, cwd, env, stdin=None) -> Process
ProcessIdentity(pid, start).alive() -> bool
stop(identity_or_process, *, grace) -> StopReport
ActivityClock(first_s, idle_s, *, clock, suspend_gap_s)
ActivityClock.touch(); ActivityClock.poll() -> Deadline | None
```

**Consumers.** Task-loop and delegate; lifesim parallel test/editor tools; any-proc and other shelf process users.

**Owning contract tests**

- Move the capture/TERM-during-spawn scenarios: both streams drain, timeout kills detached descendants, signal replay leaves no orphan.
- A reused PID with another start token is never treated as the recorded child; missing process-table information remains unknown.
- Exercise stdin backpressure, torn output, signal exit mapping, ticker cancellation and exception teardown.
- Fake-clock suspension does not count as silence; terminal deadline state is sticky and deadline numbers are caller inputs.

**Factory risk / cost:** 5/5: an incorrect fence or stop can kill a different process or leave an unowned worker. `table() -> None` must not become an authoritative empty table. Cost L (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Add the missing primitives and generic protocols to stream-proc; release a tag. Move capture behind the old return-code adapter, then recorded handles, then delegate's raw Orphan/run_capture. Move the Watchdog clock body with numeric thresholds supplied by delegate. Keep WorkerEnd construction, launch access flags, per-CLI limits, Turn.apply, the outcome ladder and history flush local.

### C08 — ✅ extract: Process simulation and fake clocks

**Reuse first / target.** `git-porcelain.testing` already owns real/fake git; do not re-extract it here. `_shelf/packages/blueprint/src/blueprint/testing.py:17` has `Repo.create`/`fake_tool` for executable fixtures, but not an in-process subprocess guard. Target: `stream-proc.testing` plus its testing extra; expose a small scripted-process world.

**Behavior.** Provides simulated process results, virtual durations, spawn/fork guards, call observation and an explicit fake clock.

| Donor span | Lines | Operation |
|---|---:|---|
| `tests/support/procsim.py:1–125` | 125 | M |
| `tests/support/procsim.py:128–249` | 122 | M |
| `tests/support/fake_clock.py:1–16` | 16 | M |
| `tests/rules/test_procsim.py:1–71` | 71 | M |
| `tests/rules/real/test_procsim.py:1–18` | 18 | M |

**Volume:** 352 M; 0 D; 0 proved third-party replacement lines.

**Public interface**

```text
world = ProcessWorld(guard_real=True, clock=FakeClock())
world.register(argv, fn, *, prefix=False)
with world.installed(): ...
world.calls; world.assert_activity(required=False)
FakeClock.advance(seconds)
```

**Consumers.** Task-loop logic tests; delegate and lifesim process tests after adoption; shelf stream-proc/any-proc contract suites.

**Owning contract tests**

- Transfer the fake-through-stream, subprocess capture, env prefix, timeout and real-spawn rejection tests.
- A swallowed spawn assertion still fails teardown; a real-marked test must perform the requested real activity.
- Uninstall restores subprocess, fork, socket and which patches after a failing test; nested worlds do not leak registrations.
- Virtual blocking stops through a stop flag and never waits indefinitely for an unowned fake.

**Factory risk / cost:** 2/5: a permissive fake can make a broken factory appear green. Cost M (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Promote the world/clock with no taskloop imports and tag it. Keep the two-line tl-nobd registration local (explicitly excluded from the manifest). Parameterize app defaults instead of importing the engine's marker checks. Replace test setup once, retaining app test-kind and time-limit rules in conftest.

### C09 — ✅ extract: Build diagnostics and bounded reports

**Reuse first / target.** No shelf package parses build diagnostics. Timefmt only formats counts/durations (`_shelf/packages/timefmt/src/timefmt/__init__.py:28–84`); static-page-check validates asset structure. Target: new `build-output`, with caller-supplied presentation budgets and labels.

**Behavior.** Parses compiler/linter diagnostics and test summaries, and renders bounded failure reports while preserving useful failure context.

| Donor span | Lines | Operation |
|---|---:|---|
| `src/taskloop/domain/checks/diagnostics.py:1–119` | 119 | M |
| `src/taskloop/domain/checks/trim.py:1–135` | 135 | M |
| `src/taskloop/domain/checks/diag/matchers.py:1–81` | 81 | M |
| `src/taskloop/domain/checks/matchers.py:130–168` | 39 | M |
| `src/taskloop/adapters/suiteout.py:1–43` | 43 | M |
| `tests/domain/test_diagnostics.py:1–65` | 65 | M |
| `tests/checks/test_check_trim.py:37–87` | 51 | M |
| `tests/release/test_parallel_suite.py:32–56` | 25 | M |

**Volume:** 558 M; 0 D; 0 proved third-party replacement lines. Plus 1,488 .log fixture lines: long_green.log 903, shell_exit_only.log 5, compile_error.log 62, unittest_fail.log 65, pytest_many_fail.log 254, pytest_fail.log 66, nunit_fail.log 133; all under tests/fixtures/checklogs. Those are outside the target-extension percentage.

**Public interface**

```text
report = BuildOutput.parse(text)
report.diagnostics -> tuple[Diagnostic, ...]
report.failed_tests -> tuple[str, ...]
report.render(*, bytes_limit, tail_lines, log_ref='') -> str
merge(parts) -> CombinedOutput
```

**Consumers.** Task-loop check/release output; lifesim check scripts and parallel test reports; shelf blueprint output consumers. Delegate can use it for tool-output presentation without adopting check policy.

**Owning contract tests**

- Move Roslyn/MSBuild, ruff and pyrefly format tests, duplicate suppression and ANSI handling.
- Move trim fixtures: every failing name/first assertion survives budget allocation, giant lines stay bounded and zero errors is not failure.
- Transfer pytest failure/summary merging cases, preserving order, exit codes and warning-section exclusion.
- Test UTF-8 byte caps and fallback text when no diagnostic is recognized.

**Factory risk / cost:** 2/5: an omitted failure could mislead a writer; the parser must never decide whether a gate passed. Cost M (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Release the parser/report object and move the pure tests plus seven checklogs fixtures. Adapt app prompt headers and budgets explicitly. Keep test_check_diagnostics integration, engine retry classification, build/unity scheduling and the writer's instructions local.

### C10 — ✅ extract: HTTP transport and contained assets

**Reuse first / target.** Existing `_shelf/packages/any-file/src/any_file/__init__.py:101` (`resolve_within`) and `:146` (`media_type`) supply containment/type facts. No shelf HTTP server package matches this synchronous transport; async-scope.asgi is an async lifecycle with extra uvicorn. Target: new `http-mini`, composing any-file and stdlib http.server rather than another containment implementation.

**Behavior.** Serves bounded contained static assets and dispatches JSON HTTP requests over an injected application callback, with all-or-none multi-bind.

| Donor span | Lines | Operation |
|---|---:|---|
| `src/taskloop_dash/http.py:46–87` | 42 | M |
| `src/taskloop_dash/assets.py:1–36` | 36 | M |
| `src/taskloop_dash/bind.py:96–109` | 14 | M |
| `tests/dash/test_dash_assets.py:1–61` | 61 | M |

**Volume:** 153 M; 0 D; 0 proved third-party replacement lines.

**Public interface**

```text
Assets(root, *, allowed_types, deny, max_bytes).get(path) -> Response
handler(dispatch, *, body_limit, headers, on_error) -> Handler
bind_all(addresses, port, handler) -> Servers
Response(status, body, content_type, headers=())
Servers.close()
```

**Consumers.** Task-loop dashboard first; shelf's static inspection pages; delegate/lifesim web tools only prospective.

**Owning contract tests**

- Move static-asset tests: encoded traversal, symlink escape, dot paths, backslashes, hidden/dev files, MIME and size caps.
- Partial bind failure closes every earlier socket; port zero is reused for all addresses.
- Preserve malformed body status, response headers, ETag propagation and read error isolation; explicitly test oversized bodies.
- No handler import or static lookup spawns a process.

**Factory risk / cost:** 3/5: accidentally exposing an address or serving outside the static root. Bind authorization remains app code. Cost M (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Extract transport with dispatch/version/POST callbacks and explicit asset policy; tag. Replace static_file first, then binding, then handler construction. Keep route, /api/version payload, command allowlist, Tailscale/dev-install restrictions, repos.json prerequisite and idle-exit policy local. Body-limit bug fixes require a separate change.

### C11 — ✅ extract: Observation caches

**Reuse first / target.** `_shelf/packages/llm-cache/src/llm_cache/__init__.py` exposes `LlmCache` for SQLite-backed Completion values; http-cache persists HTTP validators; async-scope.memoized owns async construction. None is a synchronous arbitrary-value TTL plus signature/LRU file cache. Target: new `observation-cache`.

**Behavior.** Caches caller-produced values by TTL or a file's observable signature with bounded LRU eviction.

| Donor span | Lines | Operation |
|---|---:|---|
| `src/taskloop_dash/cache.py:1–72` | 72 | M |

**Volume:** 72 M; 0 D; 0 proved third-party replacement lines.

**Public interface**

```text
TtlCache(clock).get(key, ttl, make) -> T
TtlCache.peek(key); TtlCache.put(key, value)
TtlCache.drop(key); TtlCache.clear()
FileCache(limit, *, signature).get(path, load, missing=None) -> T
```

**Consumers.** Task-loop dashboard; delegate's observation caching after refactor; shelf filesystem observers.

**Owning contract tests**

- Fake-clock expiry, replacement, drop and clear preserve current behavior.
- A missing file evicts its old entry; least-recently used entries are evicted deterministically.
- A failed loader is not installed as a successful value; concurrent behavior is documented and tested.

**Factory risk / cost:** 2/5: stale dashboard data. Existing code signs by mtime and size and is not single-flight; strengthen either only in an explicit semantic change. Cost S (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Move the current semantics and tests to a package, tag, replace both classes through their old names. Keep freshness durations and all interpretations of a cached result in the caller. No tests move from an existing isolated cache-test file because none was supplied.

### C12 — ✅ extract: Vendor event and transcript readers

**Reuse first / target.** `anyllm` owns completion providers, not the codex/claude/opencode tool-event stream. Its `accounting.extract_token_counts` is reusable (C13), not a stream decoder. Target: new `agent-stream`; anyllm's CLI provider may subsequently reuse it. Keep launch and worker-contract behavior outside.

**Behavior.** Decodes vendor lines into neutral tool/message/token events, reconstructs evidence and finds/exports vendor transcripts.

| Donor span | Lines | Operation |
|---|---:|---|
| `_delegate/src/delegate/adapters/harness/claude.py:21–81` | 61 | M |
| `_delegate/src/delegate/adapters/harness/claude.py:105–181` | 77 | M |
| `_delegate/src/delegate/adapters/harness/claude.py:206–210` | 5 | M |
| `_delegate/src/delegate/adapters/harness/codex.py:26–55` | 30 | M |
| `_delegate/src/delegate/adapters/harness/codex.py:80–162` | 83 | M |
| `_delegate/src/delegate/adapters/harness/codex.py:185–190` | 6 | M |
| `_delegate/src/delegate/adapters/harness/opencode.py:171–248` | 78 | M |
| `_delegate/src/delegate/adapters/harness/opencode.py:261–276` | 16 | M |
| `_delegate/src/delegate/adapters/harness/opencode.py:291–309` | 19 | M |
| `_delegate/src/delegate/contracts/events.py:9–96` | 88 | M |
| `_delegate/src/delegate/contracts/events.py:108–114` | 7 | M |

**Volume:** 470 M; 0 D; 0 proved third-party replacement lines.

**Public interface**

```text
reader = Reader(vendor, *, clock, event_factory, transcript_root)
reader.feed(line, *, stream='stdout') -> tuple[Event, ...]
reader.evidence() -> Evidence
reader.transcript(ref) -> Path | None
reader.export(ref, destination, runner) -> Path | None
```

**Consumers.** Delegate immediately; task-loop live views through delegate's event adapter; anyllm CLI provider and other agent transcript viewers. No unseen delegate tests are credited.

**Owning contract tests**

- Replay malformed/unknown vendor lines, duplicate usage message IDs and first-result handling; byte-identical app events are holdouts.
- Pair provisional OpenCode starts with completed commands exactly once; preserve retry/network observations without classifying outcomes.
- Read missing, moved and truncated transcripts without inventing a completion; export failure remains an observed failure.
- A denial is a neutral vendor fact; delegate continues to assign policy/sandbox meaning and enforce access.

**Factory risk / cost:** 4/5: wrong completion detection, usage double-counting or changed denial evidence can alter settlement. Cost L (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Freeze event replay fixtures from the current parsers, release a decoder tag, and replace one vendor at a time. Supply event factories so app event types and the Denied classification remain local. Keep launch_spec, free-model approval, login/access policy, _denials and summary/outcome decisions local; only generic event records cross ownership.

### C13 — ✅ extract: Quota observations, accounting and reset parsing

**Reuse first / target.** Existing `_shelf/packages/anyllm/src/anyllm/accounting.py:26`, `extract_token_counts`, already sums fresh/read/write input correctly. `anthropic_cost_usd` estimates model prices and cannot replace delegate's vendor-reported-or-unknown cost. Extend accounting and C12's `agent-stream.usage`; timefmt input parsing (C15) can own stated reset timestamps. No new lane or routing package.

**Behavior.** Normalizes vendor quota observations, per-call/cumulative token arithmetic and explicitly stated reset times.

| Donor span | Lines | Operation |
|---|---:|---|
| `_delegate/src/delegate/app/usage.py:41–47` | 7 | M |
| `_delegate/src/delegate/app/usage.py:85–100` | 16 | M |
| `_delegate/src/delegate/adapters/statusline.py:1–30` | 30 | M |
| `_delegate/src/delegate/adapters/harness/reset_parse.py:11–66` | 56 | M |
| `_delegate/src/delegate/domain/cost/accounting.py:14–49` | 36 | M |
| `_delegate/src/delegate/domain/cost/accounting.py:69–101` | 33 | M |

**Volume:** 178 M; 0 D; 0 proved third-party replacement lines.

**Public interface**

```text
usage = Usage.from_vendor(vendor, raw, *, observed_at)
usage.windows -> tuple[Window, ...]
usage.per_call(previous) -> Usage
usage.merge(other) -> Usage
parse_reset(text, *, now) -> Reset | None
```

**Consumers.** Delegate, task-loop cost display and anyllm CLI providers. Lifesim is not a demonstrated quota consumer.

**Owning contract tests**

- Cached input includes all documented counters; resumed cumulative totals reset rather than becoming negative.
- Unknown cost remains unknown; a missing cache-write counter is distinct from zero.
- Replay quota wrappers/bucket deduplication and percent/reset fields without selecting a lane.
- Test Retry-After seconds/HTTP date, explicit zone, local next-clock time and plausible future limits.

**Factory risk / cost:** 3/5: quota telemetry or billing display could be wrong; moving lane-out thresholds would also change routing and is forbidden. Cost M (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Release primitive normalizers and accounting, replace pure usage helpers first, then status-line payload parsing and reset prose parsing. Keep cache age, source priority, auth/logout probes, 95/98 percent thresholds, burn/pace policy, lane names and the 15/30/60 guessed-reset ladder local.

### C14 — ✅ extract: Opaque IDs and numeric versions

**Reuse first / target.** No catalog package owns opaque ULID-compatible IDs or dotted numeric ordering. `partial-time` models date precision, not identifier encoding. Promote new `opaque-id` for the 26-character identifier; put the numeric Version helper with C17's artifact-install. Neither is allowed to know beads, manifests or run folders.

**Behavior.** Creates sortable opaque IDs with injectable clock/entropy and parses exact numeric version strings.

| Donor span | Lines | Operation |
|---|---:|---|
| `src/taskloop/contracts/ids.py:31–106` | 76 | M |
| `tests/contracts/test_wire.py:202–208` | 7 | M |
| `tests/contracts/test_wire.py:218–224` | 7 | M |

**Volume:** 90 M; 0 D; 0 proved third-party replacement lines.

**Public interface**

```text
OpaqueId.new(now, *, entropy=None) -> OpaqueId
OpaqueId.parse(text) -> OpaqueId
OpaqueId.of(text) -> OpaqueId | None
OpaqueId.to_wire() -> str
NumericVersion.parse(text) -> NumericVersion
```

**Consumers.** Task-loop immediately; delegate history IDs and shelf artifact consumers prospective. No second consumer is required by shelf Article VII.

**Owning contract tests**

- Transfer opaque-ID creation/order and numeric version tests; keep bead-ID assertions in task-loop.
- Pin length, alphabet, leading-bit range, equality/hash and deterministic entropy.
- Pin numeric comparison, accepted leading zeros and rejection of non-ASCII/non-digit version components.

**Factory risk / cost:** 2/5: existing run folders become unreachable if the accepted alphabet or rendering changes. Cost S (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Tag the exact algorithms first, retain RunId/Version aliases at the app seam, then replace imports. Reject a monotonic-ID or UUID swap until compatible behavior is separately demonstrated. repo_key, loop_key, bead validation and CheckId mangling stay local.

### C15 — ✅ extract: Time input and display

**Reuse first / target.** Existing `_shelf/packages/timefmt/src/timefmt/__init__.py:28–84` exposes fmt_dur/fmt_span/fmt_until/human_count; due-schedule.schedule_is_due checks recurring jobs, not owner-entered future times. Evolve `timefmt.input` and display options to absorb the concrete parsers instead of creating another time library.

**Behavior.** Parses numeric/ISO/relative/local future times and renders timestamps or spans with caller-selected conventions.

| Donor span | Lines | Operation |
|---|---:|---|
| `src/taskloop/domain/timespec.py:1–26` | 26 | M |
| `_delegate/src/delegate/domain/time/spec.py:1–64` | 64 | M |
| `src/taskloop_dash/tails.py:10–23` | 14 | M |

**Volume:** 104 M; 0 D; 0 proved third-party replacement lines.

**Public interface**

```text
parse_time(value, *, now, milliseconds=False) -> float | None
parse_future(text, *, now) -> float
next_weekly(spec, *, now) -> float | None
fmt_local(epoch, *, zone=None) -> str
fmt_span(seconds, *, style='compact') -> str
```

**Consumers.** Task-loop asks, delegate holds/reset display, shelf schedulers; lifespan/build scripts can adopt later.

**Owning contract tests**

- Epoch seconds versus milliseconds, timezone offsets, ISO Z and malformed text are distinguished.
- Relative units and next local HH:MM/day retain boundary, past-time and DST behavior.
- Golden display probes preserve <1m and local formatting until an explicitly approved output change.

**Factory risk / cost:** 2/5: a hold, pause or owner answer could wake at the wrong time. Cost S (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Add explicit compatibility modes and tag; swap each parser independently. Pass now and timezone, never read app state. Keep which events receive a weekly/relative deadline and all hold eligibility local.

### C16 — ✅ extract: Retry arithmetic

**Reuse first / target.** Any-proc's existing Supervisor (`_shelf/packages/any-proc/src/any_proc/supervise.py:71`) already owns capped restart/backoff behavior. Add table-driven arithmetic there; due-schedule is not retry policy. No retry framework is needed for 18 donor lines.

**Behavior.** Computes remaining attempts and rest durations from supplied tables, including bounded exponential jitter.

| Donor span | Lines | Operation |
|---|---:|---|
| `src/taskloop/domain/lanes/retry.py:41–55` | 15 | M |
| `src/taskloop/domain/lanes/pauses.py:86–88` | 3 | M |

**Volume:** 18 M; 0 D; 0 proved third-party replacement lines.

**Public interface**

```text
RetryPlan(rows).left(key, used) -> bool
RetryPlan(rows).rest(key, used) -> float
backoff(base, cap, attempt, *, random, jitter=.2) -> float
```

**Consumers.** Task-loop, any-proc supervision, delegate only where it supplies its own limits.

**Owning contract tests**

- Attempt zero, exhausted attempts, an empty rest tuple and repeating the final rest are pinned.
- Cap exponential growth before jitter, clamp negative/huge attempts and test random endpoints.
- Caller-supplied action names are opaque and no default reason table is imported.

**Factory risk / cost:** 2/5: timing drift or an extra retry changes load on the factory. Cost S (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Release arithmetic under a tag, adapt RetryPlan construction with existing rows, then replace delay(). Keep ROWS, TABLE, unknown-reason owner wake, reroute/ask/fault actions and Park attempt history local.

### C17 — ✅ extract: Artifact manifests and exec

**Reuse first / target.** `dir-trust` exposes a TrustStore/content digest but owns grants for changed folders, not a release manifest; atomic-io owns replacement writes; stream-proc owns process lifecycle. Target: new `artifact-install` for manifest/fingerprint/numeric-version operations, with exec delegated to stream-proc and caller-supplied before_exec. Do not move install selection policy.

**Behavior.** Builds/verifies content manifests, fingerprints selected install files and performs a prepared exec handover.

| Donor span | Lines | Operation |
|---|---:|---|
| `src/taskloop/app/release/manifest.py:1–38` | 38 | M |
| `src/taskloop/app/loop/versions.py:31–42` | 12 | M |
| `src/taskloop/app/release/reexec.py:72–76` | 5 | M |
| `tests/release/test_manifest.py:21–53` | 33 | M |

**Volume:** 88 M; 0 D; 0 proved third-party replacement lines.

**Public interface**

```text
Manifest.build(root, files) -> str
Manifest.verify(root, text=None) -> tuple[Problem, ...]
fingerprint(files) -> str
exec_replace(argv, env, *, before_exec=()) -> Never
```

**Consumers.** Task-loop release/doctor; delegate and shelf plugin installers prospective. The existing factory remains the only current manifest consumer.

**Owning contract tests**

- Move manifest unit scenarios: deterministic order, self exclusion, missing file, changed byte and unlisted-file tolerance.
- Fingerprint an explicit file set and distinguish missing files from unchanged installs.
- Exec closes only supplied resources, preserves argv/env exactly and cannot accidentally run the close workflow twice.

**Factory risk / cost:** 4/5: an exec can lose recovery state, or a damaged installed copy can pass verification. Cost M (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Extract manifest first and tag; retain DoctorInstall holdouts locally. Move fingerprint after the app supplies its core-file list. Add prepared exec last. Keep owner pin precedence, bad-version rollback windows, checkpoint argv rewriting, release-clone ownership and installed_plugins interpretation local.

### C18 — ✅ extract: Bounded network facts

**Reuse first / target.** Http-fetch.fetch_bytes is an HTTP request; stream-proc is process lifecycle; neither answers deadline-bounded DNS/TCP facts without vendor usage. Target: new `network-facts`, using stdlib sockets and atomic-io.

**Behavior.** Probes a caller's host set under a total deadline and stores/views freshness-qualified connectivity observations.

| Donor span | Lines | Operation |
|---|---:|---|
| `_delegate/src/delegate/adapters/netprobe.py:1–120` | 120 | M |

**Volume:** 120 M; 0 D; 0 proved third-party replacement lines.

**Public interface**

```text
probe(hosts, *, budget_s, connect_s, resolve, connect, clock) -> Observation
record(path, observation) -> Observation
load(path) -> Observation | None
view(observation, hosts, *, now, fresh_s) -> View
looks_dropped(vendor_text) -> bool
```

**Consumers.** Delegate first; task-loop network pauses through its delegate boundary; shelf host diagnostics.

**Owning contract tests**

- Injected DNS failure, TCP refusal and IP-only success remain distinct; an unresolved thread cannot overrun the returned deadline.
- An unknown/untested host and stale cache never become a fresh authoritative down result.
- The outage since timestamp changes only when up changes; record errors do not manufacture success.

**Factory risk / cost:** 3/5: false network pauses or busy retry loops. Daemon resolver threads can outlive the budget; preserve that limit explicitly. Cost M (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Create the fake-network contract suite, tag, replace the adapter. Pass fallback hosts and cache ages from the app. Keep whether a failed connection pauses/reroutes/asks, and all vendor host selection, local.

### C19 — ✅ extract: Diff link checking

**Reuse first / target.** Existing `_shelf/packages/http-fetch/src/http_fetch/__init__.py:17–20` exposes fetch_bytes/FetchOutcome. Missing: public-address redirect guarding, HEAD-to-GET link validation and a bounded batch verdict; its async GET alone is not parity. Extend http-fetch with a sync-compatible link-check facade, retaining transport injection.

**Behavior.** Finds URLs on added diff lines and validates reachable public web links with bounded parallel checking.

| Donor span | Lines | Operation |
|---|---:|---|
| `src/taskloop/adapters/links.py:1–154` | 154 | M |
| `tests/adapters/test_links.py:1–68` | 68 | M |
| `tests/adapters/real/test_links.py:1–55` | 55 | M |

**Volume:** 277 M; 0 D; 0 proved third-party replacement lines.

**Public interface**

```text
added_links(diff, *, extensions) -> tuple[Link, ...]
check_link(url, *, timeout, transport, user_agent) -> Verdict
check_links(urls, *, deadline, workers, check) -> dict[str, Verdict]
```

**Consumers.** Task-loop research-link verification; shelf document tooling; game design-doc checks prospective.

**Owning contract tests**

- Move added-lines parsing, punctuation balancing, placeholder/private address and legacy numeric IP cases.
- Transfer HEAD rejection/GET fallback, redirects to non-public targets, invalid HTTP and timeout handling.
- A raising or late checker gets a failure/unknown verdict without blocking the batch past its return deadline.

**Factory risk / cost:** 3/5: wrong public/private classification or changed verification verdict. DNS rebinding protection is a separate improvement, not already guaranteed here. Cost M (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Port the parser and injected-check tests, tag; switch parsing, then transport. Keep the review decision to re-ask or send unverified claims to the owner local, along with the app's user-agent/default extensions.

### C20 — ✅ extract: Host memory facts

**Reuse first / target.** Existing `_shelf/packages/any-proc/src/any_proc/cpus.py:17–71` exposes host_cpus/cgroup_quota/available_cpus. Add available_memory/headroom alongside those host facts. No separate OS package is needed now.

**Behavior.** Measures usable host/container memory and computes a concurrency count from explicit budgets.

| Donor span | Lines | Operation |
|---|---:|---|
| `src/taskloop/app/release/suite.py:51–92` | 42 | M |
| `tests/release/test_cgroup_memory.py:1–53` | 53 | M |
| `tests/release/test_parallel_suite.py:60–69` | 10 | M |

**Volume:** 105 M; 0 D; 0 proved third-party replacement lines.

**Public interface**

```text
available_memory(*, proc_root, cgroup_root, sysconf) -> int | None
workers(*, cpus, memory_bytes, budget_bytes) -> int
```

**Consumers.** Task-loop release suite; lifesim `_lifesim_tools/run_tests_parallel.py:33`; shelf any-proc/blueprint.

**Owning contract tests**

- Move cgroup tests: numeric max-current, unlimited max, root cgroup, missing/garbage inputs and usage above limit.
- Host and cgroup constraints take the minimum; unknown remains unknown.
- Worker count is never below one and uses a caller budget, not task-loop's 2048 MB constant.

**Factory risk / cost:** 2/5: too many workers can exhaust memory during the production gate. Cost S (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Tag the host facts with injected roots, then replace suite reads and the arithmetic. Keep the factory's worker budget, environment override and refusal-before-suite rule local. Do not silently change cpu_count to affinity/quota-aware count in the same adoption.

### C21 — ✅ extract: Isolated suite execution

**Reuse first / target.** Blueprint's runner executes configuration checkpoints, not this parallel-then-serial pytest sequence. Stream-proc and process-lock already supply execution and host exclusion. Target: a small new `suite-run` engine composed from them; app selectors/commands are inputs.

**Behavior.** Runs an explicit sequence of isolated test processes with deadlines, captured parts and cleanup.

| Donor span | Lines | Operation |
|---|---:|---|
| `src/taskloop/app/release/suite.py:122–168` | 47 | M |

**Volume:** 47 M; 0 D; 0 proved third-party replacement lines.

**Public interface**

```text
run(parts, *, runner, isolated_env, deadline) -> tuple[Part, ...]
Part(argv, cwd, name, *, acceptable_exits=(0,))
clean_expired(paths, *, now, max_age, remove) -> tuple[Path, ...]
```

**Consumers.** Task-loop release/dev suite; shelf test runners; lifesim parallel helper as a later adapter.

**Owning contract tests**

- Parallel completion occurs before the serial part starts; one red part keeps the combined result red.
- Timeout/interrupt kills descendants, returns captured text and removes only owned temporary directories.
- An empty serial group is acceptable only when its part explicitly allows exit 5; an empty main suite is not.

**Factory risk / cost:** 4/5: a gate could pass without running required tests, or serial tests could overlap. Cost M (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Extract execution with argv/exit policy supplied by the app; tag and replace run_parts through its current seam. Preserve existing release integration tests locally. Keep just-check ordering, serial selector, uv sync, suite cache keys and release authorization local.

### C22 — ✅ extract: CLI dispatch

**Reuse first / target.** Existing `_shelf/packages/verb-cli/src/verb_cli/__init__.py` exposes analyze/add_flags/collect_kwargs over annotated signatures. It lacks a minimal lazy-call dispatch adapter. Evolve verb-cli rather than exporting task-loop's verbs or a second argparse facade.

**Behavior.** Turns lazy function references and selected argparse attributes into a callable dispatch entry.

| Donor span | Lines | Operation |
|---|---:|---|
| `skills/task-loop/tl.py:312–331` | 20 | M |

**Volume:** 20 M; 0 D; 0 proved third-party replacement lines.

**Public interface**

```text
lazy(module, name) -> Handler
from_namespace(fn, *attributes) -> Handler
```

**Consumers.** Task-loop launcher now; delegate/shelf CLI dispatch prospective.

**Owning contract tests**

- Import happens at dispatch, not parser construction; return values and raised exceptions propagate.
- Attribute order matches the function call, and missing fields produce a deterministic caller error.
- Help text, aliases and exit behavior stay identical through app holdouts.

**Factory risk / cost:** 2/5: command startup or argument routing could break. Cost S (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Add and tag two dispatch helpers; replace only the 20 measured lines. Keep command names, all parser declarations, Ctx, handler tables and delegate's exit-0 bad_request mapping local. Deriving all flags from signatures is an uncredited later redesign.

### C23 — ✅ extract: Configuration locations and overlay loading

**Reuse first / target.** Existing `_shelf/packages/app-dirs/src/app_dirs/__init__.py:36–57` exposes config_dir/state_dir/cache_dir/plugin_data_dir. Missing: installed-plugin path decoding and legacy fallback compatibility. `_shelf/packages/settings-base/src/settings_base/__init__.py:27–37` exports resolve_env_refs/resolve_config_path/SecretStrippingYamlSource, but not pure JSON overlay/retired-key traversal. Evolve those packages.

**Behavior.** Resolves generic app/plugin roots and applies caller-declared configuration overlays and retired/renamed-key diagnostics.

| Donor span | Lines | Operation |
|---|---:|---|
| `src/taskloop/contracts/paths.py:10–12` | 3 | M |
| `src/taskloop/adapters/ident.py:14–19` | 6 | M |
| `_delegate/src/delegate/app/env.py:33–41` | 9 | M |
| `_delegate/src/delegate/app/env.py:57–63` | 7 | M |
| `src/taskloop/contracts/config.py:279–320` | 42 | M |

**Volume:** 67 M; 0 D; 0 proved third-party replacement lines.

**Public interface**

```text
config_dir(app, *, env, home, compatibility=None) -> Path
installed_plugin_data(path, *, layout) -> Path | None
overlay(base, override) -> dict
inspect_keys(data, rules) -> tuple[Problem, ...]
strip_keys(data, rules) -> object
```

**Consumers.** Task-loop and delegate; shelf plugin/config consumers. Lifesim can reuse overlay mechanics if it develops matching configuration inputs.

**Owning contract tests**

- Unset, empty, relative and absolute XDG values preserve the explicitly selected compatibility contract.
- Symlink/cache layout lookalikes and checkout versus installed paths have pinned cases.
- Overlay deep-copies its base, preserves list/scalar replacement, and reports retirement once via caller-owned reporting.
- Config unknown keys, cross-lane reads, resource declarations and worker schemas remain app validation holdouts.

**Factory risk / cost:** 3/5: a new root can split state; a dropped warning/unknown key can alter execution. Cost M (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Tag location/overlay helpers first. Replace root lookup using a compatibility adapter: today's task-loop accepts a relative XDG root while app-dirs rejects it. Move recursive traversal with app rules as data. Keep the 411-line profile's schemas/defaults and graph/resource/argv validations local; pydantic-settings is not a reason to export those policies.

### C24 — ✅ extract: Browser formatting and UI primitives

**Reuse first / target.** Timefmt already owns duration/count semantics (C15). `_shelf/packages/html-fragment/src/html_fragment/__init__.py:44,65` offers Python to_text/to_markdown, not browser-safe Markdown output or dialog lifecycle. No catalog package owns these browser widgets. Target: new `static-ui`, consuming a timefmt browser module where suitable; keep a compatible formatter mode for the dashboard.

**Behavior.** Provides neutral browser formatting, escaped small Markdown rendering and controlled modal/popover/chart primitives.

| Donor span | Lines | Operation |
|---|---:|---|
| `src/taskloop_dash/static/js/format.js:9–34` | 26 | M |
| `src/taskloop_dash/static/js/format.js:47–84` | 38 | M |
| `src/taskloop_dash/static/js/ui/kit.js:7–28` | 22 | M |
| `src/taskloop_dash/static/js/ui/kit.js:44–59` | 16 | M |
| `src/taskloop_dash/static/js/ui/kit.js:66–69` | 4 | M |
| `src/taskloop_dash/static/js/ui/kit.js:124–203` | 80 | M |

**Volume:** 186 M; 0 D; 0 proved third-party replacement lines.

**Public interface**

```text
kit = createKit({html, useState, useRef, useEffect}, theme)
kit.Button; kit.Tabs; kit.Panel; kit.Meter
kit.Drawer; kit.Sheet; kit.Popover; kit.Toast
kit.Ring; kit.Spark; kit.EmptyState
format(value, options); renderSafeMarkdown(text)
```

**Consumers.** Task-loop dashboard; shelf static pages; delegate/lifesim browser tools prospective. The components gallery is an app holdout, not a second independent consumer.

**Owning contract tests**

- Escape HTML before Markdown formatting; test code/bold/list boundaries and hostile markup.
- Dialog open/focus/Esc/backdrop behavior follows caller state and cleans up effects/timers.
- Popover/toast layering and per-instance IDs do not collide; charts handle empty/flat/out-of-range values.
- Format goldens retain existing rounding, token units and local calendar-day behavior.

**Factory risk / cost:** 3/5: inaccessible or unclosable dialogs, unsafe HTML, changed counts or illegible charts. Cost M (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Extract the selected neutral spans with injected runtime/theme; tag assets with integrity. Adopt formatting, then modal lifecycle, then neutral widgets. Keep MARK, bid/project behavior, BeadCard/BeadRow, Status, Totals thresholds and Dots/loop warning policy in the app. CSS policy and app screenshots are not counted as moved.

### C25 — ✅ extract: Structural scanner machinery

**Reuse first / target.** Existing `_shelf/packages/blueprint/src/blueprint/facts.py` and `testing.py:17` own repository inspection/fixtures, but not the donor's SLOC/AST/ratchet engine. Add blueprint.scan/testing support; stdlib ast/tokenize/graphlib remain implementation dependencies.

**Behavior.** Scans Python syntax, measures definitions, detects configured structural patterns and compares measured violations with a shrinking baseline.

| Donor span | Lines | Operation |
|---|---:|---|
| `tests/rules/gate_rules.py:63–173` | 111 | M |
| `tests/rules/gate_rules.py:191–214` | 24 | M |
| `tests/rules/gate_rules.py:217–261` | 45 | M |
| `tests/rules/gate_rules.py:174–189` | 16 | M |
| `tests/rules/gate_rules.py:296–306` | 11 | M |
| `tests/rules/gate_rules.py:350–390` | 41 | M |
| `tests/rules/gate_rules.py:415–437` | 23 | M |
| `tests/rules/gate_rules.py:477–490` | 14 | M |
| `tests/rules/gate_rules.py:493–505` | 13 | M |

**Volume:** 298 M; 0 D; 0 proved third-party replacement lines.

**Public interface**

```text
scan(root, *, roots, exclusions) -> PythonTree
PythonTree.measure() -> Measurements
PythonTree.find(rule) -> tuple[Finding, ...]
ratchet(actual, baseline, *, ceiling) -> tuple[Problem, ...]
imports(tree) -> tuple[str, ...]
```

**Consumers.** Task-loop gate; delegate's analogous tooling and lifesim layer checks after adaptation; blueprint itself.

**Owning contract tests**

- Docstrings/comments, decorators, nested/async definitions and cache invalidation have source-string fixtures.
- Ratchets reject growth/new members and require removal of fixed entries; app caps are supplied values.
- Scanner finds planted mutable globals, forbidden calls/shell argv and import edges while respecting configured exclusions.
- Keep the app's real-tree assertions locally, so a broader shelf exclusion cannot hide a gate regression.

**Factory risk / cost:** 2/5: a rule could stop detecting a real violation. Never loosen a baseline during extraction. Cost M (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Move measured AST functions with synthetic fixtures, tag blueprint, then replace one rule family per release. Keep FILE_CAP/FUNC_CAP, known oversize JSON, taskloop layer/path tables, forbidden-process names and actual gate assertions local. Transfer detection machinery, not those rules.

### C26 — ✅ extract: Shelf dependency distribution

**Reuse first / target.** All code here already belongs to shelf. `dev/vendor.json:1` pins atomic-io, child-env, git-porcelain, jsonl-log, process-lock, static-page-check and stream-proc by tag/commit/hash. Delegate additionally ships app-dirs/timefmt. There is no new package to invent.

**Behavior.** Removes checked-in shelf implementation copies after replacing vendor-path bootstrapping with reproducible released dependencies.

| Donor span | Lines | Operation |
|---|---:|---|
| `_delegate/skills/delegate/_vendor/timefmt/**` (all inventoried Python files) | 97 | D |
| `_delegate/skills/delegate/_vendor/app_dirs/**` (all inventoried Python files) | 90 | D |
| `_delegate/skills/delegate/_vendor/atomic_io/**` (all inventoried Python files) | 91 | D |
| `_delegate/skills/delegate/_vendor/jsonl_log/**` (all inventoried Python files) | 425 | D |
| `_delegate/skills/delegate/_vendor/child_env/**` (all inventoried Python files) | 93 | D |
| `_delegate/skills/delegate/_vendor/stream_proc/**` (all inventoried Python files) | 799 | D |
| `_delegate/skills/delegate/_vendor/process_lock/**` (all inventoried Python files) | 237 | D |
| `skills/task-loop/_vendor/atomic_io/**` (all inventoried Python files) | 91 | D |
| `skills/task-loop/_vendor/jsonl_log/**` (all inventoried Python files) | 425 | D |
| `skills/task-loop/_vendor/child_env/**` (all inventoried Python files) | 93 | D |
| `skills/task-loop/_vendor/git_porcelain/**` (all inventoried Python files) | 4511 | D |
| `skills/task-loop/_vendor/stream_proc/**` (all inventoried Python files) | 804 | D |
| `skills/task-loop/_vendor/process_lock/**` (all inventoried Python files) | 237 | D |
| `skills/task-loop/_vendor/static_page_check/**` (all inventoried Python files) | 136 | D |

**Volume:** 0 M; 8,129 D; 0 proved third-party replacement lines.

**Public interface**

```text
# Runtime imports stay atomic_io / jsonl_log / stream_proc / ...
# App dependency declarations pin namespaced shelf tags.
# Release artifacts provide those dependencies before first launch.
# System-python hooks retain a separately proven dependency path.
```

**Consumers.** Task-loop and delegate distribution; every app consuming the same shelf artifacts.

**Owning contract tests**

- Launch fresh installed artifacts from a clean environment, including offline/cold-start behavior and plain-python hooks.
- Verify exact tags/content hashes and deterministic rebuilds; no dependency resolves to an unpinned branch.
- Run the factory's startup, dashboard, worker launch and reexec holdouts using packaged dependencies.
- Rollback to the old app release restores its dependency set without rewriting plugin caches.

**Factory risk / cost:** 5/5: import/bootstrap failure can stop the whole factory. This is repository deduplication, not 8,129 newly discovered substrate lines or a claim of smaller installed bytes. Cost L (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** First produce an installable dependency/artifact plan with parity for route.py, tl.py and hooks; cut/pin tags and build release artifacts. Test clean/offline startup before replacing sys.path bootstrap. Remove the two vendor trees only in the app release that carries the dependencies. Do not mutate any installed cache. If offline delivery cannot be proved, retain vendoring and forgo these savings.

### C27 — ✅ extract: Path matching and bounded file reads

**Reuse first / target.** Any-file already owns names, containment and media facts (C10). Path-pattern (`_shelf/packages/path-pattern/src/path_pattern/__init__.py:1–17`, resolve/reverse_match) is a placeholder language, not **/{a,b} globs. Add bounded file observations and matching to any-file, using stdlib hashing; do not change the glob language to fnmatch by assertion.

**Behavior.** Matches existing path globs and reads bounded file content/digests without importing check-cache policy.

| Donor span | Lines | Operation |
|---|---:|---|
| `src/taskloop/domain/checks/matchers.py:11–46` | 36 | M |
| `src/taskloop/adapters/check_files.py:30–43` | 14 | M |
| `src/taskloop/adapters/check_files.py:52–59` | 8 | M |

**Volume:** 58 M; 0 D; 0 proved third-party replacement lines.

**Public interface**

```text
PathPattern(pattern).matches(path) -> bool
PathPattern.alternatives() -> tuple[str, ...]
PathPattern.literal_prefix() -> str
digest(path, *, max_bytes=None) -> Digest | TooBig | Missing
read_lines(path, *, limit, errors='replace') -> tuple[str, ...]
```

**Consumers.** Task-loop input selection; lifesim changed/diff-coverage tools; shelf file walkers.

**Owning contract tests**

- ** crosses directories, * and ? do not, nested brace alternatives and literal prefixes preserve existing cases.
- Digest streams chunks and distinguishes missing from too-large; changing the app's size-only sentinel is a separate change.
- Read limits, decode errors and missing/unreadable files retain caller-selected behavior.

**Factory risk / cost:** 3/5: an incorrect match/digest could reuse a green result for changed inputs. Cost S (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Port grammar and file-read contracts, tag, replace glob_re/expand_braces/literal_prefix first. Then adopt bounded digest/read helpers with the app retaining BIG and sentinel encoding. Keep registry dependency rules and the cache-key authority local.

### C28 — ✅ extract: bd CLI transport and contract fake

**Reuse first / target.** No shelf package implements the bd JSON client. Blueprint.testing.fake_tool only scripts command output, and git-porcelain is not bd. Target: new `bd-client`, owning the external tool's argv/wire vocabulary and contract fake. This is an upstream API adapter: it does not decide when a factory bead may be claimed, landed or closed.

**Behavior.** Calls bd with explicit actor/runner, normalizes its external JSON/error variants and provides a contract-tested memory backend.

| Donor span | Lines | Operation |
|---|---:|---|
| `src/taskloop/adapters/bd.py:1–202` | 202 | M |
| `src/taskloop/adapters/bd.py:213–253` | 41 | M |
| `src/taskloop/adapters/bd.py:262–276` | 15 | M |
| `src/taskloop/contracts/bead.py:1–55` | 55 | M |
| `src/taskloop/app/launch/selftest_beads.py:1–106` | 106 | M |
| `tests/ports/beads_contract.py:1–129` | 129 | M |
| `src/taskloop/contracts/ports.py:58–139` | 82 | M |

**Volume:** 630 M; 0 D; 0 proved third-party replacement lines.

**Public interface**

```text
client = BdClient(actor, *, cwd, executable, runner, timeout)
client.query(Query) -> tuple[Issue, ...]
client.show(id) -> Issue | None
client.apply(Command) -> Result
client.at(cwd) -> BdClient
testing.MemoryClient(actor) -> BdClient
```

**Consumers.** Task-loop; shelf blueprint/bead tooling and any other bd-based app. Delegate and lifesim do not currently call bd through this package.

**Owning contract tests**

- Move BeadsContract and the memory backend; assert real/fake external behavior for claim, metadata, dependency reads and labels.
- Malformed list/show output faults the whole response; only explicit not-found/valid empty reads mean absence.
- Keep stdout JSON/stderr errors, actor/cwd/timeout and exit-0 push-rejection compatibility pinned.
- A write that fails does not become a successful typed command; the app's two-call close fence remains tested locally.

**Factory risk / cost:** 3/5: false absence or a falsely successful write can corrupt coordination. The existing guarded-close sequence is not an atomic transaction. Cost M (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Promote vendor records, typed request vocabulary, transport and the upstream-contract fake; tag. Replace read calls before writes. Keep adapters/bd.py:203–212 (the selected sync command/no-adopt policy), :254–261 (coordinator close fencing), bdcreate fillers, close guards and every land/provenance decision local. New library primitive close takes the requested command; it does not authorize it.

### C29 — ✅ extract: Restricted shell syntax

**Reuse first / target.** No shelf package provides this restricted shell-text analysis. Stdlib shlex splits words but does not identify unquoted command separators, nested shell -c wrappers, redirections or search exclusions. Any-file.secret_pattern supplies a filename fact, not shell parsing or worker authorization. Target: new `shell-inspect`, composed with shlex.

**Behavior.** Returns structural facts about the existing supported shell subset without deciding whether a worker may run it.

| Donor span | Lines | Operation |
|---|---:|---|
| `_delegate/src/delegate/domain/policy/matchers.py:13–23` | 11 | M |
| `_delegate/src/delegate/domain/policy/matchers.py:26–56` | 31 | M |
| `_delegate/src/delegate/domain/policy/matchers.py:73–137` | 65 | M |
| `_delegate/src/delegate/domain/policy/shell.py:21–26` | 6 | M |
| `_delegate/src/delegate/domain/policy/shell.py:90–94` | 5 | M |

**Volume:** 118 M; 0 D; 0 proved third-party replacement lines.

**Public interface**

```text
analyze(text, *, max_unwrap=3) -> Analysis
Analysis.commands -> tuple[tuple[str, ...], ...]
Analysis.parsed; Analysis.redirects; Analysis.substitutions
without_search_exclusions(text) -> str | None
after_assignments(words) -> tuple[str, ...]
```

**Consumers.** Delegate immediately; task-loop hook/tool inspection only where authorized by app rules; shelf command-inspection tooling prospective.

**Owning contract tests**

- Quoted/escaped pipes, semicolons, newlines, nested -lc and malformed quotes preserve current analysis.
- Loop headers, env assignments, quiet fd redirects and process/command substitutions have explicit supported/unknown cases.
- Search exclusion removal preserves quote-spliced paths and never removes an actually selected path.
- Delegate holdouts preserve read/write/secret denial outcomes; this parser is not promoted as a complete shell security boundary.

**Factory risk / cost:** 4/5: parsing drift can change which commands delegate blocks. Cost M (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Extract syntax with its constants, tag, replace pieces/unwrap and other pure analysis functions. Keep SECRET_RE, READ_CMDS, READ_GIT, GIT_CHANGING, engine-only recipes, OWN_PIDS and worker.judge local. Unknown syntax is a fact passed to the existing app decision, not a new default allow/deny rule.

### C30 — ✅ extract: Browser contract-test harness

**Reuse first / target.** Static-page-check already exposes structural asset checks (`_shelf/packages/static-page-check/src/static_page_check/__init__.py`); it lacks browser execution helpers. Add an optional browser harness module/asset there. Reuse the existing no-build browser/runtime path; do not export the factory's dashboard scenarios.

**Behavior.** Loads an isolated iframe, intercepts writes, drives basic DOM interactions and checks caller-configured layout constraints.

| Donor span | Lines | Operation |
|---|---:|---|
| `dev/dash_check.html:10–52` | 43 | M |
| `dev/dash_check.html:55–92` | 38 | M |
| `dev/dash_check.html:95–99` | 5 | M |

**Volume:** 86 M; 0 D; 0 proved third-party replacement lines.

**Public interface**

```text
h = BrowserHarness(frame, {root, viewport, theme, readOnly})
await h.load(url); await h.click(selector, text)
h.type(selector, text)
h.audit({hiddenSelector, minTap, minText, minInput}) -> Findings
h.blockedWrites; h.failures
```

**Consumers.** Task-loop dashboard checks; shelf static pages; lifesim visual/helper pages prospective.

**Owning contract tests**

- Frame navigation gets a new document for hash-only changes; load waits for the new document.
- Read-only mode records and blocks non-GET fetches inside the frame without invoking the app.
- Interaction failures are explicit; hidden elements and configured threshold exceptions are tested.
- App phone/desktop thresholds and selectors produce the same local scenario results.

**Factory risk / cost:** 2/5: false-green visual checks or an unintended write during live inspection. Cost S (S: narrow seam; M: several callers/contracts; L: multi-release integration).

**Releasable steps.** Extract helpers with app policy supplied as data, tag the browser asset, replace the measured helper spans. Leave CLOSED, widths/font/tap thresholds, /dev/writes, scenario tables and all bead actions in dev/dash_check.html.

## ❓ Untested direct substitutions — no additional savings

The extraction decisions above are positive even when a drop-in third-party replacement is unproven. These alternatives overlap already allocated donor spans and contribute **zero additional lines**. They must earn adoption by the listed parity experiments; no package/documentation/network query was executed during this offline review.

| Alternative / measured overlap | Verdict, public call and missing proof | Consumers, factory risk and release sequence |
|---|---|---|
| msgspec schema generation; `src/taskloop/contracts/schema.py:1–147` + `_delegate/src/delegate/contracts/schema.py:1–104` = 251 | ❓ `msgspec.json.schema(Type)` can replace reflection only after comparing required fields, metadata, tags and custom scalar hooks; compare `$ref`/definition layout and strict optional-null rewriting; preserve app schema goldens. | Task-loop/delegate. Risk: invalid structured answers. Put behind C02's schema API, run equality/acceptance matrix, tag, then adopt one app. |
| python-ulid; `src/taskloop/contracts/ids.py:31–84` = 54 | ❓ `ULID.from_str(text)` / library generation must demonstrate exact alphabet rejection, timestamp/entropy injection and lexical/equality behavior; future-time and malformed-ID probes are required. | Task-loop/shelf IDs. Risk: unreadable run folders. Trial behind C14, retain alias and old data, then tag/adopt. |
| wcmatch vs fnmatch; `src/taskloop/domain/checks/matchers.py:11–46` = 36 | ❓ `wcmatch.glob.globmatch(path, pattern, flags=...)`; prove **/, nested braces and slash boundaries, prefix derivation and no unexpected path normalization. Stdlib fnmatch alone does not promise the donor language. | Task-loop/lifesim/shelf walkers. Risk: wrong check cache inputs. Compare corpus through C27 API before replacing its engine. |
| platformdirs/pydantic-settings; C23's 67 lines | ❓ `platformdirs.user_config_path(app)` and `BaseSettings(...)` need legacy XDG/macOS/plugin-layout, unknown/retired-key, override precedence and diagnostic parity tests; they cannot replace application schemas or validation rules. | Task-loop/delegate. Risk: split state or changed gate settings. Prototype behind C23, preserve old roots and holdouts, tag/adopt only on parity. |
| Web framework substitution; C10's 153 lines | ❓ a Starlette/FastAPI static/router adapter must prove identical route/error/header/body behavior, all-or-none bind and no process starts; test dev/install/Tailscale refusal in the app. | Dashboard/shelf pages. Risk: changed server exposure/startup. Retain callback API; prove and pin framework/deps before a separately released transport swap. |

The relevant owning tests are concrete in C02/C10/C14/C23/C27. Tenacity is not an accepted replacement for C16: only 18 arithmetic lines are at stake, while the app must retain its durable pause/retry tables. argparse already performs parsing; moving its per-verb declarations to a library would merely relocate app command policy. Static-page-check and timefmt have already been adopted in parts of these trees; their existing library code is counted only as C26 duplicate copies, never as a new extraction.

## ❌ Refusals and retained seams

These refusals concern **application rules**, not coupling or migration difficulty. Generic mechanisms inside the same files are assigned to accepted candidates above. A preserved seam is a callback, protocol or data object the app supplies; it is not a license for shelf to import the app.

| Rule that stays | Evidence | App-owned interface after extraction |
|---|---|---|
| Bead close/land authority and ordered effects | `src/taskloop/app/run/closer.py:1–184`, `app/land/gate.py:1–177`, `contracts/runkey.py:1–32` | Decide outcome, authorize a receipt and invoke requested primitive effects. Git/JSON/process libraries do not decide close. |
| Routing and durable owner/clock wake | `src/taskloop/domain/lanes/pauses.py:23–84,91–103`, `retry.py:29–38`; `_delegate/src/delegate/domain/routing/router.py:1–164` | Supply reason/action/rest tables, requested model/lane and wake decisions. C16 only calculates numbers. |
| Worker launch, sandbox and permission contract | `_delegate/src/delegate/domain/policy/worker.py:1–65`, `shell.py:8–18,29–87,96–109`; `adapters/harness/base.py:16–35` | Supply permission/secret/engine-only rules and launch flags. C12/C29 report syntax/vendor facts. |
| Profile semantics | `src/taskloop/contracts/config.py:88–253,322–411` | Define check/container/resource/slot schemas, cross-lane read restrictions, graph cycles and retired/renamed-key tables. C02/C23 load/traverse, not decide. |
| Configuration path vocabulary | `src/taskloop/contracts/paths.py:16–288` | ConfigDir/RunFiles/RepoDirs continue to name runs, asks, slots, receipts and app ownership. C23 chooses only generic roots. |
| Install/pin/fallback/reexec continuation | `src/taskloop/app/loop/versions.py:45–100`; `app/release/reexec.py:21–69`; `selfupdate.py:20–37` | Owner pin precedence, rollback/bad-version duration, checkpoint argv and network-pause adoption remain app decisions. |
| Retention eligibility | `src/taskloop/app/prune/runs.py:1–73`, `contracts/stores.py:191–224` | Select eligible run/evidence/usage rows and retention ages. C04 compacts/ages exactly the supplied objects. |
| Dashboard behavior, not transport | `src/taskloop_dash/http.py:28–43`, `bind.py:21–94`, `static/js/ui/kit.js:32–41,71–119` | App routes, access boundaries, bead cards/markers, lane totals, loop warnings and owner actions remain local. |
| Test kind, gate thresholds and ratchets | `tests/rules/gate_rules.py:45–59,264–282`; `tests/conftest.py:1` | Caps, allowed imports/path literals, scan exclusions, logic/real/e2e eligibility and production quality bar stay app-owned. C25 moves execution of those declarations. |

### The 25 largest remaining files, after the allocated moves

These **23,001 lines** remain because of the named domain/contract rules. The table uses residual physical lines, not original sizes where a split was assigned. A ❌ rejects wholesale export of that residual; it does not authorize deleting its tests/goldens.

| Remaining file and evidence anchor | Original → remaining | Verdict / exact reason |
|---|---:|---|
| `tests/dash/golden/closes.json:2` | 2927 → 2927 | ❌ Expected bead/ask/phase presentation after close, not generic serializer output. |
| `tests/fixtures/dash/snapshot.json:8` | 2341 → 2341 | ❌ Factory loop/run health, owner decisions and dashboard wire fields. |
| `tests/contracts/golden/records.json:10` | 1826 → 1826 | ❌ RunTrace/bead/land/ask record shapes; C02 moves codec tests, not these app contracts. |
| `_delegate/skills/delegate/contract.json:3` | 1749 → 1749 | ❌ Worker answer/stop and run-flag contract; this is explicitly app protocol. |
| `tests/fixtures/dash/mock-8b.json:16` | 1045 → 1045 | ❌ Named planner/worker phases and expected factory board scenarios. |
| `tests/loop/real/test_loop.py:1` | 915 → 915 | ❌ Ready-bead pick/run/stop and slot ownership behaviors. |
| `tests/run/test_engine_run.py:1` | 828 → 828 | ❌ Engine resume, stop, budget, recovery and run lifecycle. |
| `tests/run/test_stages.py:45` | 817 → 817 | ❌ Planner empty-plan/follow-up/noop and stage-handoff rules. |
| `tests/support/narrow_hosts.py:1` | 777 → 777 | ❌ Typed hosts/fakes of named land/gate/close slices, not a generic fake engine. |
| `tests/support/engine_case.py:38` | 765 → 765 | ❌ PLAN/WRITE/review fixtures and composition of the app engine. Generic process/git worlds move separately. |
| `tests/land/test_engine_land_1.py:1` | 752 → 752 | ❌ Land/push/rebase/conflict-fix decisions. |
| `tests/run/test_stages_visual.py:1` | 717 → 717 | ❌ Visual-stage resume counts, bead claims and owner review. |
| `tests/land/test_stages_land.py:1` | 706 → 706 | ❌ Stale receipt/slot/dead-lane/contract/follow-up authority. |
| `skills/task-loop/SKILL.md:3` | 674 → 674 | ❌ Operating instructions for claim → plan → verify → land → close. |
| `tests/run/test_engine_units.py:1` | 652 → 652 | ❌ Outcome/delegate launch/confirmation and persisted brief policy. |
| `tests/land/test_race_invariants.py:5` | 640 → 640 | ❌ No double claim/run/close and correct push/engine-lock authority. |
| `tests/contracts/samples.py:1` | 600 → 600 | ❌ Filled samples of app records; keep coverage of domain wire shapes. |
| `tests/e2e/test_release.py:1` | 570 → 570 | ❌ Release-clone, publication and factory gate ordering. |
| `src/taskloop/contracts/dash.py:21` | 562 → 562 | ❌ Columns/phases/owner actions and exact dashboard request/response contract. |
| `tests/land/test_stack.py:1` | 549 → 549 | ❌ Ordered stack delivery and each PR's recorded merge result. |
| `tests/plan/test_engine_plan.py:1` | 546 → 546 | ❌ Plan acceptance, replan and app stage construction. |
| `tests/support/dash_fixtures.py:37` | 527 → 527 | ❌ App phases, epics, causes, project ID rendering and fixture records. |
| `tests/fixtures/delegate3/skills/delegate/contract.json:3` | 525 → 525 | ❌ Frozen engine/worker compatibility contract; not a generic schema fixture. |
| `dev/dash_check.html:101` | 582 → 496 | ❌ After C30, dashboard scenarios, selectors, layout thresholds and bead/write actions remain. |
| `tests/loop/real/test_loop_more.py:1` | 495 → 495 | ❌ Network/health/stop requests and app self-update/fallback rules. |

### What the shortfall actually means

50% of the target inventory is **71,816 lines**; this plan is **53,170 gross lines short** before new app adapters are charged. The remaining 124,986 lines are enumerated by tree below. Of them, the 25 concrete refusals above account for 23,001. The other **101,985 lines are not certified unextractable**: this B1 plan assigns no additional savings without a source-span/interface/test brief. A next volume pass must examine those residuals and app-test setup, not double-count these 30 candidates or call all fixtures reusable. The large app behavioral tests and JSON contracts do not become substrate because they are long.

The necessary discriminating test for any further mixed module is a live consumer expressed solely through data/callbacks and the proposed package's own contracts, with no import or hidden knowledge of beads, slots, lanes, runs or worker authorization. If the callback is merely a proxy that invokes the whole existing app state machine, no domain lines have left. If it isolates a real generic algorithm, extract it even with one consumer. This is the boundary that keeps an aggressive refactor from laundering product policy into shelf.

## Totals

| Verdict / operation | Target-inventory lines | % of 143,632 | Meaning |
|---|---:|---:|---|
| ✅ M — transferred source/tests/mechanisms | 10,284 | 7.16% | Gross donor spans allocated to packages, not net new shelf size. |
| ✅ D — removed duplicate implementations/copies | 8,362 | 5.82% | 233 old git test helpers + 8,129 already-shelf vendor lines; gated on replacement parity. |
| ✅ R — proved stdlib/third-party replacement | 0 | 0.00% | No unverified drop-in claim. Existing stdlib calls remain implementation choices. |
| **✅ Total proposed out of the apps** | **18,646** | **12.98%** | No overlapping donor spans. |
| ❌ Explicit residual refusals (largest 25) | 23,001 | 16.01% | 0 moved/deleted; named application rules above. |
| ❓ Residual not allocated by this substrate plan | 101,985 | 71.01% | 0 booked; requires further concrete extraction briefs. |
| Supplemental ✅ diagnostics .log fixtures | 1,488 | excluded | Outside the owner's five-extension denominator; moved with C09. |

| Tree | Proposed out | Exactly remaining |
|---|---:|---:|
| engine | 3,737 | 37,180 |
| dashboard | 443 | 5,367 |
| tests | 4,831 | 70,661 |
| skills | 6,317 | 1,114 |
| dev | 86 | 1,965 |
| delegateSource | 1,400 | 6,371 |
| delegateSkills | 1,832 | 2,328 |

Source-only: task-loop engine **3,737 / 40,917 = 9.13%**; delegate **1,400 / 7,771 = 18.02%**; separate dashboard **443 / 5,810 = 7.62%**. Together **5,580 / 54,498 = 10.24%** of application source. The target-inventory numerator also includes **4,831 test/support lines**, **20 launcher lines** and **86 browser-harness lines**, plus vendor deletions. No application JSON golden/fixture or skill prose is claimed as generic. With all vendor deletion deferred, the supported proposal is **10,517 / 143,632 = 7.32%**, plus the supplemental logs.

## Top 10

Rank primarily by **gross lines out per unit factory risk**, then by cross-consumer leverage and cost. Risk is 1–5; cost S/M/L is engineering scope, not permission to refuse. N counts named adoption opportunities, not already-deployed consumers. C26 ranks for repository volume only: it adds no new reusable behavior and must pass its distribution holdouts before its deletion is booked in an implementation. Phase 2 starts from these concrete briefs/manifests, with package tags and app parity gates as specified above.

| Rank | Brief | Gross lines out | Risk | Lines / risk | N | Leverage (lines × N) | Cost |
|---:|---|---:|---:|---:|---:|---:|---|
| 1 | C26 Shelf dependency distribution | 8,129 | 5 | 1625.8 | 2 | 16,258 | L |
| 2 | C01 Git plumbing and contract fakes | 4,266 | 4 | 1066.5 | 3 | 12,798 | L |
| 3 | C02 Typed records, schemas and golden harness | 768 | 2 | 384.0 | 2 | 1,536 | M |
| 4 | C09 Build diagnostics and bounded reports | 558 | 2 | 279.0 | 3 | 1,674 | M |
| 5 | C28 bd CLI transport and contract fake | 630 | 3 | 210.0 | 2 | 1,260 | M |
| 6 | C08 Process simulation and fake clocks | 352 | 2 | 176.0 | 3 | 1,056 | M |
| 7 | C25 Structural scanner machinery | 298 | 2 | 149.0 | 3 | 894 | M |
| 8 | C04 JSONL handles, cursors, retention and tails | 361 | 3 | 120.3 | 3 | 1,083 | M |
| 9 | C12 Vendor event and transcript readers | 470 | 4 | 117.5 | 2 | 940 | L |
| 10 | C03 Typed document and memory stores | 335 | 4 | 83.8 | 2 | 670 | M |

C07's process completion is a necessary high-risk dependency of several later migrations, even though its 403 lines / risk 5 place it below the volume top ten. C05/C06 should share a lock release train; C12/C13 share vendor event fixtures; C02/C03 share one typed-json package. Sequence prerequisites before dependent adoption rather than relaxing a gate to follow rank literally.

## Beads to file

One bead per extraction below; titles and acceptance scopes are ready for the coordinator. These are filing proposals, not tracker mutations. Each requires the package's no-app-import check, contracts, a released tag and the named app holdouts; use dependency edges for shared release prerequisites.

- **C01: Converge git plumbing, simulator and contract suites on git-porcelain.** Port the exact donor manifest, close negative-read/write parity gaps and retire the 233-line old helper set.
- **C02: Promote strict records, schemas and generic golden tests to typed-json.** Support both existing record models without changing app wire goldens or worker schemas.
- **C03: Move typed document/log and memory backends into typed-json.** Preserve four read outcomes, locked transactions and file/memory contract parity.
- **C04: Finish jsonl-log handles, bounded cursors, compaction and tails.** Transfer cursor tests and keep app row-selection/retention rules explicit.
- **C05: Add cancellation and compatible holder observations to process-lock.** Replace the second wait/mutex loop only after thread/process/error parity.
- **C06: Promote durable ticket publication into process-lock.queue.** Inject payload/rank/liveness; preserve link publication and monotone arrival numbers.
- **C07: Complete stream-proc capture, identity handles and activity clocks.** Move generic protocols/tests; preserve fences, kill proofs and old app mappings.
- **C08: Promote process-world guards and fake clocks to stream-proc.testing.** Transfer fake/real guard tests and leave tl-nobd registration/test-kind rules local.
- **C09: Extract build-output diagnostics, report trimming and fixtures.** Move pure tests plus the 1,488-line checklogs corpus; preserve app prompt/gate holdouts.
- **C10: Extract synchronous HTTP transport and contained static assets.** Compose any-file; keep routes and bind authorization in the dashboard.
- **C11: Promote synchronous observation caches.** Pin current TTL/signature/concurrency semantics before replacing the dashboard classes.
- **C12: Extract vendor agent event and transcript decoders.** Replay each vendor into neutral events while preserving app denial/settlement holdouts.
- **C13: Consolidate usage accounting, quota facts and stated reset parsing.** Reuse anyllm counters and preserve unknown costs; retain all lane thresholds locally.
- **C14: Promote opaque ID and numeric-version wire scalars.** Keep current alphabet, entropy injection, ordering and app aliases; split package ownership as specified.
- **C15: Extend timefmt with compatible time input and local display.** Pin timezone, epoch-ms and future-time boundary behavior at each caller.
- **C16: Move supplied-table retry/backoff arithmetic to any-proc.** Leave reason/action/rest policy tables and durable pause state in the app.
- **C17: Promote artifact manifest/fingerprint and prepared exec primitives.** Release manifest first; keep pin/rollback/checkpoint continuation authority local.
- **C18: Extract bounded DNS/TCP network observations.** Test total deadline and unknown cache/host semantics through injected network facts.
- **C19: Extend http-fetch with public-link batch validation.** Transfer parser/transport tests and preserve review decisions as app policy.
- **C20: Extend any-proc with host/container memory facts.** Move cgroup tests; keep factory worker budget, override and refusal policy unchanged.
- **C21: Extract isolated test-sequence execution into suite-run.** Prove parallel-before-serial ordering, exit acceptance, owned cleanup and timeout teardown.
- **C22: Add lazy argparse dispatch adapters to verb-cli.** Remove only the measured generic adapter span; keep app flags and exit meanings.
- **C23: Extend app-dirs/settings-base with legacy locations and JSON overlay mechanics.** Prevent state-root changes and preserve app profile/retired-key behavior.
- **C24: Extract neutral browser formatting and controlled UI primitives.** Keep bead cards/status/threshold policy local and pin browser assets by release.
- **C25: Promote AST measurement and structural rule execution into blueprint.** Keep app rule data/ratchets local and prove the detector on planted source fixtures.
- **C26: Replace checked-in shelf vendors with reproducible released dependency artifacts.** Require clean/offline launch, hooks, reexec and rollback parity before deleting any vendor tree.
- **C27: Extend any-file with existing glob grammar and bounded observations.** Preserve path matching/cache-key semantics; do not silently substitute fnmatch or change BIG sentinels.
- **C28: Promote external bd transport/types and its upstream contract fake.** Retain selected sync policy, close fencing and all factory lifecycle decisions locally.
- **C29: Extract restricted shell syntax facts without worker authorization.** Keep forbidden-command/secret/recipe tables and malformed-command decisions in delegate.
- **C30: Extend static-page-check with the browser contract-test harness.** Extract iframe/write-interception/DOM/layout mechanics with app scenarios and thresholds supplied locally.
