# Lens D — shelf reuse, with the app substrate split out

The second pass approves **7,149 gross donor lines for extraction or replacement (4.98% of 143,632 counted lines)**. It identifies another **276 lines requiring an anyllm contract experiment** and **8,129 already-shared vendor lines removable only after solving distribution**. Even that combined ceiling is **15,554 lines, 10.83%**, before replacement adapters. It does not establish the owner's 50% target.

This is substantially broader than the first pass: move the Git simulator and its contracts, strict record machinery, typed document storage, diagnostic parsing, process-test infrastructure, cache objects, shell syntax analysis and source-analysis machinery. Mixed modules are split; caller count and production risk are migration problems, not refusal reasons. Existing shelf packages get the first opportunity to absorb the substrate. App rules remain app rules even when they are expensive.

This document is a design verdict, not a tested migration. No application, test, credential file, dependency, tracker or Git state was changed. Tests below are acceptance criteria. No program under review was executed. Reads stayed within this directory tree. The first read failed because bubblewrap could not create a namespace; its exact escalated retry succeeded. Subsequent reads used that execution permission. There was no denied escalation.

## Scope and counting

The denominator was measured with:

~~~sh
rg --files --hidden --no-ignore src tests skills dev _delegate/src _delegate/skills \
  -g '*.py' -g '*.js' -g '*.html' -g '*.json' -g '*.md' | xargs wc -l
~~~

| Counted root | Physical lines |
|---|---:|
| src, including src/taskloop_dash | 46,727 |
| tests, including fixtures and JSON goldens | 75,492 |
| skills, including task-loop's vendor copies | 7,431 |
| dev | 2,051 |
| _delegate/src | 7,771 |
| _delegate/skills, including delegate's vendor copies | 4,160 |
| **Total** | **143,632** |
| **50% target** | **71,816** |

The supplied delegate tree has no _delegate/tests or _delegate/dev directory. It does have an older delegate distribution and contract fixtures inside task-loop's tests/fixtures/delegate3; those files are counted once, as task-loop test assets. Shelf and lifesim are comparison consumers, excluded from the primary denominator. CSS, shell, C#, TOML and JSONL are outside the owner's specified extension denominator. No savings from those extensions are credited.

Counts include comments and blank lines. Whole files were measured with wc -l; inclusive spans with sed -n 'A,Bp' FILE | wc -l. Every budget below names its spans. Budgets are **gross old lines whose implementation/test ownership can leave the apps**, not predictions of net shrinkage after imports, adapters and retained holdouts. Generic test scenarios can move with neutral fixtures; app-specific assertions and fixture data stay. No fixture/golden volume is silently assigned to a package just because the package participates in decoding it.

Verdicts have two separate meanings:

- **Candidate ✅ extract:** approve the generic boundary, including an upstream refactor when necessary. This does not assert production compatibility has passed.
- **Package ✅ adopt now / ❓ shelf change first / ❌ not a fit:** whether its current public release can directly perform the job. A package mismatch does not refuse the underlying app substrate; the candidate specifies another home.
- **Candidate ❓ untested:** a named experiment must establish the proposed boundary; its lines are separate from approved movement.
- **Candidate ❌ refuse:** the named rule belongs to the app. Zero movement.

All relative file references are rooted here. In the package ledger, P means _shelf/packages; an API reference such as P/atomic-io/src/atomic_io/__init__.py:21 is a real source location. Each package's root README.md:1 and corresponding _shelf/catalog/<name>.toml:1 were also inspected. Catalog release strings are local declarations; no remote tag was queried.

## Distribution: pin the artifact that actually executes

Shelf already documents project consumption in _shelf/docs/consuming-the-shelf.md:30-39: a namespaced git tag, package subdirectory, and uv.lock's resolved commit. The rule is distributable Git sources, never a committed local path. _shelf/AGENTS.md:1 and _shelf/docs/constitution.md:1 require upward-only dependency arrows and reconciliation. These are design constraints, not authorization to modify shelf during this audit.

Task-loop already has an offline delivery mechanism:

- dev/vendor.py:1-29 describes byte-identical copies from an archived tag, with tag, commit and tree hash recorded in dev/vendor.json:1. The manifest names atomic-io-v0.2.0, child-env-v0.1.0, git-porcelain-v0.7.0, jsonl-log-v0.2.0, process-lock-v0.2.0, static-page-check-v0.1.0 and stream-proc-v0.2.2.
- src/taskloop/__init__.py:11-13 and _delegate/src/delegate/__init__.py:6-9 append their vendor directories. An already-installed same-name module can therefore win. Checking shipped bytes alone does not prove which implementation executed.
- skills/task-loop/tl.py:1-5 declares only msgspec==0.22.0. _delegate/skills/delegate/route.py:1-12 is a plain-python launcher. A pyproject dependency does not automatically reach either deployment.
- hooks/hook.py:6-9 explicitly keeps PreToolUse on plain python3 without msgspec or record imports. src/taskloop/hook/main.py:13-20 dispatches before importing the event's implementation. Preserve that boundary.

For a uv single-file entry point, the proposed explicit PEP 723 dependency is:

~~~python
# /// script
# requires-python = ">=3.15"
# dependencies = [
#   "atomic-io @ git+https://github.com/yoselabs/shelf@atomic-io-v0.2.0#subdirectory=packages/atomic-io",
# ]
# ///
~~~

Validate this recipe with the repository's pinned uv, create and ship that script's lock, and prepare the environment before activating the release. Repeat for every uv entry point; the project's uv.lock is not evidence that a script environment is locked. Test that two shelf subdirectory requirements resolve together: namespaced tags are different snapshots of one monorepo, and sibling workspace sources can conflict with a consumer's explicit pins.

**Plain python3 does not resolve PEP 723 metadata.** Retain tagged, hash-verified stdlib vendoring for the light hook. Alternatively, build a private, self-contained dependency artifact during release and make the launcher select it deterministically. That alternative must prove the lowest supported system Python can import its complete dependency closure; an app venv cannot be assumed available to a hook. Do not resolve Git, install dependencies or contact a package service on every Bash call.

Required distribution contracts:

- Clean offline installation, cold versus prepared uv cache, missing script lock, and unavailable Git/build backend have explicit outcomes before factory cutover.
- Tag resolves to the recorded commit and source hash; package imports come from the selected artifact even with an unrelated same-name package installed.
- Every sibling package and extra resolves without a local shelf checkout; unsupported hook Python fails at installation verification.
- The PreToolUse import closure stays stdlib-only, with no msgspec import or package resolver.
- Previous artifact and pins remain installable for rollback.

The packaging experiment D0 below is separate from new extraction. Vendored shelf code is already reused; deleting its app copies improves repository volume without discovering 8,129 new generic lines.

## Release protocol shared by every approved candidate

Each candidate's migration below is a sequence of independently releasable changes, governed by this protocol:

1. Characterize current outputs, error distinctions, serialized bytes and ordered side effects in consumer holdouts. Generalize transferable tests without importing taskloop or delegate into shelf.
2. Add the missing shelf surface, or promote the named new package; publish an immutable namespaced tag. Proposed tags below mean a future release, never an existing tag silently edited.
3. Adopt one operation family in one app. Pin tag, resolved commit and delivered bytes together using the current vendor mechanism until D0 passes.
4. Run the affected package contracts and app checks, including unchanged land/gate/close scenarios. Mutation comparisons run against separate test worlds; never perform a production side effect twice for comparison.
5. Release that app boundary, then the next consumer. Roll back dependency artifact and pin together. Persisted schema migrations and intentional decision changes require separate releases.

Cost is relative refactor effort: S, M or L. Risk concerns the running factory, not just the utility's complexity. “New tests” are not included in line savings.

## Candidate briefs and measured budgets

### R1 — ✅ Extract Git mechanics and its simulator; evolve git-porcelain

**Reuse first:** P/git-porcelain/src/git_porcelain/__init__.py:20-89 already exports RealRepo, RealWorktree, Repo/Worktree protocols, typed outcomes and low-level operations; its testing module supplies FakeRepo and hermetic Git helpers. Current pin: git-porcelain-v0.7.0. Do not create another Git package.

**Job:** own repository observation, subprocess/error parsing, checkout mechanics, cache invalidation and a faithful in-process Git test world.

**Exact donors:** src/taskloop/adapters/git.py:1-325 (325), git_base.py:1-150 (150), git_ops.py:1-96 (96), gitrepo.py:1-91 (91), gitmemo.py:1-100 (100), base_tree.py:1-22 (22), treehash.py:1-104 (104), and _delegate/src/delegate/adapters/git.py:8-20 (13): **901 runtime lines**. The first seven names are all under src/taskloop/adapters.

**Tests moving:** tests/ports/git_contract.py:1-473 and git_contract_land.py:1-184 (657); tests/support/gitsim/{__init__,ctx,diffs,ignore,model,read,rebase,refs,remote,status,trees,write}.py, respectively 200+76+142+74+276+226+119+113+114+70+102+245 = 1,757. Total **3,315**. Test branch names are fixtures, not land eligibility. App adapter tests and real/fake runner wrappers remain holdouts.

**Split:** task-loop keeps its Git port, SlotGitError translations, hook policy and the decision to fetch/rebase/push/delete. Delegate keeps the rule that a worker must leave HEAD and branch unchanged (_delegate/src/delegate/adapters/git.py:23-38). Shelf absorbs execution and observation below those choices. The generic simulator joins git_porcelain.testing; it must converge with the existing FakeRepo rather than leave two divergent Git models.

**Public interface, extending the existing deep objects:**

~~~python
repo = RealRepo(path, env=env)
wt = repo.worktree(path)
wt.health(); wt.snapshot(); wt.diff(base); repo.worktrees()
wt.record(...); wt.rebase_onto(...); wt.push(...)
repo.observe(query, *, required=True)  # proposed strict missing-operation seam
testing.GitWorld().install(stack)     # proposed simulator facade
~~~

**Consumers:** task-loop and delegate; lifesim's changed.py:65-106 can later use strict path observation. Shelf's own Git consumers share the richer tests.

**Contracts:**

- Permission, corrupt-object, malformed NUL record and timeout failures never turn into clean/absent; true missing refs remain distinguishable.
- Linked worktrees, packed refs, reftable bypass, config changes and external writes invalidate only sound cached observations.
- Snapshot hashing includes untracked paths while leaving the real index untouched; newline names and exact renames survive.
- Hook invocation, LFS-before-ref order, force-with-lease and expected-OID deletion match current adapters.
- Run the same generic scenarios on the binary and simulator; unsupported fake commands fail even if app code swallows the exception.

**Movement:** 901 runtime + 2,414 test/helper lines; 0 separate dead-code credit. **Cost L; risk critical:** false clean reads or changed hook/lease behavior could authorize a wrong land.

