# B2 redo — delegate and dashboard substrate

## Decision, scope and measured volume

**Extract 3,018 existing lines across 18 concrete migrations.** This includes 2,600 runtime lines and 418 test/support lines. The default here is extraction, including splitting mixed modules and changing their internal architecture. The retained boundary is the factory's decisions, not the current module layout.

This is **14.89% of the 20,264-line B2 inventory**, **19.14% of its 13,581 runtime lines**, and **2.10% of the requested 143,632-line task-loop + delegate denominator**. It does not substantiate 50%. Reaching that global target requires another 68,798 lines beyond these donor spans. B2 alone cannot supply them: its entire inventory is only 14.11% of the global denominator. This is not evidence that all remaining engine code is irreducible domain policy.

These are measured, gross donor spans to relocate, not an implemented diff or a prediction of net savings. Compatibility adapters, parameter injection and imports remain/add lines in the apps. No savings are claimed for code already in shelf, hypothetical new tests, changing JSON indentation, moving product fixtures without their meaning, or deleting unproven dead code.

### Census and reproducibility

Counts include blanks, comments and imports, and use physical lines, not SLOC. The full census was:

    rg --files --hidden --no-ignore src tests skills dev _delegate/src _delegate/skills       -g '*.py' -g '*.js' -g '*.html' -g '*.json' -g '*.md' | xargs wc -l

| Census | Lines |
|---|---:|
| task-loop: src, tests, skills, dev; five extensions above | 131,701 |
| delegate: _delegate/src and _delegate/skills; same extensions | 11,931 |
| Global denominator | **143,632** |
| _delegate/src, Python source | 7,771 |
| src/taskloop_dash, Python + JS + HTML + JSON + Markdown | 5,810 |
| tests/dash, same five extensions, including golden/closes.json | 6,345 |
| tests/support/procsim.py | 249 |
| tests/rules/test_procsim.py + tests/rules/real/test_procsim.py | 89 |
| B2 inventory, disjoint sum of the five preceding rows | **20,264** |

The supplied delegate snapshot has no _delegate/tests or _delegate/dev directory. Their contribution is zero, not an estimated unseen test suite. The global census includes existing vendored Python under skills; those copies receive no new extraction credit. CSS is excluded from the requested denominator and from savings. Shelf and lifesim are comparison consumers, excluded from both denominators.

Every partial range below was reread and measured with sed -n 'START,ENDp' FILE | wc -l. Ranges are inclusive. Where a method has app references, the relocation replaces those references with explicit arguments/callbacks; it does not copy the app import into shelf. Counts describe the old generic body, with separately identified app rules retained.