**Migration:** publish strict read/topology parity first → migrate read families → merge simulator/contract harness into testing → migrate snapshot/cache → mutation families individually, with the app's existing port mapper retained. Do not replace land orchestration with the README's illustrative land function.

### R2 — ✅ Extract strict record/JSON-schema ownership

**Reuse first:** no existing shelf package owns this capability. dom-schema is HTML extraction, llm-wobble is recovery policy, and lean-wire is presentation pruning. Use **new typed-record**, backed by msgspec where compatible; retain a compatibility codec for dataclass omission semantics until differential tests prove it removable.

**Job:** strictly encode/decode versioned, tagged values and derive their JSON Schema without owning application record definitions.

**Donors:** packages/kernel/src/tlkernel/wire.py:1-101; schema.py:1-147; _delegate/src/delegate/contracts/codec.py:1-229; schema.py:1-104: **581 runtime lines**. Tests/contracts/test_wire.py:121-199 (79) and tests/contracts/test_schema.py:83-116 (34) supply **113 test lines**, re-expressed over neutral record fixtures. **694 total**. The app's complete-record coverage tests, samples and JSON goldens stay.

**Public interface:**

~~~python
record(...); mutable(...)
Codec[T](type_, *, version=None, tag="kind")
codec.load(data); codec.dump(value)
schema_of(type_) -> dict
strict(schema); unstrict(data, schema); prune(data, schema)
~~~

**Consumers:** task-loop and delegate; schema-facing shelf packages can consume the neutral generator later.

**Contracts:**

- Unknown/missing keys, bool versus int, numeric coercion, aliases and nested error paths retain each donor's accepted/refused inputs.
- Top-level versions, nested version omission, union tags, ABSENT versus null and set ordering round-trip unchanged.
- Strict-schema transformations are non-mutating and preserve required/nullable/enum behavior, including existing limitations until separately fixed.
- Differential tests pin actual wire bytes and both apps' existing schemas; do not silently replace delegate's integer-preserving float behavior with msgspec coercion.

**Movement:** 581 + 113; consolidation savings are included once, not added again as duplicate deletion. **Cost M; risk high:** invalid schemas or changed omission can stop every worker response.

**Migration:** tag schema transforms → adopt shared strict walker → introduce codec facade/re-exports → migrate types without moving app schemas → remove redundant codec paths only after parity.

### R3 — ✅ Extract typed document stores and keyed document sets

**Reuse first:** atomic-io supplies atomic replacement, process-lock supplies exclusion; neither owns typed read outcomes or locked update transactions. Extend **typed-record.storage**, composing both.

**Job:** give a typed file four explicit read outcomes and serialize read/modify/write under one lock.

**Donors:** packages/kernel/src/tlkernel/stores.py:44-120 (77); src/taskloop/stores/files.py:20-37 (18); _delegate/src/delegate/contracts/stores.py:91-102 (12). Tests/stores/suites.py:33-60 (28), replacing LoopState/Rest fixtures with neutral records. **107 runtime + 28 test = 135**.

**Public interface:**

~~~python
Document[T](path, codec, *, lock=None, encode_text=None)
doc.read() -> Present[T] | Absent | Torn | ForeignVersion
doc.write(value); doc.delete()
with doc.transaction() as value: ...
Documents(path_of, codec).of(key); Documents.keys()
~~~

**Consumers:** both apps; shelf frontmatter remains a distinct comment-preserving document capability.

**Contracts:**

- Missing, unreadable, torn and foreign-version files stay distinct; strict versus lossy read is the caller's choice.
- Concurrent update holds exclusion across load and replace, and a raising update never commits.
- Atomic write bytes/modes and key listing match existing stores; hidden/temp entries remain excluded.
- Delegate's retired-key handling and empty-state fallback remain above the storage layer.

**Risk high; cost M:** lost updates or foreign state interpreted as fresh could repeat work. **Migration:** R2 codec → storage tag → task-loop cache document → delegate transaction primitive → durable authoritative documents last. Ask lifecycle and first-answer-wins remain in AskStore.

### R4 — ✅ Extract the complete JSONL reader/writer substrate

**Reuse first:** jsonl-log-v0.2.0 already supplies Jsonl, JsonlLog, append_line, read_from and tail (P/jsonl-log/src/jsonl_log/__init__.py:211-228). Evolve it instead of inventing a log store.

**Job:** own complete-line cursor reads, bounded tails, typed pages, append descriptor pooling and predicate compaction.

**Donors:** packages/kernel/src/tlkernel/rotating.py:1-21 (21); adapters/applog.py:1-91 (91); contracts/stores.py:122-167 (46), :206-224 (19); src/taskloop_dash/jsonl.py:1-62 (62); tails.py:36-52 (17); _delegate/src/delegate/contracts/stores.py:118-135 (18), :40-46 (7): **281 runtime lines**.

**Tests moving:** tests/contracts/test_jsonl.py:24-144 (121), tests/contracts/test_rotation.py:15-34 (20), tests/stores/suites.py:131-186 (56): **197**, after neutralizing record fixtures. App family/path assertions in the remainder stay. **478 total**.

**Public interface:**

~~~python
Reader(path, decode, *, max_bytes=None).read_from(cursor, limit=None) -> Page[T]
Reader.tail(n, before=None); parse_bytes(data, decode, offset=0)
AppendPool(max_open=16).append(path, complete_bytes)
AppendPool.close(path); AppendPool.close_all()
compact(path, decode, *, keep, lock) -> int
tail_lines(path, *, max_bytes, partial="current") -> list[str]
~~~

**Consumers:** task-loop, dashboard and delegate (two apps, three components). Shelf's existing JSONL consumers share the evolution.

**Contracts:**

- UTF-8 byte offsets, skipped complete records, torn final records and truncate/replacement reset agree between real and fake stores.
- A dashboard poll respects its 1 MiB budget; a huge unterminated record has a specified outcome rather than unbounded growth.
- Pool ownership changes after fork; descriptors are close-on-exec, inode/device replacement reopens, and eviction/close are deterministic.
- Append versus compaction shares one lock; retained rows preserve original bytes and no concurrent append disappears.
- Text tails preserve the existing replacement-decoding/partial-line behavior separately from JSON cursors.

**Split:** Beat exclusion, event codecs, row-age thresholds and history selection stay app callbacks. App stores may no longer import jsonl_log.cursor._parse privately. **Cost M; risk high:** lost logs, replayed records or leaked handles.

**Migration:** public bytes parser → bounded readers → typed pages → pooled append behind existing facade → locked compaction → remove app mechanics. Preserve rotation and fsync choices per consumer.

### R5 — ✅ Extract capture, recorded-process handles and deadline tracking

**Reuse first:** stream-proc-v0.2.2 already owns run, stop_tree, popen_held, alive, proc_start and process tables (P/stream-proc/src/stream_proc/__init__.py:19-32). any-proc's JSON-marker runner is a different protocol.

**Job:** own captured streaming runs, safe handles for recorded processes and sleep-adjusted activity deadlines.

**Donors:** src/taskloop/adapters/procs.py:1-134 (134); _delegate/src/delegate/adapters/procs.py:37-51 (15), :83-91 (9); _delegate/src/delegate/app/watch.py:94-133 (40): **198 runtime**. Move only tests/adapters/real/test_procs.py:36-108 (**73**) with neutral imports. The environment-policy tests in tests/adapters/test_procs.py and the real file's ChildEnv class stay. **271 total**.

**Public interface:**

~~~python
capture(argv, *, stdin=None, tick=None, timeout=None, ...) -> Captured
ProcessRef(pid, start, pgid=None).alive(); ProcessRef.stop(grace=...) -> StopReport
stop_tree(handle, ...) -> StopReport
ActivityDeadline(first, idle, *, clock, sleep_gap, heartbeat=None)
deadline.touch(); deadline.poll() -> str | None
~~~

**Consumers:** task-loop and delegate; lifesim's process-owning tools are later consumers, not credited demand.

**Contracts:**

- Large stdout/stderr, torn final lines, stdin EOF and callback exceptions never strand or deadlock a child.
- PID reuse cannot signal a new occupant; detached descendants are stopped and survivors reported.
- SIGTERM during spawn and exceptions during wait clean up children before unwinding.
- StopReport says which signals were actually attempted; elapsed grace is not fabricated evidence of SIGKILL.
- Deadline tests cover suspended clocks, first-event/idle boundaries and sticky expiry.

**Split:** delegate keeps Worker/WorkerEnd, Turn.apply, CLI thresholds, completion grace, tool-in-flight exemptions and GapRow creation. **Cost M; risk critical:** an orphan or wrong-PID kill can damage the factory.

**Migration:** captured result/ProcessRef tag → migrate task-loop capture → delegate orphan/capture → optional stdin and signal report → generic deadline → app watchdog adapter. No stop-reason changes hidden in the move.

### R6 — ✅ Extract cancellable locks and filesystem ticket mechanics

**Reuse first:** process-lock-v0.2.0 already covers kernel lifetime, holder records, timeout and non-reentrant mode (P/process-lock/src/process_lock/__init__.py:104). Add cancellation and a generic ticket primitive there; avoid another flock package.

**Job:** arbitrate exclusive paths and allocate visible monotone priority tickets without knowing what the resource is.

**Donors:** src/taskloop/adapters/locks.py:24-32 (9), :59-100 (42); src/taskloop/stores/files.py:39-98 (60): **111 runtime**. Tests/stores/suites.py:188-251 (64), :252-278 (27), tests/adapters/test_locks_mutex.py:1-36: **127 tests**, **238 total**.

**Public interface:**

~~~python
ProcessLock.acquire(path, *, timeout=None, reentrant=False, check=None, on_wait=None)
TicketQueue(root, *, encode, decode, alive, clock)
queue.take(priority, payload) -> Ticket
queue.live() -> list[Ticket]; queue.drop(sequence)
~~~

**Consumers:** task-loop; delegate already uses non-reentrant ProcessLock in contracts/stores.py:27-37. Other shelf lock consumers can use cancellation without acquiring app semantics.

**Contracts:**

- Cancellation and timeout races leave neither a thread mutex nor file lock held; once-only app waiting notices remain once.
- Kernel-held locks are never broken merely because a recorded PID appears stale.
- Concurrent ticket link creation yields unique increasing sequences, including after the queue empties.
- Dead-ticket and stale-temp cleanup never removes a live ticket; priority then arrival ordering is deterministic.

**Split:** paths, LAND/RESOURCE labels, resource quantities, bead attribution and admission decisions remain app policy. **Cost M; risk critical:** two factories could enter the same land or slot boundary.

**Migration:** cancellable wait tag → replace redundant mutex/poll loop → migrate ticket allocation behind FileTickets → migrate dead-ticket observation. Keep holder sidecar compatibility until every reader is upgraded.

### R7 — ✅ Promote diagnostic output as check-output

**Reuse first:** no existing package parses build/test diagnostics. any-markdown's text budgeting does not understand failure groups; timefmt does not parse output. Create **check-output**.

**Job:** parse compiler/linter findings, summarize failing test output and render a byte-budgeted diagnostic excerpt.

**Donors:** src/taskloop/domain/checks/diagnostics.py:1-119; diag/matchers.py:1-81; trim.py:1-135; matchers.py:131-168 (38); src/taskloop/adapters/suiteout.py:1-43: **416 runtime**. Tests/domain/test_diagnostics.py:1-65 and tests/checks/test_check_trim.py:1-147: **212 tests**, **628 total**.

**Public interface:**

~~~python
Output(text).diagnostics -> tuple[Diagnostic, ...]
Output(text).failures -> tuple[str, ...]
Output(text).excerpt(max_bytes, *, tail_lines=40) -> str
Output(text).summary -> str
render_diagnostics(items, *, max_bytes, log_path="") -> str
~~~

**Consumers:** task-loop; lifesim's C#/Python build tools can later consume the parser. Do not count a prospective adoption as a second live consumer.

**Contracts:**

- Roslyn/MSBuild, Ruff, Pyrefly, generic file:line:column and ANSI fixtures produce ordered deduplicated diagnostics.
- Tracebacks, zero-error summaries and warnings are distinguished as today.
- Byte limits hold for multibyte text, tiny budgets and enormous lines; failure groups and last words have fixed priority.
- Parsing never changes a check exit code or classifies a factory retry.

**Split:** failure_kind, Unity lock/import classification, gate admission and retry choices in matchers.py:47-129 stay local. **Cost M; risk medium:** a wrong excerpt hides the actionable error but must not change delivery authorization.

**Migration:** parser tag + tests → migrate diagnostic rendering → trim/suite summaries → remove local regexes. Golden prompt changes are separately reviewed, not silently accepted.

### R8 — ✅ Promote path-glob selection and hashing

**Reuse first:** path-pattern resolves brace templates, not globs; git-porcelain owns Git pathspecs, not the app's exact include dialect. Create **path-glob**, or reconcile it into a later any-file submodule after contracts exist.

**Job:** compile the existing glob language and select/hash named file digests.

**Donors:** src/taskloop/domain/checks/matchers.py:11-44 (34); inputs.py:20-57 (38): **72 runtime**, **0 existing test lines credited**. Inputs-only and gate tests remain app holdouts.

**Public interface:**

~~~python
PatternSet(include, exclude=()).matching(paths) -> list[str]
PatternSet.dead(paths) -> list[str]
PatternSet.literal_roots() -> list[str]
PatternSet.digest(path_to_digest) -> str
~~~

**Consumers:** task-loop; lifesim path grouping is a simpler separate dialect until proven equivalent.

**Contracts:**

- Star versus double-star, zero-folder double-star, question marks and nested braces match current vectors.
- Include/exclude, ordering, surrogate filenames and empty-selection digest match exactly.
- Literal-root optimization cannot prune any matching input.

**Cost S/M; risk high:** selecting too few files could reuse a false green. **Migration:** freeze vectors → tag → adopt selection → hash → pathspec optimization. ROOT_FILES, TOOLCHAIN_FILES and cache authorization remain app policy.

### R9 — ✅ Promote the synchronous HTTP/static substrate

**Reuse first:** any-file.resolve_within already provides containment (P/any-file/src/any_file/__init__.py:101). static-page-check validates assets but does not serve them. async-scope.asgi is an async lifecycle, not a synchronous handler. Build **local-http**, composing stdlib http.server and any-file where appropriate.

**Job:** serve bounded static bytes and wrap injected GET/POST callbacks without owning dashboard routes.

**Donors:** src/taskloop_dash/assets.py:1-36; http.py:23-25 (3), :50-66 (17), :73-82 (10); bind.py:96-108 (13): **79 runtime**. Tests/dash/test_dash_assets.py:1-61: **61 tests**, **140 total**.

**Public interface:**

~~~python
StaticFiles(root, *, types, deny, max_bytes).get(url_path) -> Reply | None
handler(get, post, *, max_body, error_reply, headers) -> HandlerType
bind_all(addresses, port, handler) -> Servers
with Servers: ...
~~~

**Consumers:** dashboard now; other shelf tools serving a local UI are potential consumers.

**Contracts:**

- Encoded traversal, NUL, backslash, hidden components, directory requests and symlink escapes remain refused.
- MIME allowlist, denied dev assets and byte limits stay caller-configurable.
- Bind every requested address or close every partial listener.
- JSON/body handling and errors remain byte-compatible; current body-cap behavior is characterized before any stricter rejection.

**Split:** http.py:28-44 and :68-72 keep app routes/version payload; bind.py:20-93 keeps the unauthenticated loopback/Tailscale and installed-copy rules. **Cost M; risk high:** wrong routing or containment could expose private evidence.

**Migration:** static serving first → byte-level HTTP adapter → bind lifecycle. Do not add token authentication or change bind policy as an extraction side effect.

### R10 — ✅ Promote memoized file/value objects

**Reuse first:** http-cache is an HTTP body/conditional-GET SQLite cache; llm-cache stores completions. Neither fits. Create **value-cache**, rather than distort either.

**Job:** own instance-scoped TTL values and bounded LRU parsing of unchanged files.

**Donor:** src/taskloop_dash/cache.py:1-72: **72 runtime**, **0 existing tests credited**.

**Public interface:**

~~~python
TtlCache(clock).get(key, ttl, make); peek(key); put(key, value); drop(key); clear()
FileCache(limit=500).get(path, load, missing=None)
~~~

**Consumers:** task-loop dashboard; delegate auth-cache decisions remain app policy, but can later compose the same cache.

**Contracts:**

- TTL boundary and injected clock are deterministic; failed makers do not create a successful cache entry.
- File disappearance invalidates, changed mtime/size reloads, and access updates LRU eviction.
- Concurrent readers preserve current duplicate-computation behavior; single-flight is a separate feature.

**Cost S; risk medium:** stale display facts could mislead an owner. **Migration:** add contract tests → tag → swap dashboard objects → evaluate stronger signatures separately.

### R11 — ✅ Extract browser text/formatting substrate; evolve timefmt delivery

**Reuse first:** timefmt-v0.2.0 exports fmt_dur/fmt_span/fmt_until/human_count (P/timefmt/src/timefmt/__init__.py:21). It has no browser module and its rounding differs from dashboard display. any-markdown is a Python structural reader, not a safe browser renderer.

**Job:** format browser time/count values and render the existing escaped Markdown subset.

**Donors:** src/taskloop_dash/static/js/format.js:9-35 (27), :49-84 (36): **63 JS lines**, **0 tests credited**. MARK, MARK_TONE and bid/setManyProjects remain app display policy.

**Public interface:**

~~~javascript
dur(seconds); age(epoch, now); unit(seconds); tokens(count)
clock(epoch); day(epoch, now)
esc(text); md(text)
~~~

**Targets:** a tagged browser artifact in timefmt for formatting; **new safe-inline-markdown** for the renderer. Keep this one migration budget disjoint across those two releases.

**Consumers:** dashboard; shelf static pages are prospective consumers.

**Contracts:**

- JS rounding, nulls, zero token display and day boundaries match existing strings.
- HTML metacharacters escape before Markdown replacement; hostile markup never becomes active HTML.
- Lists/headings/code/bold render the same subset, not whatever a full Markdown engine happens to permit.

**Cost S/M; risk medium:** unsafe rendering or broken phone layout. **Migration:** snapshot pure functions → publish browser artifact with tag/hash → update static imports → render subset separately. Python package installation alone cannot deliver an ES module.

### R12 — ✅ Extract time parsing and legacy display dialects

**Reuse first:** timefmt handles rendering; due-schedule handles recurrence; partial-time handles precision intervals. None supplies the apps' timestamp/future-time parser. Promote **time-spec**, composing timefmt and preserving named compatibility dialects.

**Donors:** src/taskloop/domain/timespec.py:1-26; _delegate/src/delegate/domain/time/spec.py:1-64; src/taskloop_dash/tails.py:10-19 (10): **100 runtime**, **0 tests credited**. Delegate's display functions move to timefmt; do not count them twice under R11.

**Public interface:**

~~~python
parse_timestamp(value, *, milliseconds=False) -> float | None
parse_future(text, now, *, dialect) -> float
next_weekly(spec, now) -> float | None
format_wait(seconds, *, dialect) -> str
~~~

**Consumers:** task-loop and delegate; dashboard shares timestamp reads.

**Contracts:**

- ISO zones, local-naive values, epoch milliseconds and bool/zero inputs preserve each dialect.
- Relative durations and next HH:MM/weekday boundaries are pinned around DST and equal-now cases.
- Malformation and past-time outcomes stay explicit; the current zero-relative discrepancy is not silently “fixed.”

**Cost S/M; risk medium:** an owner wake or hold can move by hours. **Migration:** characterize dialects → tag parsers → migrate timestamp reads → owner-entered waits → rendering.

### R13 — ✅ Evolve child-env and app-dirs for remaining mechanics

**Reuse first:** child-env-v0.1.0 exports scrub/scrub_current (P/child-env/src/child_env/__init__.py:70); app-dirs-v0.1.0 exports config_dir/state_dir/cache_dir/plugin_data_dir (P/app-dirs/src/app_dirs/__init__.py:36-57). Keep those owners.

**Job:** remove a virtualenv from a child environment and derive an installed plugin's data root without owning app layout.

**Donors:** src/taskloop/adapters/childenv.py:16-27 (12); packages/kernel/src/tlkernel/paths.py:10-14 (5); _delegate/src/delegate/app/env.py:33-41 (9): **26 runtime**, **0 tests credited**.

**Public interface:**

~~~python
child_env.without_venv(mapping) -> dict[str, str]
app_dirs.config_dir(app, *, env, home, create=False)
app_dirs.installed_plugin_data(path) -> Path | None
~~~

**Consumers:** task-loop and delegate.

**Contracts:**

- Remove only exact virtualenv variables/bin path; input mapping is untouched.
- Relative/empty XDG behavior is characterized against the current task-loop fallback before adopting the spec-correct shelf default.
- Installed-cache path spelling, sanitized identity and checkout refusal match delegate; no directory is created during observation.

**Cost S; risk high:** split state roots or a gate launched with the wrong tools. **Migration:** pure virtualenv operation → installed-plugin locator → root lookup with an explicit compatibility decision. Keep app allowlists, handover variables and full ConfigDir/RunFiles layouts local.

### R14 — ✅ Extract shell syntax analysis from worker policy

**Reuse first:** any-file.secret_pattern recognizes filenames, not shell execution or exclusions; no shelf shell analyzer exists. Promote **shell-inspect**, using shlex inside the same proven partial grammar. A full parser such as bashlex is an implementation experiment, not an automatic compatibility upgrade.

**Job:** expose parsed command pieces, wrapper unwrapping, exclusions and substitution/redirection observations.