Read first: _shelf/AGENTS.md, _shelf/CONTEXT.md, _shelf/docs/constitution.md and catalog/*.toml; also doctrine and relevant package implementations. Other extraction reviews were consulted as prior hypotheses, not substituted for source inspection.

Two architectural corrections affect the migration. The dashboard is not wholly read-only: src/taskloop_dash/http.py:77-86 accepts POSTs through dash.writes.post. Its live transport is long polling, explicitly documented as “no SSE” in src/taskloop_dash/static/js/api.js:98-100; src/taskloop_dash/api/live.py:109-124 implements the server wait. Neither replacing owner writes nor inventing SSE is an extraction.

### Release contract for every accepted item

Each candidate below follows these independently releasable steps:

1. Separate the proposed generic body from the named app rule behind the existing import/call seam. Freeze current observable behavior in the app.
2. Transplant the listed portable tests; supply synthetic protocol/filesystem/process fixtures where none were delivered. Shelf tests import no consumer.
3. Release an immutable, namespaced shelf tag; update the app's pinned dependency/vendor artifact to that tag.
4. Replace one reader, parser or transport at a time; retain the app holdouts and previous production pin as rollback.
5. Remove the obsolete body only after parity. Any semantic correction is a separate app release.

In particular, do not regenerate tests/dash/golden/closes.json to make an extraction pass. tests/dash/test_dash_golden.py:27-46 records the close cases, and :78-89 normalizes expected contracts and recomputes versions: therefore also assert literal ETag/hash bytes independently. Land/gate/close behavior, denial precedence, resume accounting and stopped-after-answer behavior must not change silently. No floating shelf branches or production imports from this _shelf checkout.

No tests, applications, git, tracker commands or network operations were run. No credential files were opened. The namespace sandbox could not start shell reads; exact-command escalations allowed the in-tree reads. This review claims inspection/counting, not runtime validation.

## Reuse before new packages

Paths below are the existing implementations/public surfaces, not proposed package names.

| Existing shelf package and public API | Actual fit; missing behavior |
|---|---|
| _shelf/packages/stream-proc/src/stream_proc/__init__.py:14-18: run, stop_tree, alive, proc_start, table, descendants, group_alive, TermHold, popen_held | Already owns process identity, signals and streaming. Extend it for stdin pumping, recovered handles, callback cancellation and suspend-aware watchdogs; do not create another kill-tree implementation. |
| _shelf/packages/any-proc/README.md: one-shot any_proc.run.call; any_proc.supervise.Supervisor and rotate_log | JSON-marker calls and daemon restarts already exist. A single interactive agent session with caller-owned stop rules is stream-proc's capability, not automatic daemon respawning. |
| _shelf/packages/jsonl-log/src/jsonl_log/__init__.py: exports JsonlLog, Jsonl, Entry, append_line, open_append, read_from, tail, expire; cursor.py owns byte offsets | Existing append, rotation and cursors. Missing row-predicate compaction, byte-budget pages/raw-text tails, bounded optional final writes, directory-growth scanning and a multi-source merge. Extend, not another JSONL package. |
| _shelf/packages/atomic-io/src/atomic_io/__init__.py:21-78: atomic_write_bytes/text/json | Already adopted in delegate. Atomic replace is not a locked typed transaction; add the latter above this package. |
| _shelf/packages/process-lock/src/process_lock/__init__.py:104-159: ProcessLock.acquire, release; holder | Already adopted. Kernel-held flock is never broken merely because its recorded PID looks dead. Preserve timeout and non-reentrant thread exclusion. |
| _shelf/packages/any-file/src/any_file/__init__.py:93-109,146: safe_name, resolve_within, media_type; _names.py:58: secret_pattern | Reuse containment, MIME and conventional secret-name recognition. Missing bounded URL-to-static-response behavior and shell exclusion/quoting interpretation. |
| _shelf/packages/http-cache/src/http_cache/__init__.py: HttpCache.get/put, CacheRow, conditional_headers | Cache of fetched HTTP bytes in SQLite. It is neither a Python object cache nor a server response/content-hash engine. Do not distort its contract to absorb either. |
| _shelf/packages/http-fetch/README.md: fetch_bytes, FetchOutcome, FetchVerdict, conditional_headers | HTTP GET transport; no bounded DNS/TCP fact probe, stdio JSON-RPC session or browser polling lifecycle. |
| _shelf/packages/async-scope/src/async_scope/asgi.py:39-197: bind_loopback, serve_asgi; ResourceScope | Existing ASGI lifecycle. The dashboard has threaded servers and all-or-none multi-address binding; switching to ASGI is unnecessary migration scope. |
| _shelf/packages/asgi-token-gate/src/asgi_token_gate/__init__.py: TokenGate, StaticTokenGate, LeaseTokenGate, LeaseSet, stable_token | Auth middleware exists. The dashboard's current access rule is bind restriction, with an explicit no-auth holdout in tests/dash/test_dash.py:59-77. Do not introduce tokens during extraction. |
| _shelf/packages/event-bus/src/event_bus/__init__.py:26-71: EventBus.subscribe/publish/subscribed | Synchronous, in-process notification. Does not replace persistent file cursors, browser subscriptions or cross-process long polling. |
| _shelf/packages/json-in-html/src/json_in_html/__init__.py:83: extract_json_payloads | Extracts JSON from HTML. No corresponding job in serving this dashboard's JSON API. |
| _shelf/packages/lean-wire/src/lean_wire/__init__.py:21-34: encode_tsv, PruneEmpty, prune_dict, dump_model_for_wire | Agent TSV and optional empty-value pruning. Not strict typed decoding, schema projection or preserving ABSENT versus null. |
| _shelf/packages/anyllm/src/anyllm/providers/claude_code_cli.py:30-94: build_argv, ClaudeCodeCliAdapter.complete | Existing subscription completion adapter. It deliberately requests JSON completion output; tool streams, provisional calls and resumable session facts need a separate any-agent-cli capability, composable with anyllm rather than changing complete's meaning. |
| _shelf/packages/app-dirs/src/app_dirs/__init__.py: config_dir/state_dir/cache_dir/plugin_data_dir | XDG lookup and explicit plugin-data opt-in already exist. Missing installed-cache-path to owning-plugin-data derivation. Delegate deliberately ignores the launching plugin's CLAUDE_PLUGIN_DATA. |
| _shelf/packages/child-env/src/child_env/__init__.py: scrub, scrub_current | Already adopted; no fresh env-scrub extraction credit. Preserve keep/drop precedence. |
| _shelf/packages/settings-base/README.md: resolve_env_refs, resolve_config_path, SecretStrippingYamlSource | Config source plumbing exists; no recursive JSON overlay function. App schemas, retired-key handling and profile decisions remain app-owned. |
| _shelf/packages/git-porcelain/src/git_porcelain/api.py:305-448: Repo, Worktree, worktrees, snapshot, history, dirty | Broad git substrate and fake already exist. Delegate additionally wants tolerant upward discovery and a small HEAD/branch fact read. Its worker restriction stays local. |
| _shelf/packages/timefmt/src/timefmt/__init__.py: fmt_dur, fmt_span, fmt_until, human_count | Already used by delegate. Browser number/time formatting needs an explicit JS artifact/parity contract; do not substitute Python rounding semantics. |
| _shelf/packages/verb-cli/README.md: flags_of, to_argparse, kwargs_of | Signature-to-argparse already exists. Delegate's bad_request response/exit-zero convention and verb vocabulary remain its own. |
| _shelf/packages/static-page-check/src/static_page_check/__init__.py: import_problems, page_problems, pin_problems, colour_problems, budget_problems | Already adopted by dashboard static checks. No credit for extracting it again. |
| _shelf/packages/dir-trust/README.md: TrustStore.grant/is_trusted/revoke, folder_hash | Code trust by content hash, not sandbox enforcement or the worker's command permissions. |

Proposed APIs below are target interfaces; additions are not claimed to exist in these packages today. Consumer statements distinguish observed demand from prospective adoption. “Others” never adds speculative consumers to the ranking.

## Accepted extractions

### E1 — ✅ Agent event streams and evidence: 651 runtime lines

**Reuse first / target:** anyllm has completion adapters, but not this event-stream contract. New _shelf/packages/any-agent-cli, with parser modules and shared event types; reuse typed records from E3. Decode CLI facts, tool pairing and usage without choosing a lane or a worker outcome.

**Exact donor spans:** _delegate/src/delegate/contracts/events.py:1-114 (114); adapters/harness/base.py:48-65 (18); adapters/harness/claude.py:16-81 (66),105-182 (78); adapters/harness/codex.py:16-55 (40),80-162 (83); adapters/harness/opencode.py:19-24 (6),42-82 (41),171-275 (105). All paths in that list after the first are relative to _delegate/src/delegate/.

    stream = AgentStream(kind, clock=clock, resume=ref, price_source=source)
    stream.feed(stdout_line, channel="stdout") -> tuple[Event, ...]
    stream.evidence -> Evidence

**Split:** delegate keeps secret_event selection, permissions, lane price selection, Summary-to-RunResult mapping, outcome classification and answer acceptance. OpenCode's provisional rows, Codex reconnect facts, Claude message-id usage deduplication and vendor token normalization belong below that seam. The price source is an input, never inferred from a lane name.

**Consumers:** delegate observed; task-loop's direct agent integrations and anyllm are prospective. Lifesim has no observed CLI-stream reader. No test suite was delivered with delegate: portable existing tests credited **0**, not invented hundreds of lines.

Contracts to own:

- Synthetic streams for all three vendors: unknown/malformed rows, tool start/end pairing and duplicate/incomplete events.
- Claude's first result wins; a message's usage is counted once; a partial stream still records paid usage.
- Codex cumulative resume totals remain facts; caller subtraction and successful-answer decisions stay outside the parser.
- OpenCode provisional starts close the correct calls; policy denial and sandbox failure remain distinct facts.

**Volume/risk/cost:** moved 651; deleted 0; stdlib replacement 0. Risk 3, cost L: changed evidence can stop a valid worker, misreport a denial or double count resumed spend. **Migration:** E3 tag → event-type compatibility exports → one parser at a time with saved synthetic streams → evidence readers → remove old parser bodies. Keep Summary/outcome holdouts in delegate.

### E2 — ✅ Vendor launch, transcript location and probes: 108 runtime lines

**Reuse first / target:** extend any-agent-cli from E1; compose stream-proc and child-env. anyllm.complete does not locate/resume/export CLI sessions or expose login facts. Build vendor argv and locate/probe vendor session artifacts from explicit roots.

**Donors:** _delegate/src/delegate/adapters/harness/base.py:40-44 (5); claude.py:94-103 (10),205-226 (22); codex.py:68-78 (11),185-209 (25); opencode.py:291-325 (35), all in the same harness directory.

    cli = AgentCli(kind, executable, roots, run=transport, auth_probe=probe)
    cli.launch(request, permissions=explicit_permissions) -> LaunchSpec
    cli.transcript(ref) -> Path | None
    cli.export(ref, destination); cli.login_status(timeout) -> LoginFact

**Split:** app retains allowed tools, engine-only recipes, sandbox choice, provider allowlist and OpenCode free-model eligibility. Generic vendor flags consume those decisions. Authentication access is injectable; contract tests use synthetic input and never the owner's auth files.

**Consumers:** delegate observed; anyllm and task-loop prospective; lifesim none observed. Tests moved 0.

Contracts to own:

- Fresh/resume argv preserve stdin placement, schema flags and escaping.
- Missing CLI, malformed probe and timeout produce unknown/error facts, never an inferred logout.
- Transcript discovery, absent exports and write failures preserve current results using temporary fixture roots.

**Volume/risk/cost:** moved 108; deleted/replaced 0. Risk 2, cost M: wrong resume ref or login interpretation. **Migration:** add root/transport injection → tag CLI adapter → replace transcript/probe methods → replace launch assembly with the app permission object still authoritative.

### E3 — ✅ Strict record codec and schema projection: 333 runtime lines

**Reuse first / target:** new typed-record, composing atomic-io for subsequent document support. lean-wire prunes/encodes output; settings-base loads sources; neither supplies this strict wire model. msgspec is already the task-loop implementation option, not proof it exactly replaces delegate's dataclass behavior.

**Donors:** _delegate/src/delegate/contracts/codec.py:1-229 (229), schema.py:1-104 (104). Strictly encode/decode versioned dataclasses and derive contract/structured-output schemas.

    record, mutable, ABSENT
    dump(value) -> dict; load(type, data) -> value
    tagged(types, data, tag="kind") -> value
    schema(type) -> dict; strict(schema) -> dict

**Consumers:** delegate and task-loop have observed codec/schema demand; shelf's config/wire consumers prospective; lifesim none demonstrated. App record definitions and all product schema/golden fixtures remain app holdouts. No existing test lines are credited here.

Contracts to own:

- Wrong version versus bad shape; unknown/missing fields; bool-versus-int; integer preservation inside float fields.
- Aliases, nested versions/tags, scalar wire hooks, ABSENT versus null and deterministic set serialization.
- Schema nullability, enums, nested objects/arrays and unsupported types; strict conversion never mutates the original.
- Compare delegate and msgspec adapters on synthetic records before allowing backend replacement.

**Volume/risk/cost:** moved 333; deleted/replaced 0. Risk 3, cost L: broadened worker schemas or changed on-disk bytes can invalidate live state. **Migration:** codec re-exports → tagged dataclass backend → schema extraction with byte/shape holdouts → optional msgspec consolidation only in a separately validated release.

### E4 — ✅ Locked JSON document transactions: 53 runtime lines

**Reuse first / target:** typed-record document module over atomic-io and process-lock. Existing packages already implement replace/flock; missing capability is typed locked read-modify-write, including failure rollback.

**Donors:** _delegate/src/delegate/contracts/stores.py:27-38 (12),49-65 (17),92-101 (10),174-180 (7),184-190 (7).

    doc = JsonDoc(path, encode, decode, default, lock=lock)
    doc.read() -> Read
    with doc.transaction() as value: ...
    doc.update(change) -> value

**Split:** StateStore.load's retired-key warning and fallback remain delegate policy (:75-90); ConfigStore's profile exclusion and lane mutation remain (:181-182,192-215). Task-loop's strict versus lossy read choices remain explicit, not silently unified.

**Consumers:** delegate and task-loop observed; shelf config stores prospective; lifesim not evidenced. Tests moved 0.

Contracts to own:

- Two threads/processes cannot save a stale snapshot; non-reentrant lock behavior and timeout remain stable.
- Exception during mutation leaves original bytes; replacement is private and uses the existing fsync choice.
- Missing, unreadable, malformed and foreign-version values are distinguishable; fallback belongs to the caller.

**Volume/risk/cost:** moved 53; deleted/replaced 0. Risk 3, cost M: lost holds/config edits or authoritative corruption read as empty. **Migration:** extract transaction mechanism → tag → ConfigStore.update first → StateStore.transaction → preserve warning/fallback adapters and app store tests.

### E5 — ✅ JSONL cursors, raw tails, compaction and capped sinks: 168 runtime lines

**Reuse first / target:** evolve jsonl-log, composing atomic-io/process-lock. Existing cursors and retention cover much of the behavior; no second append-log package. Read incrementally, preserve complete-row byte offsets, compact by predicate and optionally stop an auxiliary stream at a size cap.

**Donors:** src/taskloop_dash/jsonl.py:15-19 (5),22-28 (7),32-62 (31); tails.py:1-52 (52); _delegate/src/delegate/contracts/stores.py:40-46 (7),118-139 (22); app/supervisor.py:89-107 (19); app/publish.py:52-76 (25).

    log = Jsonl(path, decode, max_bytes=budget)
    log.read_from(offset) -> Page; log.tail_bytes(budget) -> list[str]
    log.compact(keep, lock=lock) -> int
    sink = BoundedSink(path, encode, limit, on_error)
    sink.write(value, final=False); sink.close()
    scan = GrowingFiles(root, pattern, initial="end")

**Split:** Beat suppression stays at jsonl.py:29. History retention age, RunRow/cumulative lookup, live event schemas and “never fail a run” error reporting remain app decisions. Inject predicates, encoding and warning callbacks. Source's “limit” Stop becomes a generic matched-line fact, not a lane outcome. Preserve existing damaged-line behavior, including current differences between full-file reads and cursors.

**Consumers:** delegate and task-loop observed; existing shelf JSONL consumers; lifesim log consumers prospective. Tests moved 0 here; multi-file polling tests are counted only in E12.

Contracts to own:

- Unicode byte offsets, malformed complete rows, truncation restart, torn-tail waiting and backlog chunk limits.
- Raw tails discard a leading partial line and bound bytes; typed tail and text tail remain different APIs.
- Append/compact with the same lock loses no accepted record; retained raw rows keep their bytes.
- Capped sinks admit the explicit final record, report a write failure once and never turn it into an authoritative state result.
- Directory scanning starts at the requested position and reports growth without deciding whether text means “rate limited.”

**Volume/risk/cost:** moved 168; deleted/replaced 0. Risk 2, cost M: missing/duplicated live events or lost historical usage. **Migration:** cursor parity/tag → dashboard tail/read adapter → history predicate compaction → generic growth scanner → bounded auxiliary sink; each independently adoptable.

### E6 — ✅ Duplex subprocess execution, identity and watchdog: 158 runtime lines

**Reuse first / target:** extend stream-proc; its catalog already names both donors. any-proc's daemon restart behavior is not this one-run transport. Own piped stdin, concurrent drains, parent-death cancellation, recorded identities and configurable silence deadlines.

**Donors:** _delegate/src/delegate/adapters/procs.py:22-51 (30),83-91 (9); app/watch.py:94-139 (46); app/supervisor.py:174-246 (73).

    handle = spawn(argv, cwd, env, stdin=payload)
    handle = recover(pid, start, pgid)
    result = run(argv, stdin=payload, on_stdout=out, on_stderr=err, stop=stop)
    watchdog = Watchdog(first, silence, suspend_gap, clock, heartbeat)
    watchdog.touch(); watchdog.poll() -> Deadline | None

**Split:** keep WorkerEnd/outcome folding in procs.py:53-80, watcher ordering and Turn rules in supervisor.py:124-171, and finish/answer interpretation in :248-258. App chooses CLI-specific limits, when parent change means cancel, heartbeat effects and stop-report mapping. The generic wait loop accepts these as parameters/callbacks.

**Consumers:** delegate and task-loop observed; lifesim's process runners prospective; anyllm transport prospective. Tests moved 0; do not count stream-proc's existing process-table implementation again.

Contracts to own:

- stdin larger than pipe capacity while stdout/stderr flood: no deadlock, complete EOF and torn-line flush.
- PID reuse and unknown start token do not kill a replacement process; recovery has explicit identity semantics.
- SIGTERM during spawn/wait, timeout and cancellation stop the owned tree and restore handlers/close descriptors.
- Suspend gaps do not consume silence budget; sticky deadline and heartbeat throttling match current behavior.

**Volume/risk/cost:** moved 158; deleted/replaced 0. Risk 3, cost L: orphan workers, accidental signals or altered answer/grace behavior. **Migration:** add stdin + capture contracts/tag → run_capture → piped spawn/recovery → suspend-aware watchdog → generic wait loop with app stop callbacks. Keep current inferred kill_sent behavior until a separate report-contract change is approved.

### E7 — ✅ Shell text interpretation and exclusion-aware matching: 147 runtime lines

**Reuse first / target:** extend any-file's secret-name recognition with a shell interpretation module, or a shell-text package if that surface would distort any-file. Existing secret_pattern does not understand excluded globs, quoting, loops or heredocs. Keep a single conventional-path matcher, not two diverging secret lists.

**Donors:** _delegate/src/delegate/domain/policy/matchers.py:1-137 (137); shell.py:21-26 (6),90-93 (4).

    parsed = ShellText(command)
    parsed.commands() -> list[list[str]] | None
    parsed.match_paths(predicate, ignore_exclusions=True) -> Hit | None
    parsed.heredoc_only(predicate) -> bool
    parsed.redirects_or_substitutes() -> bool
    git_args(words); after_assignments(words)

**Split:** shell.py's allowed commands, git-is-coordinator rule, recipe runner list and own-PID exceptions remain local. worker.py still decides blocked/reason. Shelf exposes syntax facts and takes a path predicate; it is not advertised as an adversarial shell security boundary.

**Consumers:** delegate observed; task-loop's hook and shelf command tooling prospective; lifesim none proven. Tests moved 0.

Contracts to own:

- Quoted/escaped separators, nested sh -c, assignments and loop headers preserve command boundaries.
- Exclusion flags, negative find predicates and git pathspec exclusions do not count as accessed files.
- Malformed text is an explicit parse failure; heredoc mentions and real command accesses remain distinguishable.
- Current redirection/substitution heuristics are pinned, rather than “fixed” as part of relocation.

**Volume/risk/cost:** moved 147; deleted/replaced 0. Risk 3, cost M: false permission decisions. **Migration:** match/parsing fixtures → tag → pieces/unwrap replacement → exclusion/path matching → retain exact app verdict comparisons.

### E8 — ✅ Declarative command-sandbox compiler: 42 runtime lines

**Reuse first / target:** dir-trust hashes trusted code and child-env scrubs inherited variables; neither compiles an execution sandbox. New command-sandbox, composing child-env/app-dirs rather than duplicating them. Compile a caller-supplied filesystem/network grant into the existing macOS shell wrapper and preflight it.

**Donors:** _delegate/src/delegate/adapters/harness/opencode_sandbox.py:48-53 (6),60-69 (10),72-83 (12),86-99 (14). Explicitly exclude :70-71, which choose task-loop's .task scratch root and default writable directories.

    plan = SandboxPlan(read_roots, write_roots, denied_paths, network)
    compile_shell(plan, shell, restored_config, path) -> None
    preflight(run, platform) -> Problem | None
    cache_env(root) -> dict[str, str]

**Split:** app supplies SECRETS, .task, cache exceptions, environment restoration choice, read-only/write role and permission table. Do not export opencode_sandbox.py:22-46's task-loop runs directory or engine-only recipe rules.

**Consumers:** delegate observed; task-loop and other shelf command hosts prospective; lifesim not demonstrated. Tests moved 0.

Contracts to own:

- Profile quoting handles spaces and punctuation without broadening allowed roots.
- Cache exceptions are narrower than denied parent roots; read-only workspace and scratch remain distinct.
- Preflight is cached only under the documented scope; nested-sandbox failure is a value.
- Synthetic profile fixtures pin network denial and file mode; OS-specific enforcement tests precede adoption.

**Volume/risk/cost:** moved 42; deleted/replaced 0. Risk 3, cost M: worker gains unintended read/write/network access. **Migration:** parameterize app grants → profile golden fixtures → platform preflight contracts/tag → adopt compiler while retaining app permission generation. No speculative Linux backend receives credit.

### E9 — ✅ Bounded DNS/TCP network facts: 120 runtime lines

**Reuse first / target:** new net-probe over stdlib socket/threading plus atomic-io; http-fetch does HTTP and does not bound blocking DNS across hosts. Probe connectivity within one global deadline and retain an optional stale-aware cached fact.

**Donor:** _delegate/src/delegate/adapters/netprobe.py:1-120 (120).

    probe(hosts, budget_s, connect_s, resolve, connect, clock) -> Probe
    record(path, probe, clock) -> CachedProbe
    view(cached, hosts, now, fresh_s) -> Availability
    looks_dropped(vendor_error) -> bool

**Consumers:** delegate observed; task-loop outage reporting and shelf network clients prospective; lifesim not observed. Tests moved 0.

Contracts to own:

- One blocked resolver cannot extend the whole deadline; tested hosts retain independent DNS/TCP/slow facts.
- DNS outage differs from offline/vendor refusal; supplied hosts and fallback IP are not conflated.
- Cache freshness, host subset projection and outage-since timestamps preserve existing semantics.
- Vendor error matching excludes the documented max_output_tokens false positive.

**Volume/risk/cost:** moved 120; deleted/replaced 0. Risk 1, cost S for extraction, with explicit app outage/stop holdouts: misreported connectivity could otherwise pause work. **Migration:** injected resolver/connect tests → tagged primitive → probe replacement → cached status projection. No real network is needed for logic contracts.

### E10 — ✅ Vendor usage and transcript readers: 164 runtime lines

**Reuse first / target:** extend any-agent-cli's vendor modules from E1/E2; compose jsonl-log/stream-proc/atomic-io. Existing anyllm accounting does not read CLI rollout files, Claude status-line handover or Codex's app-server exchange. Read vendor facts and provenance; never mark a lane out.

**Donors:** _delegate/src/delegate/adapters/codex_account.py:1-134 (134), statusline.py:1-30 (30).

    usage = AgentUsage(kind, roots, rpc=transport, clock=clock)
    usage.limits(timeout) -> LimitsFact
    usage.total(ref) -> Tokens | None
    usage.children(ref, since) -> ChildUsage
    usage.context(ref) -> float | None
    usage.capture_statusline(payload, at)

**Split:** roots/executables are inputs. app/usage.py retains freshness selection among manual/cache/live sources, lane labels, burn thresholds, 98%/95% cutoff rules and out_until. The stdio JSON-RPC exchange moves with this vendor adapter; its initialize client identity becomes a parameter. No auth/rollout files on this machine are read for the review or for package tests.

**Consumers:** delegate observed; task-loop usage views and anyllm prospective; lifesim none demonstrated. Tests moved 0.

Contracts to own:

- JSON-RPC notification noise, partial frames, nonmatching ids, EOF and total deadline; child cleanup on every exit.
- Synthetic rollout layouts cover parent/child totals, missing final counts, date boundaries and bounded context tails.
- Status-line missing/stale/malformed readings remain unknown, not zero usage.
- Resume totals and cache-read/write counts retain their units and provenance.

**Volume/risk/cost:** moved 164; deleted/replaced 0. Risk 2, cost M: double charged resume totals or exhausted lanes presented as available. **Migration:** fixture-only readers/tag → statusline → rollout queries → RPC reader → preserve app fleet/usage comparisons.

### E11 — ✅ Vendor reset-time prose parser: 66 runtime lines

**Reuse first / target:** extend any-agent-cli with reset parsing. timefmt renders time; due-schedule handles schedules, not vendor prose. Parse a stated reset/retry time without selecting a fallback.

**Donor:** _delegate/src/delegate/adapters/harness/reset_parse.py:1-66 (66).

    parse_reset(message, now) -> tuple[float | None, str | None]

**Split:** :69-81's limit_until remains delegate's rule: vendor reset, then lane limit_reset, then a 15/30/60-minute guessed ladder. The unused-in-parser ladder constant in the donor prefix stays an app argument/constant after separation; no shelf retry decision follows from it.

**Consumers:** delegate observed; shelf HTTP/agent clients prospective; task-loop consumes the resulting facts indirectly; lifesim none. Tests moved 0.

Contracts to own:

- Retry-After seconds/HTTP date; ISO timestamps and explicit signed offsets.
- Local-time AM/PM rollover, relative mixed units and clock/DST fixtures.
- Past and implausibly distant times remain absent under an explicit horizon.

**Volume/risk/cost:** donor envelope 66, including imports/comments; deleted/replaced 0. Risk 2, cost S: wrong rest interval. **Migration:** temporal fixtures → tag parser → replace parse_reset only; leave limit_until and its ladder local.

### E12 — ✅ Multi-file cursor merge and long-poll engine: 121 lines

**Reuse first / target:** extend jsonl-log with a multi-source reader. event-bus is in-process notification; http-cache/http-fetch do not preserve file offsets. Merge projected records by a supplied ordering key and wait for new content without changing the transport.

**Runtime donors:** src/taskloop_dash/api/live.py:26-38 (13),44-53 (10),59 (1),74-98 (25),102-124 (23): **72**. **Tests:** tests/dash/test_dash_live.py:64-89 (26),118-140 (23): **49**, transplanted against synthetic source/projector inputs. Keep the original app integration assertions too if they verify engine event mapping.

    feed = MergedFeed(sources, discover, decode, project, order, clock)
    feed.refresh(); feed.offsets() -> dict[str, int]
    feed.page(cursor=None, limit=limit) -> Page
    feed.poll(cursor, wait, sleep) -> Page
    encode_cursor(offsets); decode_cursor(text)

**Split:** RunBundle paths, engine-first tie ranking, Beat filtering, worker-event projection and live/ended run state stay app-owned. Supply them as callbacks; no shelf import of log, RunBundle or views.live_events.

**Consumers:** task-loop dashboard observed; delegate transcript tooling and shelf log viewers prospective; lifesim none observed.

Contracts to own:

- Stable source+offset identity, equal-time ordering, first-page limit and opaque cursor round-trip.
- Truncation resets a source; torn rows wait; source discovery adds files without resetting unrelated offsets.
- Initial fetch never waits; no growth exhausts the bound; growth returns on the next injected tick.

**Volume/risk/cost:** runtime 72 + tests 49 = 121; deleted/replaced 0. Risk 2, cost M: duplicate/missing live lines or stuck requests. **Migration:** cursor contracts/tag → generic Source reader → merge/page → polling wait; keep tests/dash/test_dash_live_page.py as product holdout. Preserve current server wait cap of 20 seconds even though the browser requests 25.

### E13 — ✅ Object TTL and file-fingerprint caches: 72 runtime lines

**Reuse first / target:** new object-cache unless reconciliation identifies an equivalent catalog capability. http-cache is a persisted fetched-response cache; it is not this object loader. Hide locking, timestamps, file stat invalidation and LRU eviction behind two objects.

**Donor:** src/taskloop_dash/cache.py:1-72 (72).

    TtlCache(clock).get(key, ttl, make)
    TtlCache.peek/put/drop/clear(...)
    FileCache(limit).get(path, load, missing=None)

**Consumers:** dashboard observed; delegate usage/login and shelf readers prospective; lifesim none proven. Tests moved 0.

Contracts to own:

- Injected clock covers hit, expiry, overwrite and explicit invalidation.
- File size/mtime change reloads; missing file drops the cached entry; LRU order and limit hold.
- Concurrent miss semantics match current behavior: loaders can run twice; extraction must not silently introduce single-flight or a stronger file fingerprint.

**Volume/risk/cost:** moved 72; deleted/replaced 0. Risk 1, cost S: stale display/cache contents. **Migration:** cache contracts/tag → file readers → TTL readers; any monotonic-clock or nanosecond-stat improvement is separate.

### E14 — ✅ HTTP response, static serving and binding mechanics: 145 lines

**Reuse first / target:** evolve any-file for bounded static responses; new local-http for stdlib handler/conditional-response/multi-bind mechanics. async-scope already owns ASGI lifetime but does not fit this server. Keep http-cache, http-fetch and asgi-token-gate in their existing roles.

**Runtime donors:** src/taskloop_dash/assets.py:16-36 (21); http.py:50-67 (18),73-82 (10),86-87 (2); bind.py:96-108 (13); api/reads.py:21-35 (15); views/snapshot.py:109-113 (5): **84**. **Tests:** tests/dash/test_dash_assets.py:1-61 (61), using package static-response inputs and the app deny list as explicit configuration.

    static_response(root, url, types, deny, max_bytes) -> Response
    handler(get, post, error, body_limit, headers) -> Handler
    bind_all(addresses, port, handler, server_factory) -> Servers
    conditional_json(value, encode, version, held, since) -> Response
    content_hash(value, encode, omit) -> str

**Split:** route paths, /api/version payload, POST verb dispatch, allowed bind addresses, default port, installed-copy guards, repo registration, denied dev filenames and hash omissions remain app parameters/rules. Never import Dash into local-http.

**Consumers:** task-loop observed; delegate's future local cockpit and shelf local UIs prospective; lifesim none demonstrated.

Contracts to own:

- URL decoding, symlink containment, hidden/dev filenames, extension/MIME and size limits match existing static behavior.
- All addresses bind or every opened server closes; ephemeral port is reused across the set.
- JSON/errors/headers and conditional 304 bytes are stable; query-token precedence and hash bytes match current answers.
- POST length/JSON failure behavior is pinned before any deliberate hardening; no new auth, request semantics or owner action is introduced.

**Volume/risk/cost:** runtime 84 + tests 61 = 145; deleted/replaced 0. Risk 3, cost M: accidental public binding, file disclosure or changed owner writes. **Migration:** static-response contracts/tag first → adopt static adapter → generic conditional response → generic handler with existing routes → all-or-none binder. Preserve NoAuth, bind and writes integration tests locally.

### E15 — ✅ Browser polling, safe formatting and native UI mechanics: 323 runtime lines

**Reuse first / target:** browser artifacts under new polling-resource and native-ui capabilities; evolve timefmt with explicitly browser-compatible format contracts. event-bus is Python-only and synchronous; json-in-html extracts from pages rather than rendering; static-page-check already verifies assets but provides no widgets.

**Donors:** src/taskloop_dash/static/js/api.js:1-10 (10),12-27 (16),29-128 (100): **126**; format.js:8-38 (31),50-84 (35): **66**; ui/kit.js:7-28 (22),43-59 (17),65-69 (5),115-120 (6),123-203 (81): **131**. Total **323**.

    resource = pollResource(url, versionOf, onChange, clock, fetch)
    resource.start/stop/retry/subscribe(...); tail = pollCursor(fetchPage, onPage)
    format.duration/age/count/day(...); safeMarkdown(text)
    Dialog({open, onClose, children}); Popover(...); Toast(...)
    controls({items, selected, onPick}); Ring(...); Spark(...)

**Split:** api.js:11's snapshot resource and :28's server-version reload decision stay app-owned, as do route/schema callbacks and “ended” interpretation. format.js:3-6,40-48 keep bead markers, tones and project IDs. kit.js:30-41,61-63,71-113 keep landed-sample thresholds, phase dots, marker/status policy and bead cards. Generic widgets accept already chosen text/tone and callbacks.

**Consumers:** dashboard observed; shelf local pages prospective; delegate has no delivered browser caller; lifesim's HTML reports are prospective, not confirmed reuse. Existing browser tests remain app holdouts; portable test credit 0. CSS relocation requires a separate measured audit and is excluded here.

Contracts to own:

- Fake browser clock/fetch: hidden tabs, focus refresh, one pending request, 304 age semantics and capped failure backoff.
- Cursor polling stop/unmount, visibility wait, minimum retry interval and unchanged-cursor suppression.
- HTML escaping precedes markdown formatting; malformed input cannot introduce script/attribute execution.
- Dialog Esc/backdrop/focus, popover behavior, toast replacement and timer cleanup; JS rounding/day-boundary fixtures.

**Volume/risk/cost:** moved 323; deleted/replaced 0. Risk 1, cost M for mechanism relocation with app action holdouts retained: stale browser state or broken controls. **Migration:** portable ES-module contract harness → tagged assets with content pins → pure formatters → native dialogs/controls → polling engine → app hooks/adapters. Do not copy the dashboard's route/record model into a UI framework.

### E16 — ✅ Process simulator and test I/O guard: 308 test/support lines

**Reuse first / target:** stream-proc.testing, with subprocess.run simulation and pytest integration behind a testing extra. git-porcelain already supplies its own real/fake contract harness; do not create another git fake here. Simulate command/time results and make unintended real process work fail deterministically.

**Donors:** tests/support/procsim.py:1-32 (32),54-89 (36),97-124 (28),127-249 (123): **219**; tests/rules/test_procsim.py:1-71 (71); tests/rules/real/test_procsim.py:1-18 (18): **89**. Total **308**.

    world = ProcessWorld(guarded, defaults, forbidden_commands)
    world.install(exit_stack); world.check(require_io=False)
    world.fake(argv, result, prefix=False); world.ran(argv)
    exits(code, output); takes(seconds, then); blocks(output)

**Split:** procsim.py:33-53's f.txt/conflict-marker checks, :90-96's factory defaults and :125-126's tl-nobd stub decision stay local: **30 retained lines**. Inject defaults/forbidden-command rules. App conftest continues deciding which test paths are logic/real/e2e; the package does not know tests/land or the factory's test-kind layout.

**Consumers:** task-loop observed; delegate and lifesim's process-helper tests prospective; other shelf process packages prospective.

Contracts to own:

- subprocess and streamed calls receive identical fake cwd/env/exit/timeout facts; bytes/text/check behavior matches.
- Unregistered spawn/fork fails guarded logic tests; swallowed errors still fail at world teardown.
- Scoped installation restores patches/world state after exceptions and prevents cross-test leakage.
- Blocking fake cancels without real sleep; a declared real test can require actual I/O.

**Volume/risk/cost:** moved 308; deleted/replaced 0. Risk 2, cost M: a false-green factory suite. **Migration:** tag the simulator with its 89 own test lines → install through existing app conftest adapter → migrate default registrations → retain app-specific fake git/beads/engine harnesses.

### E17 — ✅ Config overlay and installed-plugin path derivation: 15 runtime lines

**Reuse first / target:** extend app-dirs for owning-plugin path derivation and settings-base for recursive JSON overlay. Neither existing API supplies those two remaining mechanisms; child-env already covers scrubbing.

**Donors:** _delegate/src/delegate/app/env.py:33-41 (9),57-62 (6).

    installed_plugin_data(code_path) -> Path | None
    overlay(base_mapping, overrides) -> dict

**Split:** config_dir :44-54 keeps DELEGATE_CONFIG_DIR priority, checkout refusal and private creation; :67-101 keeps routing validation/retired-key diagnostics. Do not replace it with platformdirs defaults: that changes storage location and ownership.

**Consumers:** delegate and task-loop observed path/config demand; shelf plugin hosts prospective; lifesim not evidenced. Tests moved 0.

Contracts to own:

- Installed path derives the owning plugin identity; checkout returns absent; identity sanitization is stable.
- Launcher's CLAUDE_PLUGIN_DATA cannot redirect this derivation.
- Overlay deep-copies defaults, recursively combines dictionaries and replaces scalar/list values exactly.

**Volume/risk/cost:** moved 15; deleted/replaced 0. Risk 2, cost S: state split between directories or changed config precedence. **Migration:** app-dirs tagged addition → derive path → settings-base tagged overlay → deep_merge replacement; no profile/schema migration.

### E18 — ✅ Git discovery and identity facts: 24 runtime lines

**Reuse first / target:** evolve git-porcelain's Repo/Worktree facts, discovery and failure handling; it already has a fake and broad worktree API. Find a repository and read HEAD/current branch without exporting the worker guard.

**Donor:** _delegate/src/delegate/adapters/git.py:1-24 (24).

    repo = discover(cwd, missing="cwd")
    repo.identity() -> HeadBranch | None

**Split:** git.py:27-36's “worker must leave HEAD and branch unchanged” comparison is delegate policy. Worktree creation, land sequencing, lease pushes and gate choices do not migrate with this reader.

**Consumers:** delegate and task-loop observed; _lifesim_tools/changed.py:65-96 demonstrates a third git discovery/query demand; existing shelf git users. Lifesim adoption must retain its fail-closed changed-input decision. Tests moved 0.

Contracts to own:

- Missing git, non-repository, detached HEAD and unborn branch preserve current fact/fallback distinctions.
- Upward discovery handles worktrees and paths containing spaces.
- Synthetic runner failures cannot become authoritative clean-repository facts; app-specific fallback remains explicit.

**Volume/risk/cost:** moved 24; deleted/replaced 0. Risk 3, cost S: wrong repository or an undetected coordinator-owned git change. **Migration:** discovery/identity contracts in existing real/fake suite → tagged addition → read adapter → keep changes(before, after) locally.

## Refusals and required wider coverage

### R1 — ❌ Exporting the delegate's decision program: 468 inspected domain lines

**Files:** _delegate/src/delegate/domain/routing/dwell.py:1-22 (22), picker.py:1-26 (26), router.py:1-164 (164), tiers.py:1-67 (67); domain/holds/book.py:1-78 (78); domain/policy/worker.py:1-65 (65); adapters/harness/classify.py:29-74 (46). Sum **468**.

**What it does:** chooses permitted lane/model/step, applies owner holds and turns worker evidence into the factory's stop reason. **Target:** remain delegate. No existing shelf package should acquire these rules. In particular, tier order is requested premium, non-Claude, then Claude; a hold applies to selected roles until expiry and can raise one stale-use ask; the classifier orders secret/watchdog/timeout/vendor facts into the contract's reason vocabulary.

    Router.decide(...); Router.resume(...)
    HoldBook.for_role(...); HoldBook.release(...)
    worker.judge(...); classify(...) -> contract reason

**Consumers:** delegate; task-loop consumes the external worker contract, not an independent generic scheduling library. Lifesim and shelf have no demonstrated need for these exact decisions.

Retained app contracts:

- Hold coverage/expiry/stale prompt and dwell decisions remain unchanged.
- Premium/relaxed/family ordering is deterministic for the same routing table.
- Secret, timeout, denial and vendor failures retain reason precedence and caller effects.

**Moved/deleted/replaced: 0/0/0. Risk of moving wholesale: 3. Migration: none.** E1/E7/E11 extract protocol parsing underneath it; refusal is of these named rules, not their current dependencies or generic helper algorithms.

### Required cross-lens dispositions

These are explicit boundaries, not extra savings added to B2. The source anchors were inspected; larger mixed envelopes without a complete portable slice remain ❓ rather than being mislabeled all-domain.

| Required area | Verdict and concrete boundary |
|---|---|
| Atomic JSONL/state; JsonStore/msgspec | ✅ E3-E5. packages/kernel/src/tlkernel/stores.py:44-121 exposes Present/Absent/Torn/ForeignVersion and JsonStore.read/get/need; its 559-line whole-file envelope is U4 below. msgspec is the existing task-loop backend, not an automatic delegate compatibility guarantee. |
| Locks/stale PID; process/exec/PID fence/kill tree | ✅ E4/E6. process-lock's kernel ownership must not be replaced by stale-PID deletion. src/taskloop/adapters/pidcheck.py:1-16 already delegates to process identity functions; it is compatibility glue, not another 16-line killing engine. |
| Subprocess/log capture | ✅ E5/E6/E16, including the previously mixed Supervisor pump/wait code. Caller-selected stop reasons and finished-answer policy stay in the app. |
| Git/worktrees | ✅ E18 and existing git-porcelain. Task-loop's lease-push, land gate and cleanup eligibility remain application decisions; no new mutation scope is hidden in this read migration. |
| bd client | ❌ src/taskloop/adapters/bd.py:1-276 as a whole: app BeadStore mapping and typed lifecycle commands know beads. Its subprocess mechanism belongs to E6; claim/close semantics do not. A separate vendor bd protocol package needs its own broader lens and contracts, not blind relocation of the factory adapter. |
| Path/layout/config directories | ✅ E17/app-dirs. ❌ packages/kernel/src/tlkernel/paths.py:16-288 as a public shelf layout: names engine logs, hooks, slots and run manifests. Existing default_root :10-12 is a small app-dirs adoption seam, not hundreds of generic layout lines. |
| Version hop/reexec/self-update | ❌ src/taskloop/app/release/reexec.py:20-70 as a reusable decision engine: consume-once notes, 120-second fallback, network pause adoption and run-task argv changes encode recovery rules. Its :73-76 process replacement is os.execve plus app log shutdown; use stdlib directly, no invented reexec package or savings claim. |
| Retry/backoff/rest tables | ✅ E11 extracts stated reset parsing. ❌ _delegate/.../reset_parse.py:69-81's fallback ladder and src/taskloop/domain/lanes/retry.py:30-38's fault/ask/reroute decisions. A generic table-indexing engine can later take rests/limits as data; no new scheduling policy belongs in shelf. |
| IDs/ULID/run IDs | ✅ Generic ULID layout in packages/kernel/src/tlkernel/ids.py:31-88 is a B1 extraction candidate, not B2 credit. Use a shelf opaque-id or contract-tested ULID implementation; retain BeadId grammar, repo_key/loop_key and MARKETPLACE as app identity rules. Never infer that uuid.uuid4's eight-character hold ID is the same contract. |
| Tail/log/transcript/usage readers | ✅ E1/E5/E10/E12. ❌ app/usage.py:50-80,127-169's lane exhaustion, burn and provenance selection rules. Vendor bytes move, decisions from them do not. |
| HTTP/static/SSE/polling | ✅ E12-E15. No SSE exists to move; bind allowlist and owner POST meaning remain app policy. Existing ASGI auth is not adopted implicitly. |
| CLI scaffolding, ANSI, tables, time/size, TUI | ✅ verb-cli/timefmt existing supply, E15 browser mechanisms. ❌ _delegate/src/delegate/cli/parser.py:32-72's run bad_request-as-exit-zero contract and verb grammar. ❌ app/cockpit.py's action/needs-input decisions as a wholesale TUI package; generic formatting must be split from those decisions, not refused merely because the current file mixes them. |
| Config/profile loading | ✅ E3/E4/E17 for mechanism. ❌ packages/kernel/src/tlkernel/config.py:31-42,169-253,369-411's slot placeholders, engine schema and factory validation choices; _delegate/src/delegate/app/env.py:67-101 retains retired-setting and profile rules. settings-base/msgspec can own loaders; pydantic/platformdirs migration is untested and changes contracts/paths unless proved otherwise. |
| Policy matchers/shell parsing | ✅ E7/E8; ❌ worker admission, coordinator-only git, engine-only recipes and allowed-command tables remain app rules. |
| Test fixtures/fakes/contracts/goldens | ✅ E12/E14/E16 portable tests/support move with capabilities. Existing git fake stays with git-porcelain; static-page-check is already extracted. ❌ factory records, close goldens, app fake hosts and stage fixtures keep their product meaning. U1-U4 below identify mixed large envelopes requiring tests before a larger count. |

The table does not count standard library calls as lines “replaced” merely because a new package will use socket, json, hashlib or subprocess internally.

### ❓ Untested larger mixed envelopes, with acceptance experiments

These are follow-on extraction investigations, not a refusal on cost or caller count. Existing source/test envelopes total **2,632** disjoint lines, with **zero approved relocation credit**; the experiment must identify/count portable ranges rather than move the whole envelope. Interfaces below are proposed seams, each under six lines.

- **U1 — tests/support/engine_case.py:1-765 (765).** Existing stream-proc.testing/E16 and git-porcelain.testing cover process/git substrates; missing is isolated fixture lifecycle, not an EngineTest library. Proposed interface: FixtureWorld(root, clock, process_world).enter/close. Consumer: task-loop observed; delegate/lifesim prospective. Tests needed: teardown after partial setup; nested worlds cannot leak env/global patches; fixture git facts match real/fake behavior. App keeps EngineTest's bead/run/stage constants and outcomes. Migration: split fixture lifecycle → transplant its own tests → tag testing extra → adopt without moving factory scenarios. Risk 2; cost L; 0 moved/deleted/replaced until measured.
- **U2 — tests/rules/gate_rules.py:1-726 (726).** Existing static-page-check handles web assets, not Python AST/tokenize rules. Missing generic rule scan/ratchet engine could become source-audit. Proposed interface: scan(paths, rules) -> Problems; ratchet(actual, baseline) -> Problems. Consumers: task-loop observed, delegate/lifesim/shelf prospective. Tests needed: planted violations with arbitrary package names; docstring/SLOC accuracy; shrink-only baseline and deterministic diagnostics. App retains caps, exemptions, allowed folders and vendor manifest policy. Migration: generic scanner plus planted tests → tag → app rule declarations. Risk 2, cost L; zero credited until scanner/test spans are separated.
- **U3 — dev/dash_check.html:1-582 (582).** static-page-check is static analysis; missing browser scenario/viewport mechanics could become browser-contract. Proposed interface: runPage(url, viewport, scenario) -> Assertions. Consumer: task-loop observed; shelf UI artifacts/lifesim HTML reports prospective. Tests needed: iframe sizing and focus; isolated storage/clock; planted browser failure reaches the runner. App keeps board/bead/owner-action assertions. Migration: isolate browser runner → synthetic page contracts → tagged test artifact → retain app scenarios. Risk 2, cost M; zero credit until generic runner ranges are measured.
- **U4 — packages/kernel/src/tlkernel/stores.py:1-559 (559).** atomic-io/process-lock/jsonl-log already cover the primitives, E3/E4 supply typed-document seams. Missing here is a package test proving strict read outcomes and keyed document families independently of AskStore. Proposed interface: JsonDoc(path, codec).read/need/write; DocSet(path_of, codec).of/keys. Consumers: task-loop and delegate observed; shelf stores prospective. Tests needed: filesystem/memory parity for all four read outcomes; torn data cannot become empty authority; unknown keys/temp files and interrupted replacement. App keeps answer/amend/consume/park/stuck lifecycle rules. Migration: generic document contracts → tagged capability → app wrappers → preserve AskStore tests. Risk 3, cost L; B1 owns the additional donor ledger, B2 credits zero to avoid duplicate totals.

## Largest 25 remaining files

No accepted span removes lines from these 25 files. Therefore this is also the exact size ordering after the proposed B2 relocations. Each size is wc -l; cited first lines and named definitions were reread. “Refuse” means keep the domain assertions/data, not forbid subsequent extraction of a measured generic helper.

| Rank | Remaining file:range | Lines | Verdict and named rule / required experiment |
|---|---|---:|---|
| 1 | tests/dash/golden/closes.json:1-2927 | 2,927 | ❌ Exact close/ask/park/fault display contract; holdout stays with the factory. |
| 2 | tests/fixtures/dash/snapshot.json:1-2341 | 2,341 | ❌ Product snapshot shape and scenarios; not generic HTTP fixture data. |
| 3 | tests/contracts/golden/records.json:1-1826 | 1,826 | ❌ Factory record wire bytes, including epic/run/slot meanings. |
| 4 | _delegate/skills/delegate/contract.json:1-1749 | 1,749 | ❌ Contract-3 stop facts, scopes and accepted run flags define the worker contract. |
| 5 | tests/fixtures/dash/mock-8b.json:1-1045 | 1,045 | ❌ Bead/slot/lane/owner-look scenarios; no shelf consumer owns these facts. |
| 6 | tests/loop/real/test_loop.py:1-915 | 915 | ❌ Loop selection/run/stop policy and real factory integration. |
| 7 | tests/run/test_engine_run.py:1-828 | 828 | ❌ Run resume/stop/budget/log effects; transport fixtures can call E16 without exporting these assertions. |
| 8 | tests/run/test_stages.py:1-817 | 817 | ❌ Stage handoff and acceptance semantics. |
| 9 | tests/support/narrow_hosts.py:1-777 | 777 | ❌ Typed slice hosts encode land/gate/close ports and expected effects; generic process fake belongs to E16. |
| 10 | tests/support/engine_case.py:1-765 | 765 | ❓ U1: isolate fixture lifecycle; keep EngineTest's factory scenario DSL. |
| 11 | tests/land/test_engine_land_1.py:1-752 | 752 | ❌ Land/push/rebase/conflict-fix behavior, required app holdouts. |
| 12 | tests/rules/gate_rules.py:1-726 | 726 | ❓ U2: prove scanner independent of app folder names and rule constants. |
| 13 | tests/run/test_stages_visual.py:1-717 | 717 | ❌ Visual review/claim/resume-count rules. |
| 14 | tests/land/test_stages_land.py:1-706 | 706 | ❌ Stale-tree/slot/dead-lane/follow-up decisions. |
| 15 | skills/task-loop/SKILL.md:1-674 | 674 | ❌ User-facing factory method: claim, plan, verify, land and close. |
| 16 | tests/run/test_engine_units.py:1-652 | 652 | ❌ Failure briefs, outcomes, confirmations and worker-launch integration. |
| 17 | tests/land/test_race_invariants.py:1-640 | 640 | ❌ Claim, lock, push and release ordering invariants; retain sabotage-sensitive holdouts. |
| 18 | tests/contracts/samples.py:1-600 | 600 | ❌ Filled factory record instances; shelf gets synthetic records instead. |
| 19 | dev/dash_check.html:1-582 | 582 | ❓ U3: separate viewport/browser runner from dashboard scenario assertions. |
| 20 | tests/e2e/test_release.py:1-570 | 570 | ❌ Suite authority, publication, rollback and launcher reexec semantics. |
| 21 | packages/kernel/src/tlkernel/dash.py:1-562 | 562 | ❌ Product GET/POST wire vocabulary for beads, slots, asks and lanes. |
| 22 | packages/kernel/src/tlkernel/stores.py:1-559 | 559 | ❓ U4: generic JsonStore/DocSet and product AskStore must split; whole-file refusal would be wrong. |
| 23 | tests/land/test_stack.py:1-549 | 549 | ❌ Ordered land-stack delivery, first-failure stop and commit recording. |
| 24 | tests/plan/test_engine_plan.py:1-546 | 546 | ❌ Plan/replan acceptance and engine effects. |
| 25 | tests/support/dash_fixtures.py:1-527 | 527 | ❌ Builder maps mock beads/runs/asks to the product contract; :93 marker and :223 passes are domain rules. |

What exactly remains globally is the original census file set minus the disjoint E1-E18 spans: **140,614 physical lines before replacement adapters**. The table names the 25 largest. Files outside B2 are not automatically refused: U1-U4 and the cross-lens seams explicitly preserve additional extraction work. A global 50% pledge would otherwise count unexamined engine tests, product goldens or already-vendored packages as generic savings.

## Totals

| Verdict/category | Runtime moved | Test/support moved | Dead/duplicate deleted | Replaced by stdlib/third party | Total moved out |
|---|---:|---:|---:|---:|---:|
| ✅ E1-E18 | 2,600 | 418 | 0 | 0 | **3,018** |
| ❌ R1 named decision program, 468 inspected lines | 0 | 0 | 0 | 0 | 0 |
| ❓ U1-U4, 2,632-line investigation envelopes | 0 | 0 | 0 | 0 | 0 |

| Extraction | Runtime | Tests/support | Total |
|---|---:|---:|---:|
| E1 event stream | 651 | 0 | 651 |
| E2 CLI/session I/O | 108 | 0 | 108 |
| E3 codec/schema | 333 | 0 | 333 |
| E4 document transactions | 53 | 0 | 53 |
| E5 JSONL/tail/compaction/sinks | 168 | 0 | 168 |
| E6 process/watchdog | 158 | 0 | 158 |
| E7 shell interpretation | 147 | 0 | 147 |
| E8 sandbox compiler | 42 | 0 | 42 |
| E9 connectivity probe | 120 | 0 | 120 |
| E10 usage/transcripts | 164 | 0 | 164 |
| E11 reset prose | 66 | 0 | 66 |
| E12 multi-source feed | 72 | 49 | 121 |
| E13 object caches | 72 | 0 | 72 |
| E14 HTTP/static | 84 | 61 | 145 |
| E15 browser substrate | 323 | 0 | 323 |
| E16 process test harness | 0 | 308 | 308 |
| E17 config/path mechanisms | 15 | 0 | 15 |
| E18 git facts | 24 | 0 | 24 |
| **Sum** | **2,600** | **418** | **3,018** |

Approved relocation is **3,018 / 20,264 = 14.89%** of the covered B2 family inventory, and **3,018 / 143,632 = 2.10%** globally. Runtime relocation is **2,600 / 13,581 = 19.14%** of B2 runtime. The 50% global target is 71,816 lines; the shortfall after these gross moves is **68,798**, and actual net savings will be smaller because adapters remain. The ❓ envelopes are not added to savings; their whole-file counts are investigation bounds. No legacy JSON/minification trick, speculative fixture deletion or unverified library replacement pads the result.

## Top 10

Ranked first by measured lines moved per unit risk; leverage and cost are shown to make the tradeoff inspectable. Risk 1 = presentation/cache/fact mechanism with app decisions retained; 2 = protocol/data/test-harness parity; 3 = worker/state/security or factory authority. These are ordinal triage weights, not probabilities. Cost S/M/L = one seam/several seams/architecture or process-state refactor. Demand count means observed consumer code needing the capability, not completed package adoption.

| Rank | Start Phase 2 with | Lines | Risk | Lines/risk | Observed demands | Lines × demands | Cost |
|---|---|---:|---:|---:|---:|---:|---|
| 1 | E15 browser mechanisms | 323 | 1 | 323.0 | 1 | 323 | M |
| 2 | E1 event streams/evidence | 651 | 3 | 217.0 | 1 | 651 | L |
| 3 | E16 process simulator | 308 | 2 | 154.0 | 1 | 308 | M |
| 4 | E9 network probe | 120 | 1 | 120.0 | 1 | 120 | S |
| 5 | E3 codec/schema | 333 | 3 | 111.0 | 2 | 666 | L |
| 6 | E5 JSONL/tails/sinks | 168 | 2 | 84.0 | 2 | 336 | M |
| 7 | E10 vendor usage/transcripts | 164 | 2 | 82.0 | 1 | 164 | M |
| 8 | E13 object caches | 72 | 1 | 72.0 | 1 | 72 | S |
| 9 | E12 multi-source feed | 121 | 2 | 60.5 | 1 | 121 | M |
| 10 | E2 CLI/session I/O | 108 | 2 | 54.0 | 1 | 108 | M |

The next queue by the same weights is E6, E7, E14, E11, E4, E8, E18, E17. For the Top 10, create package contracts and pins first; E3 is a dependency to settle before E1's record relocation, E5 before E12, and E1 before E2/E10's shared adapter adoption. Ranking is value order, not permission to bypass those dependencies. E6/E7/E14 require the strongest production holdouts even when their small gross count lowers their rank.

## Beads to file

Proposed titles/acceptance summaries only; no tracker writes were authorized. One bead per extraction, including separate releases within the same package:

1. **E15: Extract browser polling, formatting and native UI substrate** — Move the 323 listed JS lines behind route/schema callbacks; ship tagged assets and browser contract tests; preserve owner-action holdouts.
2. **E1: Publish any-agent-cli event streams and evidence** — Relocate 651 listed lines; synthetic three-vendor streams prove pairing, partial usage, provisional starts and denial facts.
3. **E16: Move process simulator into stream-proc.testing** — Move 219 support + 89 test lines; inject factory defaults and preserve the guard's false-green protections.
4. **E9: Publish bounded DNS/TCP net-probe** — Move 120 lines with global deadline, DNS/TCP distinctions and fixture-only cache tests.
5. **E3: Extract strict typed-record codec and schema projection** — Move 333 lines; prove version/null/alias/type/schema parity before any msgspec backend replacement.
6. **E5: Evolve jsonl-log for byte tails, predicate compaction and capped sinks** — Move 168 lines; preserve raw bytes, cursor bounds, locking and final-record behavior.
7. **E10: Extract CLI usage and transcript fact readers** — Move 164 lines with synthetic RPC/rollout/statusline fixtures; keep lane exhaustion and source precedence local.
8. **E13: Publish object TTL and file caches** — Move 72 lines; pin current invalidation, LRU and concurrent-miss semantics.
9. **E12: Add multi-source cursor merge and long polling to jsonl-log** — Move 72 runtime + 49 test lines; inject projection/ranking and preserve live-page product assertions.
10. **E2: Extract vendor launch/session/probe adapters** — Move 108 lines behind roots/transport/permission inputs; keep login unknowns and resume behavior stable.
11. **E6: Extend stream-proc for duplex execution, recovery and watchdogs** — Move 158 lines only after pipe-flood, PID-reuse, cancellation and parent-death contracts pass.
12. **E7: Extract exclusion-aware shell text interpretation** — Move 147 lines; caller retains command/recipe/PID admission decisions.
13. **E14: Extract bounded static responses and threaded HTTP mechanics** — Move 84 runtime + 61 test lines; preserve bind restrictions, exact conditional bytes and owner POST behavior.
14. **E11: Extract vendor reset-time prose parser** — Move the 66-line prefix while keeping fallback/rest selection in delegate.
15. **E4: Extract locked typed JSON transactions** — Move 53 lines over existing atomic-io/process-lock; prove lost-update, rollback and read-outcome parity.
16. **E8: Publish declarative macOS command-sandbox compiler** — Move 42 listed lines with app-supplied roots/rules and profile/preflight contracts.
17. **E18: Add tolerant repository discovery and identity facts to git-porcelain** — Move 24 lines; preserve detached/missing/error distinctions and keep the worker git guard local.
18. **E17: Finish shelf config overlay and plugin-path derivation** — Move 15 lines via app-dirs/settings-base tagged additions; keep config priority, checkout refusal and profile schema local.