**Donors:** _delegate/src/delegate/domain/policy/matchers.py:26-57 (32), :73-137 (65): **97 runtime**, **0 tests credited**. Constants necessary for these operations become package implementation data.

**Public interface:**

~~~python
Command(text).pieces() -> list[list[str]] | Unparsed
Command.unwrap(max_depth=3) -> str
Command.without_search_exclusions() -> str | Unparsed
Command.has_writes_or_substitutions() -> bool
~~~

**Consumers:** delegate; task-loop's command-lint substrate can later use syntax observations.

**Contracts:**

- Quote splicing, escaped separators, nested shell -c forms, quiet redirections and malformed text preserve current observations.
- Excluded search paths are not misreported as accessed paths.
- Loops and command substitutions have explicit supported/unknown cases; parser uncertainty never authorizes a call.

**Split:** SECRET_RE/secret_hit, READ_CMDS/READ_GIT, git_write/read_only_problem/writer_problem and worker.judge retain the actual credential, coordinator-Git and worker role rules. **Cost M; risk critical:** a syntactic false negative can weaken a worker guard.

**Migration:** differential parser corpus → tag observations → replace syntax calls beneath unchanged judge → consider a full grammar in a separate policy review.

### R15 — ✅ Promote bounded DNS/TCP observation

**Reuse first:** http-fetch performs content GETs with TLS impersonation; this is quota-free DNS/TCP diagnosis. Create **net-status**.

**Job:** observe bounded parallel host connectivity and cache those observations.

**Donor:** _delegate/src/delegate/adapters/netprobe.py:1-120: **120 runtime**, **0 tests credited**.

**Public interface:**

~~~python
probe(hosts, *, neutral, literal, budget_s, connect_s, resolve, connect, clock) -> Observation
record(path, observation); load(path)
view(observation, hosts, now, *, fresh_s) -> Status
looks_dropped(vendor_error_text) -> bool
~~~

**Consumers:** delegate; task-loop reaches this through delegate today.

**Contracts:**

- DNS failure, TCP refusal, successful literal-IP probe and hanging resolver yield distinct bounded observations.
- Unfinished daemon probes cannot mutate the returned result after its snapshot.
- Cache freshness, host subset queries and transition-since timestamps preserve current behavior.
- Error-text matching excludes model-output token-cap messages as today.

**Cost M; risk medium/high:** a false network diagnosis could park paid work. **Migration:** injected resolver contracts → tag → replace probe → cache → error-text matcher; app decides whether to wait or reroute.

### R16 — ✅ Move generic fake-process and patching infrastructure into shelf testing

**Reuse first:** stream-proc has process contracts, git-porcelain has Git fakes, and a2effect/mcp-steps have their own testing helpers. Do not create another omnibus app test framework. Add **stream_proc.testing** for process simulation and **new test-scope** only for generic rebinding/clock ownership.

**Job:** answer subprocess calls in memory and make forbidden real I/O fail even when swallowed.

**Donors, all test code:** tests/support/procsim.py:54-125 (72), :128-249 (122); fake_clock.py:1-16; rebind.py:1-26; tests/rules/test_procsim.py:1-71; tests/rules/real/test_procsim.py:1-18: **325 lines**.

**Public interface:**

~~~python
with ProcessWorld(allow_real=False) as world:
    world.answer(argv, fake, prefix=False); world.check(must_spawn=False)
world.calls; world.current_argv
FakeClock(start).now(); advance(seconds)
rebind(scope, original, replacement)
~~~

**Consumers:** task-loop; delegate and process-owning shelf packages are proposed consumers.

**Contracts:**

- subprocess and streaming adapters agree on output, env prefixes, timeout, exit and cancellation.
- A swallowed forbidden Popen/fork remains a teardown failure; real-test must-spawn enforcement works.
- Nested worlds and cleanup restore patches, including names imported while a replacement is active.
- Fakes never load factory types; app-specific fake commands/defaults register through parameters.

**Split:** the bd stub special case at procsim.py:126-127 and marker/app fixtures above :54 stay local. **Cost M; risk medium:** a permissive fake can make factory regressions pass unnoticed.

**Migration:** publish testing extra → move generic guard tests → app re-export facade → remove facade after callers migrate. Keep engine_case, narrow_hosts and fixture schemas in the apps.

### R17 — ✅ Promote release manifest verification

**Reuse first:** static-page-check.pin_problems checks a specified static asset set, not a release manifest. atomic-io can perform writes. Promote **artifact-manifest**, or grow static-page-check only if its owner accepts general artifact verification as the same concept.

**Job:** build and verify deterministic content manifests without owning the release workflow.

**Donor:** src/taskloop/app/release/manifest.py:1-38: **38 runtime**, **0 tests credited**.

**Public interface:**

~~~python
Manifest.build(root, paths, *, manifest_name="MANIFEST.sha256") -> str
Manifest.parse(text).verify(root) -> list[Problem]
~~~

**Consumers:** task-loop; delegate/plugin artifact production can adopt later.

**Contracts:**

- Sorted paths, exact bytes, missing files and absent manifest produce deterministic evidence.
- Manifest self-exclusion and extra unlisted-file treatment match current behavior.
- Generic implementation has explicit traversal/symlink rules; extraction does not silently broaden trusted input.

**Cost S; risk medium:** altered verification can bless a modified plugin. **Migration:** byte vectors → tag → build path → doctor verification. Release authorization stays local.

### R18 — ✅ Extract JSON overlay mechanics; evolve settings-base

**Reuse first:** settings-base-v0.1.0 owns pydantic YAML/env plumbing; yaml-merge preserves YAML presentation and is not JSON overlay. Extend **settings-base** with a dependency-light mapping overlay module instead of making apps adopt YAML.

**Job:** recursively overlay mappings while preserving the base object.

**Donor:** _delegate/src/delegate/app/env.py:57-62: **6 runtime**, **0 tests credited**. The small size is reported honestly.

**Public interface:**

~~~python
overlay(base: Mapping, override: Mapping | None) -> dict
~~~

**Consumers:** delegate now; task-loop may compose it only where its declared precedence permits.

**Contracts:**

- Nested dictionaries merge; lists/scalars replace; null versus missing remains distinct.
- Neither input is mutated and mutable values retain the current copy/alias behavior.
- Retired keys, profiles, unknown-key rejection and source precedence remain app-owned.

**Cost S; risk high:** changed overrides can select a different lane. **Migration:** overlay vectors → shelf tag → replace helper only. Task-loop already validates with msgspec; replacing its 411-line config module with pydantic-settings would not remove its domain rules.

### R19 — ❓ Experiment: native agent event/transcript decoding in anyllm

**Reuse first:** anyllm-v0.7.0 has complete(), Completion and extract_token_counts; it lacks native streaming-agent event and transcript readers. Its default cost guard and unknown-price-zero behavior must not be substituted for delegate's accounting.

**Job:** decode vendor event syntax into neutral observations, independent of launch policy and worker-run v3.

**Investigation spans:** _delegate/src/delegate/adapters/harness/claude.py:105-183 (79), codex.py:80-163 (84), opencode.py:171-240 (70); src/taskloop/adapters/context_size.py:1-43: **276 runtime**. **0 tests/fixtures credited**: captured worker-contract fixtures remain in the app until a vendor-only subset is identified.

**Proposed public interface:**

~~~python
Decoder(vendor, *, clock).feed(line) -> tuple[Observation, ...]
Decoder.finish() -> VendorSummary
Transcript(path, vendor).last_input_tokens(max_bytes=...) -> int | None
extract_token_counts(usage) -> tuple[int, int, int, int]  # existing
~~~

**Consumers:** delegate and task-loop; anyllm CLI adapters are the upstream consumer.

**What tests the boundary:**

- Replay vendor-only streams through old/new decoders and compare text, tools, message IDs, deduped usage and final markers.
- App adapters alone must produce identical HarnessEvents, denials, stop facts and worker-run v3 responses.
- Torn transcripts, sidechains, resumed cumulative usage and OpenCode lookup must retain current unknown outcomes.
- Prove the package imports neither app and contains no lane names, role rules, judge calls or worker schemas.

**Exact missing shelf feature/bead:** “Add vendor-native event observations and bounded transcript token reads to anyllm without invoking completion or its cost policy.”

**Risk high; cost L.** Tool completion and denial evidence can change worker termination. **Migration:** pure vendor observation prototype → decisive replay contracts → upstream tag → one decoder at a time → transcript readers. Until those tests pass, **0 approved moved lines**, 276 conditional only. The app retains launch argv, tool permissions, summary-to-stop classification, pricing-source decisions and re-ask behavior.

### R20 — ✅ Extract sortable identifiers and installed-plugin inventory mechanics

**Reuse first:** shelf has no ULID implementation; app-dirs has plugin roots but no installed-version inventory; mcp-clients describes MCP client installations, not plugin releases. Promote **sortable-id**, and evolve **app-dirs** for plugin inventory. A third-party ULID is permissible only after exact vectors pass; no library was selected without testing.

**Job:** provide sortable opaque identifiers/numeric versions and observe complete installed-plugin versions.

**Donors:** packages/kernel/src/tlkernel/ids.py:32-85 (54), :88-107 (20); src/taskloop/app/release/catalog.py:13-54 (42): **116 runtime**, **0 tests credited**.

**Public interface:**

~~~python
SortableId.new(now, entropy=None); SortableId.parse(text)
NumericVersion.parse(text)
PluginInstalls(root, *, plugin, marker).versions() -> Mapping[str, Path]
PluginInstalls.current(scope="user") -> str
~~~

**Consumers:** task-loop; delegate's install-root observer can use the same plugin-location concept.

**Contracts:**

- Crockford spelling, bit layout, timestamp ordering, entropy injection and invalid/overflow inputs match persisted IDs.
- Numeric tuple ordering preserves 1.2 versus 1.2.0; packaging.version normalization is not assumed equivalent.
- Partial installs/non-version directories are excluded and marketplace ties/current-scope lookup remain deterministic.

**Split:** app retains BeadId, repo/loop key identity, PLUGINS table, owner pin/rollback, version refusal and step-safe handover. **Cost M; risk high:** changed IDs break resume paths; bad inventory can select the wrong install.

**Migration:** identifier vectors/tag → app re-export → plugin inventory extension/tag → catalog adapter → keep selection/reexec unchanged.

### R21 — ✅ Finish atomic-io adoption immediately

**Reuse first:** atomic-io-v0.2.0 already implements atomic_write_bytes/text/json at P/atomic-io/src/atomic_io/__init__.py:21, :51, :63. No shelf change needed.

**Job:** replace remaining temp-write-replace sequences.

**Exact spans:** src/taskloop/stores/call_state.py:47-48 (2), :52-53 (2), :66-69 (4); adapters/storm.py:50-53 (4); src/taskloop_dash/serve.py:62 (1), :64-66 (3); readers/beads.py:73-76 (4): **20 runtime lines**, **0 tests moved**. Five persistence operations become five package calls; projected body shrinkage is 15 lines before imports.

**Public interface:**

~~~python
atomic_write_text(path, text, *, fsync=False, keep_mode=...)
atomic_write_bytes(path, data, *, fsync=False, keep_mode=...)
~~~

**Consumers:** task-loop and dashboard; delegate already adopts it.

**Contracts:**

- Existing JSON bytes/newlines and mode choices match; failure leaves old data and no temp file.
- Concurrent readers see complete old or new data.
- Raw answer is durable before phase=returned; crash replay never discards paid output.

**Cost S; risk medium.** **Migration:** shared cache → storm → dashboard PID → call state last. Keep checkpoint lifecycle and storm eligibility local. Mode changes require an explicit decision; shelf's 0600 default is not automatically the old umask behavior.

### R22 — ✅ Extract source-analysis mechanics from the structural gate

**Reuse first:** blueprint is a repository checkpoint framework, not this Python AST measurement API. Promote **python-source**; blueprint may consume it. Shelf's constitution rejects arbitrary size caps, so do not make task-loop's 400/80/800 policy the shelf default.

**Job:** measure parsed Python and observe literal/global/cycle facts for caller-defined rules.

**Donors, all currently test code:** tests/rules/gate_rules.py:63-128 (66), :150-161 (12), :191-255 (65), :257-261 (5), :554-591 (38): **186 lines**. The last span becomes parameterized generic rule tests; app caps and accepted-layer configuration stay local.

**Public interface:**

~~~python
PythonSource(path).measure() -> Measurement
PythonSource.mutable_globals() -> tuple[Occurrence, ...]
PythonSource.literals() -> tuple[Occurrence, ...]
ratchet(actual, known, *, ceiling) -> list[Difference]
cycle(edges) -> list[str] | None
~~~

**Consumers:** task-loop; blueprint and delegate structural gates are potential consumers.

**Contracts:**

- Comments, multiline docstrings, decorators and nested definitions have stable physical/SLOC measurements.
- AST cache invalidates on file change; mutable-global detection handles annotated assignments and guarded module statements.
- Ratchets distinguish new/grown/fixed/deleted entries with caller-supplied ceilings.
- Cycles have deterministic evidence; no app path or naming convention is imported.

**Cost M; risk medium:** a weakened structural gate can admit forbidden coupling. **Migration:** source facts → generic test contracts/tag → app adapters with unchanged cap/placement rules → independently evaluate removing obsolete checks. Do not claim the entire gate file moved.

### R23 — ✅ Extract retry arithmetic; keep retry/rest tables local

**Reuse first:** any-proc.supervise already owns capped restart backoff, but exposes it only through daemon supervision. Evolve a dependency-light **any_proc.backoff** submodule rather than build another supervisor.

**Job:** compute a capped jittered delay or repeat the final duration of a supplied sequence.

**Donors:** src/taskloop/domain/lanes/pauses.py:86-89 (4); retry.py:52-56 (5): **9 runtime**, **0 tests credited**.

**Public interface:**

~~~python
delay(base_s, cap_s, attempt, *, random) -> float
rest(sequence, attempt, *, empty=0.0) -> float
~~~

**Consumers:** task-loop; any-proc's supervisor is the upstream reconciliation consumer.

**Contracts:**

- Negative/huge attempts, saturation-before-jitter and exact ±20% current vectors remain stable.
- Empty and exhausted rest sequences preserve current outcomes.
- Generic arithmetic cannot select a reason, retry count, terminal action or wake authority.

**Cost S; risk medium:** wrong delays can create retry storms. **Migration:** arithmetic vectors → shelf tag → two wrappers. ROWS and TABLE remain unchanged. This is nine lines, not a claimed extraction of retry policy.

## D0 — ❓ Remove already-shared vendor copies only after delivery parity

**Reuse first:** all these implementations already belong to shelf. No new runtime package is justified. The missing feature is a tested shelf consumption/release recipe for uv scripts and plain hooks.

**Donors:** Python files under skills/task-loop/_vendor and _delegate/skills/delegate/_vendor total **8,129**, measured by rg --files over those two roots and wc -l. No new source extraction is credited. dev/vendor.py:1-170 is already an explicit delivery workaround; its deletion is **not** included in the 8,129 or any other budget.

**Interface:** build_deps(tagged_manifest) → immutable dependency artifact; verify_deps(artifact, manifest) → provenance; launchers choose that artifact. This is a release-tool interface, not a runtime resolver.

**Consumers:** both apps; the light hook is a separate interpreter consumer.

**Contracts:**

- All entry points and clean offline installs import the recorded package commit.
- Namespace shadowing cannot substitute a globally installed implementation.
- System-Python hook imports stay stdlib-only and match their supported syntax floor.
- Script locks/transitive dependencies ship, and rollback never needs a mutable shelf checkout.

**Cost L; risk critical:** code may work in a developer venv and fail in every installed plugin/hook. **Migration:** document both recipes → build parallel release artifact → import/provenance tests → select artifact in one app → remove that app's copies → second app. If an external dependency artifact merely moves bytes elsewhere inside the counted app roots, count **zero deletion**. Do not advertise 8,129 fewer lines until the actual distribution removes those tracked copies.

## Every shelf package: current fit ledger

For each row the cited API is the currently inspected public surface, not the proposed extension. A missing feature is to be fixed in shelf, not by modifying a vendor copy. “0” means no additional primary-app donor budget; referenced R/L candidates own the only credited spans. For a ❌ not-a-fit row: no migration, no new pin, 0 moved/deleted. Its acceptance checks are (1) the actual app holdouts remain, (2) the unrelated package's own contract stays intact, (3) no replacement is accepted without a matching donor. This refuses the pairing, not generic app code covered elsewhere.

| Package / public API evidence | Verdict, missing feature or actual donor |
|---|---|
| a2effect — P/a2effect/src/a2effect/__init__.py:9; AppError, ErrorEnvelope, Raises, translate_to | ❌ Not a fit for replacing current worker/CLI error wires: envelope v2 and its kind/exit taxonomy differ. Worker stop vocabulary stays app-owned; R2 moves generic codecs. 0. |
| any-browser — P/any-browser/src/any_browser/__init__.py:32; BrowserBackend.render, PlaywrightBackend, ZendriverBackend | ❌ No hand-rolled browser-engine adapter established. dev/dash_check.html's scenario assertions remain a separate mixed candidate below. Driver reuse alone does not move those assertions. 0. |
| any-file — P/any-file/src/any_file/__init__.py:93-113; safe_name, resolve_within, looks_binary, media_type | ✅ Adopt containment where R9 needs it; existing API, tag any-file-v0.2.0. Preserve app URL denials before path resolution. R9 owns the 36-line static donor; do not add 36 again. |
| any-frontmatter — P/any-frontmatter/src/any_frontmatter/__init__.py:13; parse/read/Document/FrontmatterError | ❓ Add source/body coordinates and a compatibility read mode for lifesim; L2. Existing v0.1.0 is ruamel-based while donor reads PyYAML. 0 primary. |
| any-markdown — P/any-markdown/src/any_markdown/__init__.py:112; Markdown.code_spans, sections, Budget | ❓ Source-preserving masks and declared heading dialect for L1; browser rendering is R11's separate job. Current tag any-markdown-v0.3.1. 0 primary credited here. |
| any-proc — P/any-proc/src/any_proc/__init__.py:1; run.call, supervise.Supervisor, cpus.available_cpus | ✅ Adopt CPU availability for lifesim L5 at any-proc-v0.3.0. ❓ Expose proven pure backoff for R23. Do not replace worker supervision with its marked-JSON protocol. |
| anyembed — P/anyembed/src/anyembed/__init__.py:21; Embedder, EmbeddingCache, LocalEmbedder | ❌ No embedding implementation in the observed apps/tools to replace. Run keys and artifact hashes are not embeddings. 0. |
| anyllm — P/anyllm/src/anyllm/__init__.py:33-51; complete, Completion, extract_token_counts, with_cost_guard | ❓ Add native agent event/transcript observations, R19. complete() lacks tool-stream/resume behavior. Do not map unknown accounting cost to its unknown-price zero. |
| app-dirs — P/app-dirs/src/app_dirs/__init__.py:36-57; config_dir/state_dir/cache_dir/plugin_data_dir | ❓ Add installed-plugin path/inventory observations, R13/R20. Resolve relative-XDG compatibility explicitly. Current tag app-dirs-v0.1.0, present in delegate vendor tree. |
| asgi-token-gate — P/asgi-token-gate/src/asgi_token_gate/__init__.py:33; TokenGate, StaticTokenGate, LeaseSet | ❌ Dashboard uses stdlib HTTP plus a bind access rule, not ASGI token middleware. Adding authentication changes product access behavior and extracts none of the donor. 0. No token file accessed. |
| async-scope — P/async-scope/src/async_scope/__init__.py:48; ResourceScope, memoized, to_thread_joined; asgi.serve_asgi | ❌ No matching async resource lifecycle found. Threaded sync server cleanup moves under R9; converting its concurrency model is not direct adoption. 0. |
| atomic-io — P/atomic-io/src/atomic_io/__init__.py:21/51/63; atomic_write_bytes/text/json | ✅ Adopt now, R21, 20 gross donor lines under atomic-io-v0.2.0; R3 composes it. No missing feature. |
| bdd-tags — P/bdd-tags/src/bdd_tags/__init__.py:28-45; pytest tag hooks | ❌ Apps' unittest/pytest tests are classified by path, not Gherkin tags. No duplicated Gherkin tag hook. 0. |
| blueprint — P/blueprint/src/blueprint/__init__.py:1; python -m blueprint check, recipe, testing.Repo | ❓ Share a strict linked-checkout-safe common-config observer with lifesim, L4. R22 promotes Python facts, retaining task-loop rule policy. Current blueprint-v0.1.0. |
| browser-cookies — P/browser-cookies/src/browser_cookies/__init__.py:21; read_cookies, CookieRow | ❌ No browser-cookie reader donor; account/quota observations are different protocols. Credential retrieval is outside the task. 0. |
| child-env — P/child-env/src/child_env/__init__.py:70; scrub, scrub_current | ❓ Add pure virtualenv removal, R13. Current v0.1.0 scrub defaults deliberately differ from task-loop's tool/worker environments. Preserve app allowlists and keep/drop policy. |
| content-extract — P/content-extract/src/content_extract/__init__.py:230; extract_markdown, parse_metadata | ❌ No fetched-article extraction donor. Authored design checks and worker events must retain source structure. 0. |
| convert-md — P/convert-md/src/convert_md/__init__.py:13-24; convert, convert_html, missing_engines | ❌ No app document conversion engine to replace; artifact copying is not PDF/Office conversion. 0. |
| dir-trust — P/dir-trust/src/dir_trust/__init__.py:38; folder_hash, TrustStore | ❌ Host-local approval grants differ from worker identity and content-addressed snapshot identity. Do not add trust state to a run identity. Hashing mechanics can be generalized independently, but no additional spans credited. |
| dom-schema — P/dom-schema/src/dom_schema/__init__.py:26; Schema, Field, extract | ❌ No declared HTML scraper donor. JSON Schema generation is R2, not this HTML-selector package. 0. |
| duckdb-sidecar — P/duckdb-sidecar/src/duckdb_sidecar/__init__.py:47; connect, rename_column, is_lock_conflict | ❌ No app-owned DuckDB connection or migration implementation. File stores and external Dolt are different storage contracts. 0. |
| due-schedule — P/due-schedule/src/due_schedule/__init__.py:94; schedule_is_due, parse_interval, is_valid_cron | ❌ Retry wakes and limits are not recurring cron jobs. Their unknown-reason owner wake rule remains local; R12/R23 extract parser/arithmetic. 0. |
| event-bus — P/event-bus/src/event_bus/__init__.py:26; EventBus.subscribe/publish/subscribed | ❌ Durable events/logs and cross-process observations are not synchronous transient pub/sub. No subscriber-registry duplicate established. 0. |
| fts-query — P/fts-query/src/fts_query/__init__.py:125; parse, Tokens, Fold, fts_terms | ❌ No FTS5 query/tokenizer implementation to retire. Git grep and exact policy regexes are different contracts. 0. |
| git-porcelain — P/git-porcelain/src/git_porcelain/__init__.py:20-89; RealRepo, Worktree, status/history/LFS | ❓ Strict read/operation parity and simulator convergence first, R1. Pin new tag after tests; retain current git-porcelain-v0.7.0 until then. |
| html-fragment — P/html-fragment/src/html_fragment/__init__.py:44; to_text, to_markdown | ❌ No fetched HTML-fragment conversion donor. Escaped Markdown-to-HTML in R11 is the reverse direction. 0. |
| http-cache — P/http-cache/src/http_cache/__init__.py:133; HttpCache.get/put, conditional_headers | ❌ Dashboard memoizes local parsed files/typed views, not GET response bodies. R10 extracts value-cache; do not introduce SQLite/async for this pairing. 0. |
| http-fetch — P/http-fetch/src/http_fetch/__init__.py:16; fetch_bytes, FetchOutcome, FetchVerdict | ❌ DNS/TCP facts in R15 are not a content GET. A fetch cannot preserve DNS-versus-TCP diagnosis without extra mechanics. 0. |
| json-in-html — P/json-in-html/src/json_in_html/__init__.py:1; extract_json_payloads, rank_payloads, parse_json_response | ❌ Worker CLI JSON is a contractual stream, not page-embedded/ranked JSON. R19 handles vendor syntax explicitly. 0. |
| json-match — P/json-match/src/json_match/__init__.py:36; dig, compare, matches, MISSING | ❌ No duplicated dotted-path/subset assertion engine found. Existing schema/wire goldens compare exact shapes, not subset semantics. Generic harness extraction is R16/R22. 0. |
| jsonl-log — P/jsonl-log/src/jsonl_log/__init__.py:211; JsonlLog, Jsonl, read_from, tail, append_line | ❓ Public bytes parser, byte budgets, append pool and locked predicate compaction, R4. Keep current v0.2.0 until extension contracts pass. |
| launchd-agent — P/launchd-agent/src/launchd_agent/__init__.py:96; render_plist, install, uninstall, status | ❌ Factory launches are explicit POSIX process lifetimes, not LaunchAgent registration. No plist/launchctl donor. 0. |
| lean-wire — P/lean-wire/src/lean_wire/__init__.py:22; encode_tsv, prune_dict, PruneEmpty | ❌ Current worker-run v3 and persisted records own absent/falsy meaning. Table rendering can use its codec if separately required; no exact TSV implementation donor credited. 0. |
| llm-cache — P/llm-cache/src/llm_cache/__init__.py:67; LlmCache.get/put, make_key | ❌ An in-flight call checkpoint is not a reusable answer cache. Resuming paid work must not become cached answer replay. R3 moves only storage mechanics. 0. |
| llm-wobble — P/llm-wobble/src/llm_wobble/__init__.py:295; parse_with_policy, parse_list_with_policy, bind | ❌ Current worker/event records require strict contractual decoding. Recovery defaults would change answer/stop acceptance; R2 moves strict decoding and leaves recovery policy explicit. 0. |
| managed-region — P/managed-region/src/managed_region/__init__.py:25; replace_region | ❌ No matching machine-block writer identified. Lifesim removes blocks before validation; replace-one-region is a different operation. 0. |
| mcp-arg-errors — P/mcp-arg-errors/src/mcp_arg_errors/__init__.py:90; ErrorWire, ArgumentErrorMiddleware | ❌ No FastMCP tool-server error boundary donor. Worker/hook refusals are app protocols. 0. |
| mcp-bridge — P/mcp-bridge/src/mcp_bridge/__init__.py:36; build_bridge, downstream_client_name | ❌ No stdio-to-HTTP MCP relay implementation donor. Native worker stdio is not MCP. 0. |
| mcp-call — P/mcp-call/src/mcp_call/__init__.py:79; McpEndpoint.call/tools, ToolResult | ❌ No MCP initialization/session client donor. Process invocation and usage probes use different protocols. 0. |
| mcp-clients — P/mcp-clients/src/mcp_clients/__init__.py:73; configured_servers, client_statuses | ❌ Plugin release inventory in R20 is not an MCP server-list scan. Do not repurpose unreadable-config-as-disconnected for required plugin identity. 0. |
| mcp-feedback — P/mcp-feedback/src/mcp_feedback/__init__.py:38; register_feedback_tool | ❌ Durable asks/reflections have authority and lifecycle semantics, not a fixed external feedback delivery schema. 0. |
| mcp-result-wire — P/mcp-result-wire/src/mcp_result_wire/__init__.py:19; FormatRoutingMiddleware, ListViewMiddleware | ❌ Dashboard HTTP and worker stdout are not FastMCP result channels. No middleware copy. 0. |
| mcp-steps — P/mcp-steps/src/mcp_steps/__init__.py:70; McpSessions, refusal_of, result_of | ❌ No MCP-server Gherkin harness donor. R16 extracts the process harness actually present. 0. |
| page-tsv — P/page-tsv/src/page_tsv/__init__.py:21-40; Page, render, render_plain, EncodingPlan | ❌ No Page/pydantic return-type rendering implementation to remove. Changing current CLI/worker output to TSV is a product wire change. 0. |
| partial-time — P/partial-time/src/partial_time/__init__.py:64; interval, format_interval | ❌ Precision-as-interval dates do not implement future owner-entered waits or vendor reset prose. R12 extracts those parsers. 0. |
| path-pattern — P/path-pattern/src/path_pattern/__init__.py:56; resolve, reverse_match, pattern_specificity | ❓ Add explicit case-sensitive literal matching for lifesim, L3. Current v0.1.0 reverse matching is case-insensitive. It does not replace R8 globs. |
| plugin-surface — P/plugin-surface/src/plugin_surface/__init__.py:90; PluginManifest, load_surface, describe_directory | ❌ Current harness/verb registries encode known required app capabilities. No dynamic discovery implementation donor established; silent dropping of Unavailable cannot replace required-harness errors. 0. |
| process-lock — P/process-lock/src/process_lock/__init__.py:104; ProcessLock.acquire, holder, held | ❓ Add cancellation/ticket mechanics, R6; delegate already adopts v0.2.0 non-reentrant mode. Never implement stale-pid takeover of a kernel-held lock. |
| record-mine — P/record-mine/src/record_mine/__init__.py:15; extract_records, RecordSet | ❌ No repeated-HTML-record inference donor. Beads and worker events already have structured schemas. 0. |
| settings-base — P/settings-base/src/settings_base/__init__.py:41; resolve_env_refs, resolve_config_path, SecretStrippingYamlSource | ❓ Add pure JSON mapping overlay, R18. Keep msgspec schemas and profile/routing precedence in apps; do not force pydantic/YAML onto the plain hook. |
| sqlite-resource — P/sqlite-resource/src/sqlite_resource/__init__.py:32; SqliteResource.ensure/conn/close | ❌ No app-owned aiosqlite lifecycle donor. An external CLI's database is not this app's connection to manage. 0. |
| sqlite-sidecar — P/sqlite-sidecar/src/sqlite_sidecar/__init__.py:1; connect, transaction, prepare, ensure_schema | ❌ No direct sidecar lifecycle/repair donor. Moving typed JSON state into SQLite would be a storage migration, not reuse of existing mechanics. 0. |
| static-page-check — P/static-page-check/src/static_page_check/__init__.py:1; import/page/pin/colour/budget_problems | ✅ Retain existing v0.1.0 adoption in tests/dash/test_dash_static.py:1-45. No new lines saved. R17's general manifest is a separate capability. |
| stream-proc — P/stream-proc/src/stream_proc/__init__.py:19; run, stop_tree, alive, popen_held, table | ❓ Extend capture/recorded handles/stop evidence/deadlines, R5, and add testing surface R16. Current pin v0.2.2. |
| timefmt — P/timefmt/src/timefmt/__init__.py:21; fmt_dur, fmt_span, fmt_until, human_count | ✅ Retain delegate Python adoption. ❓ Browser artifact/compatibility display dialects, R11/R12; no forced format change. Current v0.2.0. |
| verb-cli — P/verb-cli/src/verb_cli/__init__.py:164; flags_of, to_argparse, kwargs_of; testing.assert_help_tree | ❓ Needs positional/remainder/subcommand compatibility before replacing explicit CLIs. Test full argv/help/default/exit tree. No speculative parser-line saving; app verb names and authorization stay local. |
| yaml-merge — P/yaml-merge/src/yaml_merge/__init__.py:43; merge_into | ❌ No round-trip YAML writer donor. Delegate overlays plain JSON; R18 owns that mechanic. Lifesim currently reads frontmatter. 0. |

### APIs that are too small or oddly shaped: upstream changes, not app forks

The actionable shelf changes are specific: jsonl-log needs byte budgets and owned pools rather than another Jsonl facade; process-lock needs cancellation rather than another wait loop; stream-proc needs ProcessRef/StopReport rather than app Popen duck types; app-dirs needs installation observations rather than app copies of Claude cache layout; settings-base needs a lightweight JSON overlay submodule; timefmt needs a browser artifact and named legacy dialects; anyllm needs vendor observations below completion; verb-cli needs real positional/remainder semantics; any-markdown needs source-preserving masks. Their extraction beads below carry these upstream acceptance criteria.

A new typed-record or value-cache is justified because no current shelf package owns that concept. A new “task framework” that takes bead/slot/run records is refused: parameterizing the app's vocabulary does not remove its rules.

## Third consumer: lifesim opportunities, excluded from primary totals

These five budgets are additional, disjoint **71 tool lines**, not evidence that 71 task-loop/delegate lines moved. No lifesim tests or fixtures are counted as transferable.

**L1 — ✅ Extract, ❓ any-markdown extension first.** _lifesim_tools/check_design.py:326-354 (**29**) masks source and sections while preserving offsets. Existing Markdown.code_spans/sections at P/any-markdown/src/any_markdown/__init__.py:112 are the starting point; missing mask API and heading dialect must live there. Interface: masked(text, exclude=...) → same-length text; sections(text, level=2) → spans. Consumers: lifesim, possible shelf document validators.

- Preserve every newline and source offset.
- Pin fenced/inline code, HTML comments and link-target exclusions against current fixtures.
- Declare CommonMark improvements as explicit design-gate changes, rather than silently changing which terms are prohibited.

Cost M; risk medium: erroneous design findings. Migration: offset corpus → shelf extension/tag → mask adapter → section adapter.

**L2 — ✅ Extract, ❓ any-frontmatter extension first.** check_design.py:90-99 (**10**) is frontmatter read machinery inside an app Doc. Interface: parse(text, locations=True) → Document/body_start/problems. Existing parse/Document are exported at P/any-frontmatter/src/any_frontmatter/__init__.py:13. Consumers: lifesim and shelf Markdown consumers.

- Pin absent/malformed/unclosed header outcomes.
- Preserve body line offsets and error positions.
- Differentially test PyYAML versus ruamel bool/date/coercion behavior.

Cost M; risk medium: false ontology validation. Migration: source coordinates/tag → compatibility reader → leave kind/slug/report policy in Doc.

**L3 — ✅ Extract, ❓ path-pattern extension first.** check_design.py:105-106 (**2**) reverses a case-sensitive slug pattern. Interface: reverse_match(pattern, path, case_sensitive=True). Existing API at P/path-pattern/src/path_pattern/__init__.py:56 needs the explicit mode. Consumers: lifesim; existing shelf template consumers keep default behavior.

- Case-only literal differences remain rejected in this mode.
- Slug does not cross folder boundaries.
- Existing case-insensitive callers remain unchanged.

Cost S; risk medium. Migration: two-mode contracts/tag → replace matcher. Do not broaden the ontology's accepted placeholder grammar without a separate gate change.

**L4 — ✅ Extract, ❓ blueprint observer first.** _lifesim_tools/check_git_config.py:13-41 (**29**) observes shared Git config and reports dangerous overrides. Interface: common_config_findings(repo, run) → findings | Unknown. Blueprint's existing check engine and git-porcelain's strict observer should share the mechanism. Consumers: lifesim/blueprint.

- Linked checkout resolves the common config correctly.
- Ambient Git variables cannot redirect the observer.
- Query failure is Unknown/failure, not a clean configuration; duplicate values remain visible.

Cost M; risk high: a corrupted checkout pin can invalidate every gate. Migration: observer parity/tag → lifesim adapter → blueprint check. Keep changed.py's group selection tables local.

**L5 — ✅ Adopt now: any-proc CPUs.** _lifesim_tools/run_tests_parallel.py:39 (**1**) uses os.cpu_count() to size a pool. Replace with any_proc.cpus.available_cpus (P/any-proc/src/any_proc/cpus.py:1), pin any-proc-v0.3.0 through verified offline delivery. Interface: available_cpus() → positive int. Consumers: lifesim; shelf already owns the implementation.

- Affinity, cgroup v1/v2 and missing quota return a usable bound.
- Pool never receives zero workers.
- Test result/exit aggregation remains unchanged.

Cost S; risk low: scheduling/performance only. Migration: install artifact → explicit adoption of quota-aware sizing → change one expression. This is reuse, not meaningful net LOC reduction.

## Explicit app-domain refusals and retained interfaces

These refusals name actual rules. They do not prohibit extracting mechanics already budgeted above. No library migration is proposed for the retained rule, and movement/deletion is zero.

| ❌ Rule and evidence | App interface retained; why shelf must not own it |
|---|---|
| Bead lifecycle/actor fencing — src/taskloop/adapters/bd.py:245-260; bdcreate.py:1-36; bdsafe.py:1-22 | Beads.claim/close/update remains app-owned. close first fences the assignee via update, then closes; a generic bd client must not absorb that factory authority. Generic process/JSON substrate is R2/R5. |
| Gate evidence/admission — src/taskloop/app/checks/cache.py:113-196, :245-268 | RunMemo.key/result and satisfied retain “only satisfied exact requirements authorize delivery,” producer receipt identity, planned-skip versus pass and historical-display distinctions. R8 may hash selected inputs; it cannot choose which inputs authorize land. |
| Retry/rest tables — src/taskloop/domain/lanes/retry.py:29-38; pauses.py:24-83 | PLAN/rule keep invalid-output retry counts, denied-secret fresh-thread handling, reroute/ask/fault choices and unknown-reason owner wake. R23 moves only arithmetic. |
| Config/profile rules — packages/kernel/src/tlkernel/config.py:322-411; _delegate/src/delegate/app/env.py:67-96 | load/typed_routing keep cross-lane-read rejection, mangled-ID collision, container requirements, retired/replaced keys and owner profile precedence. graphlib.TopologicalSorter is already used; no second cycle-sorter saving is invented. |
| Path/layout identity — packages/kernel/src/tlkernel/paths.py:16-288, except R13 | ConfigDir/RunFiles/RepoDirs name authoritative asks, checkpoints, run output and worker scratch. Path joins are already pathlib calls. Exporting these layouts exports the app's persisted model. |
| Safe-point version hop — src/taskloop/app/release/reexec.py:21-76; selfupdate.py:17-37; src/taskloop/app/run/reload.py:29-124 | Reload.safe_point/switch and owner pin/rollback retain checkpoint/counter carryover, slot ownership, bad-version fallback and close suppression after exec. R20 observes installs; it does not select or activate one. |
| Worker contract and lane pricing — _delegate/src/delegate/app/watch.py:43-86; domain/cost/accounting.py:49-64; app/usage.py:49-83, :124-170 | Turn.verdict, usage-to-Lane mapping and price-source choices retain completion grace/tool exemptions, spend-block/98% thresholds, stale-data policy, free/subscription lane rules. R19 may decode vendor facts only. |
| CLI dispatch and owner surfaces — skills/task-loop/tl.py:1-460; _delegate/src/delegate/cli/parser.py:1 | Verb names, flags, exit outcomes and owner-only actions are app API. Extract proven parser scaffolding only after verb-cli's positional/remainder parity; do not count the whole CLI as a reusable library. |
| Dashboard semantic views — src/taskloop_dash/views/live_lines.py:43-99; packages/kernel/src/tlkernel/dash.py:1-562 | Engine/worker events map to specific factory phases, owner needs and outcome tones. HTTP and text mechanics move, factory view schemas stay. |
| Dashboard access policy — src/taskloop_dash/bind.py:20-93 | allowed_addr/bind_refusal keep unauthenticated Tailscale/loopback access, installed-copy ownership of port 7878 and required registered state. R9 only binds the already-approved address set. |

The app holdouts for every refused rule must pin valid decisions, malformed/unknown refusal, and ordered side effects. New generic package contracts supplement those holdouts; they do not replace them.

## What remains below the 50% target

Even accepting every identified conditional line leaves **128,078 of the counted lines** in the apps. The shortfall to 50% is **56,262** beyond the combined gross ceiling, and larger after adapters.

That does not certify all remaining code as domain. **104,946 lines outside the budgets and the 25-file table below have no quantified extraction verdict in this lens**. They are ❓ untested for additional movement, not refused or quietly counted toward 50%. A further candidate must identify a generic input/output boundary, move its independent tests and pass the corresponding app holdouts. The existing shelf/package matching inventory covers all 57 packages; it is not a line-by-line proof about every remaining test or fixture.

The 25 largest remaining files/spans follow. The sizes are current wc counts, with explicitly budgeted spans subtracted where relevant. They total **23,132 retained lines**: **22,010 refused domain lines**, plus **1,122 untested mixed lines**. Large JSON fixtures are not disposable duplicates merely because generic codecs can decode them.

| Remaining file, evidence and lines | Verdict and exact retained rule / deciding experiment |
|---|---|
| tests/dash/golden/closes.json:1-2927 — 2,927 | ❌ Factory closes/asks/column/cause presentation golden. Generic serialization moves under R2; this expected factory behavior stays. |
| tests/fixtures/dash/snapshot.json:1-2341 — 2,341 | ❌ Snapshot server/loop/bead/lane schema fixture, not a generic cache or JSON reader contract. |
| tests/contracts/golden/records.json:1-1826 — 1,826 | ❌ Persisted Epic/RunTrace/ask/etc. wire compatibility. Moving the codec does not transfer ownership of these schemas. |
| _delegate/skills/delegate/contract.json:1-1749 — 1,749 | ❌ Worker-run v3 stop scopes/permanences/facts and caller flags. Shelf must not own the worker contract. |
| tests/fixtures/dash/mock-8b.json:1-1045 — 1,045 | ❌ Factory board scenario data: slots, lanes, owner columns and visual approvals. |
| tests/loop/real/test_loop.py:1-915 — 915 | ❌ Pick/run/stop/claim integration semantics. Processes below it move under R5; those decisions remain. |
| tests/run/test_engine_run.py:1-828 — 828 | ❌ Run resume/stop/budget/closure contract. |
| tests/run/test_stages.py:1-817 — 817 | ❌ Stage handoff, worker permission and checkpoint transitions. |
| tests/support/narrow_hosts.py:1-777 — 777 | ❌ Typed fakes of app WaitsHost/OutboundHost/worker state, including bead/Dolt/slot behavior. Generic patch/process mechanics already move under R16; exporting host protocols would export the app. |
| tests/support/engine_case.py:1-765 — 765 | ❌ Engine-specific plan/write/verify/land fixture world and expected lifecycle. No generic engine-world package. |
| tests/land/test_engine_land_1.py:1-752 — 752 | ❌ Push/rebase/conflict-fix authority and land outcomes; generic Git tests move separately under R1. |
| tests/run/test_stages_visual.py:1-717 — 717 | ❌ Visual approval, resume counts and bead claim authority. |
| tests/land/test_stages_land.py:1-706 — 706 | ❌ Stale tree, slot hygiene, lane failure and follow-up delivery behavior. |
| skills/task-loop/SKILL.md:1-674 — 674 | ❌ The app's operational method: claim/plan/delegate/verify/merge/close and slot ownership. |
| tests/run/test_engine_units.py:1-652 — 652 | ❌ Failure briefs, delegate launcher semantics and owner confirmation behavior. |
| tests/land/test_race_invariants.py:1-640 — 640 | ❌ No double claim/run, protected land/push/close and slot/lease race invariants. The generic clock/rebinding helpers move, not these assertions. |
| tests/contracts/samples.py:1-600 — 600 | ❌ One sample per app record, proving schema completeness and actual wire compatibility. |
| dev/dash_check.html:1-582 — 582 | ❓ Mixed browser harness. Split load/visibility/viewport/tap-size facts from SCENARIOS; app keeps board/drawer/owner-action expectations. Test a neutral page plus unchanged dashboard scenarios before approving measured spans. No guessed 582-line saving. |
| tests/e2e/test_release.py:1-570 — 570 | ❌ Release clone ownership, reexec, suite-before-publication and package activation semantics. R17's manifest checks are below this flow. |
| packages/kernel/src/tlkernel/dash.py:1-562 — 562 | ❌ Factory view/request schemas, paired project/bead identity and owner actions. |
| tests/land/test_stack.py:1-549 — 549 | ❌ Ordered PR/branch delivery, each merge SHA attribution, first-failure stop and land-lock scope. |
| tests/plan/test_engine_plan.py:1-546 — 546 | ❌ Plan/replan/acceptance semantics and worker answer handling. |
| tests/rules/gate_rules.py:1-726 minus R22's 186 — 540 | ❓ Mixed remaining gate. Retain app layer/path/cap rules; next test must separate generic signal/shell/import/vendor observers from their app allowlists and legacy folder table. R22's measured split already counts 186; no second credit. |
| tests/support/dash_fixtures.py:1-527 — 527 | ❌ Conversion of round-8b app mock data into factory view records, with fixed app scenario clock. |
| tests/fixtures/delegate3/skills/delegate/contract.json:1-525 — 525 | ❌ Historical worker contract fixture. Delete only if the compatibility support window is intentionally retired in an app change; not dead code proven by this audit. |

## Totals

“Moved out” below means measured gross retirement from the app tree after the proposed refactor, before replacement adapters. No implementation has moved in this review.

| Verdict / category | Covered lines | Proposed moved/replaced out | % of full 143,632 |
|---|---:|---:|---:|
| ✅ Approved candidates R1-R18, R20-R23 | **7,149** | **7,149 gross** | **4.98%** |
| Within that: source/JS/storage/dev implementation | 3,413 | Included above | 2.38% |
| Within that: generic tests/helpers/contract harnesses | 3,736 | Included above | 2.60% |
| Within that: app fixtures/JSON goldens | 0 | 0 | 0% |
| ❓ R19 vendor-event boundary | 276 | 0 approved; 276 conditional | 0.19% |
| ❓ D0 already-shared vendor delivery | 8,129 | 0 approved; 8,129 conditional deletion | 5.66% |
| ❌ Named domain in largest remaining 25 | 22,010 | 0 | 15.32% |
| ❓ Mixed remainder of those 25 | 1,122 | 0 quantified | 0.78% |
| ❓ Remaining inventoried files, no extraction budget | 104,946 | 0 quantified | 73.07% |
| **Inventory total, disjoint categories** | **143,632** | — | **100%** |

Of the approved 7,149, **7,129** are generic mechanism/test ownership transfers or consolidation; **20** are old persistence lines replaced by existing shelf calls (R21), with five replacement calls and about 15 fewer body lines. No extra duplicate-deletion number is added for R2/R1 consolidation. Proven dead-code deletion: **0**. Proven additional stdlib/third-party replacement volume: **0**; msgspec, graphlib, pathlib, shlex and stdlib HTTP are already in use. Candidate ULID/parser substitutions require compatibility tests before claiming deletion.

Known conditional movement is 276; known conditional already-shared copy deletion is 8,129. Approved plus both conditional ceilings: **15,554 / 143,632 = 10.83%**. That is not a 50% plan, and not net shrinkage. L1-L5 add 71 external tool lines and do not alter the primary percentages.

The constraint is not “too early” or “too many callers.” The measurable wins are approved despite refactoring cost. The evidence does not support manufacturing the other 56,262 lines by packaging bead/slot/run/lane/worker-contract rules, moving factory goldens away from their owner, or calling every large file dead. Further volume needs additional measured substrate splits, especially the two mixed harness/gate files, rather than looser accounting.

## Top 10

Rank balances measured lines per unit production risk, leverage across evidenced consumers, and refactor cost. Consumer count is app count; dashboard is part of task-loop. Prospective consumers do not multiply leverage. These are the Phase 2 briefs; use the candidate's exact spans, public interface and contract bullets.

| Rank | Candidate | Gross lines × current apps | Cost / risk | First releasable step |
|---:|---|---:|---|---|
| 1 | R7 check-output | 628 × 1 = 628 | M / medium | Publish pure diagnostic parser and its 212 test lines; keep check exit/admission unchanged. |
| 2 | R16 process test substrate | 325 × 1 = 325 | M / medium | stream_proc.testing guard with planted-spawn tests; app registers bd/marker cases. |
| 3 | R2 typed-record | 694 × 2 = 1,388 | M / high | Tag strict schema transforms and differential wire vectors; keep app schemas/goldens. |
| 4 | R4 JSONL substrate | 478 × 2 = 956 | M / high | Public bytes parser plus byte-budget contract before replacing dashboard readers. |
| 5 | R1 git-porcelain convergence | 3,315 × 2 = 6,630 | L / critical | Strict read/topology parity; then move simulator/contracts before any mutation-family cutover. |
| 6 | R9 local-http/static | 140 × 1 = 140 | M / high | Static containment byte contracts; route/bind policy adapters remain local. |
| 7 | R3 typed document storage | 135 × 2 = 270 | M / high | Four read outcomes and locked update behind current app stores, after R2. |
| 8 | R5 stream-proc completion | 271 × 2 = 542 | M / critical | Captured-run and recorded-handle contracts, including spawn-interruption holdouts. |
| 9 | R6 process-lock/tickets | 238 × 1 = 238 | M / critical | Cancellable non-reentrant wait; preserve current holder sidecar before ticket adoption. |
| 10 | R22 Python source facts | 186 × 1 = 186 | M / medium | Package pure measurements/AST observations with caller-supplied gate policy. |

R21 is a small immediate cleanup to do alongside the first relevant storage slice, not a reason to prioritize 20 lines over the deeper boundaries. D0 is a parallel distribution prerequisite for deleting vendor copies; it must not block using the working tagged-vendor mechanism for the first extractions.

## Beads to file

These are requested issue titles/scopes, not filed tracker entries; the task allowed only this document write. One bead per extraction boundary, including its upstream work and app migration acceptance.

- **R1 — Converge Git mechanics and simulator onto git-porcelain** — Add strict observation parity, move the 2,414-line simulator/contract body, then migrate operation families behind unchanged app ports.
- **R2 — Promote typed-record codecs and schema transforms** — Own strict version/tag/ABSENT behavior and differential tests; keep record classes, fixture data and worker schemas in apps.
- **R3 — Promote typed-record document storage** — Four read outcomes, keyed sets and locked read/modify/write composed from atomic-io/process-lock.
- **R4 — Complete jsonl-log reader/writer substrate** — Public bytes parser, byte budgets, typed pages, descriptor pooling, bounded text tails and locked predicate compaction.
- **R5 — Complete stream-proc capture and recorded-process ownership** — Add stdin/capture/ProcessRef/StopReport and generic activity deadlines; preserve WorkerEnd and stop policy in delegate.
- **R6 — Complete process-lock cancellation and ticket queue mechanics** — Preserve thread/process exclusion and holder compatibility; app retains resource/slot/land admission.
- **R7 — Promote check-output diagnostics and excerpts** — Move the measured 416 implementation and 212 test lines, preserving byte budgets and leaving retry decisions local.
- **R8 — Promote path-glob selection and digesting** — Pin the current brace/star dialect and no-false-green input-selection vectors.
- **R9 — Promote local-http static and transport mechanics** — Own containment, bounded request plumbing and all-or-none listeners; retain route and access policy.
- **R10 — Promote value-cache objects** — Own TTL and file-signature/LRU behavior without importing dashboard state.
- **R11 — Publish tagged browser formatting and safe-inline-markdown artifacts** — Preserve current strings/rendering and prove the ES-module hash/import delivery path.
- **R12 — Promote time-spec parsing and compatibility rendering** — Differentially test owner-entered times, timestamp dialects, DST and existing zero-relative behavior.
- **R13 — Evolve child-env/app-dirs for remaining app glue** — Add virtualenv removal and installed-plugin data discovery without changing tool allowlists or state roots silently.
- **R14 — Promote shell-inspect below delegate worker policy** — Extract syntax observations and an adversarial corpus; retain all allowlists, secret rules and judge decisions.
- **R15 — Promote net-status DNS/TCP observations** — Bounded injected probes and cached facts; routing/park authority remains in the consumer.
- **R16 — Move generic process fakes into stream-proc testing** — Fake subprocess/streaming agreement, swallowed-spawn guard, isolated worlds and generic clock/rebinding cleanup.
- **R17 — Promote artifact-manifest generation/verification** — Deterministic manifest bytes and explicit containment/missing/extra-file rules.
- **R18 — Add lightweight JSON overlay to settings-base** — Preserve recursive overwrite and copy semantics; no YAML/pydantic migration of app rules.
- **R19 — Experiment with anyllm native agent observations** — Establish the neutral event/transcript boundary through replay before approving any of the 276 lines.
- **R20 — Promote sortable-id and installed-plugin inventory** — Exact persisted ULID/numeric-version vectors and complete-install observations; owner pin/reexec authority stays local.
- **R21 — Finish existing atomic-io adoption** — Replace five persistence sequences while preserving bytes, modes and raw-answer-before-phase order.
- **R22 — Promote Python source facts from the structural gate** — Move measured AST/ratchet machinery and neutral tests; app owns thresholds, layers and allowed paths.
- **R23 — Expose pure backoff/rest arithmetic in any-proc** — Test saturated jitter and repeated-final-rest semantics; retain all retry/wake reason tables.
- **D0 — Prove shelf delivery for uv scripts and plain hooks** — Script locks, immutable commit/hash provenance, offline installation, import-origin verification and rollback before vendor-copy deletion.
- **L1 — Add source-preserving masks to any-markdown** — Preserve lifesim offsets and characterize grammar differences before changing its design gate.
- **L2 — Add frontmatter source coordinates and read compatibility** — Pin PyYAML/ruamel differences and body/error line positions for lifesim.
- **L3 — Add case-sensitive reverse matching to path-pattern** — Keep existing defaults and preserve the ontology's exact slug/literal grammar.
- **L4 — Share strict common-Git-config observation with blueprint** — Linked-checkout-safe reads with Unknown distinct from clean; preserve lifesim's failure behavior.
- **L5 — Adopt quota-aware CPU availability in lifesim** — Deliver any-proc-v0.3.0 offline and preserve the test runner's result aggregation.
