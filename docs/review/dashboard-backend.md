# Dashboard ↔ backend interaction review

Static review of this checkout, 2026-11-01. Read repository documentation beginning with `docs/design/dashboard/README.md`, then dashboard code, contracts, relevant producers and tests. No live state, credentials, network, git commands or test runners were used. The failures below follow from inspected paths; timing scenarios are not runtime measurements. In particular, the reported roughly 90-second claim-to-manifest interval is a scenario to support, not a bound established by this code.

The dashboard is a second state interpreter embedded in an HTTP server. Its typed HTTP response does not establish an engine-owned read contract: it constructs that response by joining independently advancing bd listings, slot metadata, manifests, engine logs, loop documents, asks, parks, events, traces and lane snapshots. The resulting content hash proves response equality, not that its inputs are current or mutually consistent.

## Route and freshness inventory

Dispatch is in `src/taskloop_dash/http.py:28` and `:64`. All responses receive `Cache-Control: no-store` (`http.py:55`); application caches and conditional requests still operate. Browser snapshot and mounted drawer/cost resources poll independently every 2.5 seconds while visible, with focus/visibility refresh and error backoff capped at 30 seconds (`static/js/api.js:7`, `:20`, `:47`). A pending fetch has no abort deadline.

| Route | Actual acquisition and invalidation | Consequence |
|---|---|---|
| GET `/api/snapshot` | One-second built-response TTL; rebuild invokes `Worlds.world()`. Content hash excludes `t` and `version`; either `since` or `If-None-Match` can produce 304 (`api/reads.py:29`, `:42`; `views/snapshot.py:110`). | A rebuild and 304 can repeatedly validate obsolete bd data; F01. |
| GET `/api/bead?project&id` | Rebuilds the entire world including unretained history for this bead; comments have a 15-second TTL. Independent content hash/ETag; unknown project, invalid ID or missing cached bead becomes 404 (`api/reads.py:46`, `:70`; `readers/world.py:150`). | Drawer freshness differs from board freshness; backend failure can resemble missing content; F01–F03. |
| GET `/api/cost?window&last&project` | One-second TTL per parameter combination, independent hash/ETag. Rebuilds the whole world, aggregates retained engine logs, validates window and numeric `last` (`api/reads.py:61`, `:75`; `views/cost.py:50`). | A cost read inherits bd latency even though usage lives in logs; retention determines the available history. |
| GET `/api/live?project&id&since&wait` | Ignores `project`; picks newest logged run by bead ID. Per-source byte cursor, 300 initial events, at most 2,000 subsequent events; polling every 250 ms for at most 20 seconds although the browser requests 25. Keeps up to 24 run readers (`api/liveview.py:15`, `:33`; `api/live.py:21`, `:102`, `:109`). | Cursor has neither run nor file generation; continuation and terminal delivery fail in specific cases; F07–F08. |
| GET `/api/artifact?bead&name` | Direct file read, no application TTL or ETag (`api/artifacts.py:20`). | Bead-scoped rather than project-scoped; no byte limit; final symlink check and open are separate operations. |
| GET `/api/look-shot?repo&path` | Look list cached 10 seconds, assembled using cached bead listing and synchronous bead detail calls; then direct image read (`api/looks.py:22`, `:33`, `:48`). | Permission to serve a removed gallery image can lag the gallery update; an image request can wait on bd. |
| GET `/api/version` | Returns process version, PID, start, script, binds and port directly (`http.py:68`). | Reports dashboard package identity, not producer/contract compatibility; F06. |
| POST `/api/answer` | Current ask lookup, option validation, in-process answer/ask-back port; logical refusal is HTTP 200 (`api/writes.py:98`, `:113`). | Writes ask/bd state; no general read-cache invalidation. |
| POST `/api/look` | Resolves project and invokes look port; drops only `looks:<repo>` (`api/writes.py:142`; `api/looks.py:72`). | Snapshot/bead caches can still retain pre-write state. |
| POST `/api/stick`, `/api/prune` | Intake writes ledger/ADR state, can create a factory bead or edit the brief (`api/writes.py:132`; `docs/contracts/dash-api.md:43`). | Five-second ADR/ledger and longer bd caches survive success. |
| POST `/api/cause`, `/api/ack` | Resolves latest logged run by bare bead ID and writes metadata through ports (`api/writes.py:146`). | Scope can differ from the run the owner saw; F04–F05. |
| POST `/api/park`, `/api/stop`, `/api/note` | Same latest-run resolution; ports invoke `OwnerVerbs`, updating holds, request files, hints and comments (`api/writes.py:158`; `app/launch/dash_ports.py:106`). | A success is acceptance, not engine application; requests can race close; F05. |

The exact write set is selected through `WRITES` and exhaustive dispatch (`api/writes.py:62`, `:73`). Unknown verbs are 404, malformed typed requests 400, and domain refusals normally 200 with `ok=false`. GET has a broad JSON 500 wrapper; POST has no equivalent wrapper around dispatch (`http.py:73`, `:77`).

Layered input caches are material to every ETag: typed beads five seconds; comments fifteen; ledger, ADRs and landings five (`readers/world.py:35`). Beneath those, bd lists use `.beads/last-touched`, a five-second minimum settle period, 60-second maximum age and a 30-second shared disk cache (`readers/beads.py:15`, `:35`). FileCache uses floating mtime plus size (`cache.py:53`), whereas manifest caching uses nanosecond mtime plus size (`contracts/locator.py:89`). None is an input revision shared by the response's other sources.

## Findings

### F01 — P1: bd failure renews stale data as a successful observation

**Evidence:** `src/taskloop_dash/readers/beads.py:48` retains the previous list, `:58–63` timestamps it again even when `_list` returns `None`, and `:65–69` suppresses bd, OS and decoding failures. With an unchanged marker, the newly timestamped failure result is reusable for another 60 seconds. `src/taskloop_dash/static/js/api.js:33–36` resets freshness and errors after a successful response or 304; `:65–68` labels freshness by HTTP validation time.

**Failure:** A locked/unavailable bd can leave old claims, missing tasks and obsolete asks looking continually current. On cold start the same path returns an apparently valid empty list; comment failures similarly become empty comments (`readers/beads.py:88`). ETags cannot distinguish “unchanged in bd” from “could not observe bd.”

**Fix:** Preserve the last successful observation timestamp and publish source health/error separately. Serve last-known data with explicit stale/degraded status and retry independently; never renew observation age on failure.

### F02 — P2: HTTP refresh synchronously waits on bd and duplicates refresh work

**Evidence:** `src/taskloop_dash/readers/world.py:65–77` reads slots directly on every world build and obtains look items; `api/looks.py:25–30` calls `show` for every owner-look bead. `src/taskloop/app/launch/dash_ports.py:43–47` gives dashboard bd calls a 30-second timeout. `src/taskloop_dash/cache.py:18–25` releases its lock before building, allowing concurrent cache misses. Snapshot, bead and cost all build worlds (`api/reads.py:42–64`).

**Failure:** A nominal 2.5-second refresh can block for several sequential 30-second calls per project. Concurrent page/resource requests can spawn duplicate expensive reads, while browser `pending` suppresses further refreshes indefinitely if a fetch never completes (`static/js/api.js:20–25`). Threaded HTTP isolates handlers, not backend load or freshness.

**Fix:** Acquire backend observations in a bounded background refresh with one in-flight acquisition per source and explicit deadlines. Serve HTTP from the last published read model and expose refresh failure/age without waiting for bd.

### F03 — P2: lifecycle joins confuse claim, startup, active execution and recovery

**Evidence:** `src/taskloop/app/loop/take.py:97–111` claims before preparation and engine launch; `app/run/entry.py:387–411` claims before constructing the engine; manifest creation occurs through `app/run/layout.py:105–114`. `src/taskloop_dash/readers/records.py:88–99` excludes manifests without a readable engine log. `views/columns.py:50–69` puts any claimed bead in Working with a RUN marker even without a live run. `views/floor.py:66–72` displays `starting` for a claimed slot whose `held_bead` is open/in-progress, with no age or lease cutoff.

**Failure:** During a roughly 90-second preparation interval the board can assert RUN without a run; after a crash the same facts can assert `starting` indefinitely. Cached bead rows and separately refreshed slots can temporarily disagree about the startup target. If an older run is lost, its EXITED marker can also dominate while the new claim is actually starting. Existing tests encode the claimed→Working rule rather than establish real startup ownership (`tests/dash/test_dash_starting.py:64`).

**Fix:** Publish a startup attempt before preparation with claim generation, target, slot, phase, owner and lease/heartbeat. Make claimed, starting, running, recovery-needed and unknown distinct backend states with explicit precedence.

### F04 — P1: project identity is lost before run selection and command dispatch

**Evidence:** `src/taskloop_dash/readers/world.py:61–63` keys projects by directory basename, collapsing different registered repositories with the same basename. `readers/records.py:99` groups logs by bare bead ID; `api/liveview.py:37–40` chooses its newest entry without project filtering. `api/writes.py:105–111` resolves repo and latest run independently, and `:158–168` combines them in owner commands. `src/taskloop/app/run/requests.py:46–60` checks that the supplied run is live but does not check that it belongs to the supplied repo/bead.

**Failure:** Two registered repos containing the same bead ID can show each other's run history/live output. A stop can post to repo B's live run while its hold is written to repo A's bead. Basename collision additionally hides one project entirely. This is a reachable identity collision, independent of bd globally discouraging duplicate IDs.

**Fix:** Carry an immutable repo key and `(repo_key, bead_id, run_id)` throughout reads and commands, using the manifest repo when grouping. Backend command acceptance must verify all identities plus the expected attempt/claim generation.

### F05 — P2: owner actions have neither observed-run preconditions nor durable application receipts

**Evidence:** `src/taskloop_dash/api/writes.py:108–111` resolves the newest logged run at click processing rather than carrying the run the owner viewed. Dispatch returns without clearing caches (`:73–96`); only look explicitly drops one cache. `src/taskloop/app/run/requests.py:55–61` checks liveness before acquiring the request lock, while `:127–131` marks closing and drops pending requests. `:146–169` returns accepted park/stop/note messages; the UI simply retries polling on success (`static/js/api.js:83–90`).

**Failure:** A click on an old run can stop its successor. A request can pass the live check, race terminal cleanup, and be written too late to be consumed, yet receive success. Successful metadata/ADR mutations can remain invisible through nested TTLs; POST acceptance does not identify which generation the owner should wait for. Calling the dashboard read-only hides these actual writes, including `owner_hold`, hints, ledger and request files; even GET writes its shared bead cache (`readers/beads.py:71`).

**Fix:** Accept commands with expected run/attempt and an idempotency key; persist accepted/applied/refused receipts, including terminal-race refusal. Return affected resource revisions and invalidate dependent caches, with the UI distinguishing queued from applied.

### F06 — P2: the version check misses backend-only upgrades and schema incompatibility

**Evidence:** `src/taskloop_dash/cli/dash.py:17–28` hashes only the dashboard package; `src/taskloop/app/launch/dash.py:99–110` compares that hash/script/binds. `src/taskloop/contracts/wire.py:35–39` forbids unknown fields and `:88` begins strict version decoding. `contracts/stores.py:90–106` maps both torn and foreign-version documents to absence through `get()`, used by manifest discovery (`contracts/locator.py:99`) and dashboard loop reads (`readers/world.py:69`).

**Failure:** A contracts/backend-only upgrade need not change `/api/version`, even after ensure. The long-running server retains old code and injected write implementations. New fields or schema versions can silently remove runs, loops or asks from old readers instead of showing incompatibility. The browser's reload on a changed dashboard version (`static/js/api.js:29`) cannot detect this producer skew.

**Fix:** Version the published read protocol explicitly, report producer and command-handler builds, and negotiate a supported schema range. Keep incompatible data visible as an error with the last valid observation; include backend/contracts identity in restart checks.

### F07 — P2: live cursors silently drop events and fail across run/file generations

**Evidence:** `src/taskloop_dash/api/live.py:102–106` takes only the last 2,000 eligible events but advances the returned cursor to all source offsets. `:49–54` detects replacement only when file size is smaller than the saved offset. The cursor is only a source-tag→offset mapping (`:26–38`); `api/liveview.py:37–47` applies it to whichever run is newest. `jsonl.py:35–44` stats before opening without catching deletion between those operations.

**Failure:** A burst exceeding 2,000 decoded events loses its earliest events permanently. Reusing a cursor after run rollover can suppress the beginning of the new engine stream. Equal/larger replacement files evade reset, and a shrinking file has no generation to distinguish reused event offsets. Retention deletion between stat and open produces a 500; deleted sources can also remain as cached items. These are file-reader races, not proof that every per-run log normally rotates.

**Fix:** Bind cursors to run ID, attempt and source generation, page forward with an explicit continuation boundary, and report gaps/reset when retention removes data. Catch disappearance around open/read and stop presenting retained cached items as a complete stream.

### F08 — P2: killed engines and terminal changes can leave the live UI running

**Evidence:** `src/taskloop/contracts/runlife.py:49–61` waits 300 seconds and tests only host/PID existence before deriving LOST. `src/taskloop_dash/static/js/api.js:113–118` calls `onPage` only when the byte cursor changes, even though `api/liveview.py:48` includes independently changing manifest liveness. `views/columns.py:92` describes LOST as a process that is gone, although the manifest can remain recorded RUNNING.

**Failure:** A killed engine remains shown live for up to five minutes; PID reuse can preserve that fiction longer. A manifest-only terminal/lost change with no new log bytes stops the live polling loop without delivering its terminal page to the component. The board may update later while the drawer retains its old live content.

**Fix:** Publish lifecycle revision separately from stream offsets and notify the component on either change. Record process start identity and explicit observation health; show suspect/stale liveness while awaiting reconciliation rather than continuing to assert running.

### F09 — P1: loopback binding does not protect owner POSTs from browser-origin attacks

**Evidence:** `src/taskloop_dash/http.py:77–86` accepts JSON bodies without checking Origin, Host, Content-Type or a request token. `bind.py:21–29` and `:77–83` constrain listening addresses only; writes reach real owner verbs via `app/launch/dash_ports.py:93–126`.

**Failure:** An untrusted page can attempt a simple cross-origin `text/plain` POST carrying JSON to a reachable dashboard; the handler accepts that media type and executes the action without needing the attacker to read the response. Browser private-network restrictions vary and are not a server-side access policy. Any peer permitted to reach the Tailscale listener also obtains the full owner write surface without per-user authorization.

**Fix:** Require a same-origin Host/Origin policy and a non-simple validated request header or CSRF token for browser writes; reject unsupported media types. Treat tailnet access as an explicit owner access grant or add authentication for remote writes.

### F10 — P3: path naming and policy remain distributed despite contracts-only imports

**Evidence:** `.importlinter:94–105` forbids static dashboard imports from engine implementation layers; the import search found dashboard imports from `taskloop.contracts`, not direct private-layer imports. Runtime wiring nevertheless dynamically loads the launcher-selected module (`src/taskloop_dash/cli/dash.py:31–36`; `src/taskloop/app/launch/dash_ports.py:135–136`). `contracts/paths.py:1` claims every location is named once, but `readers/world.py:69–70` reconstructs the loop glob, `readers/records.py:58–65` discovers directories via dummy bead IDs, and `contracts/locator.py:59` constructs the stderr suffix itself.

**Failure:** Moving storage or changing the injected port implementation can break the dashboard despite passing static dependency rules. Semantic coupling is broader: dashboard code replays step/call/wait logs (`views/runfacts.py:92–156`), closes stuck episodes (`:129–140`), decides kanban precedence (`views/columns.py:50`), and invents startup progression (`views/floor.py:79`). These rules can diverge from engine scheduling without an import violation.

**Fix:** Move lifecycle/queue/retry policy into an engine-owned projection and expose typed storage enumeration through one reader. Restrict dashboard code to display transformations over that projection, with a versioned command interface replacing runtime engine injection.

### F11 — P2: golden fixtures cannot establish producer/consumer consistency

**Evidence:** `tests/dash/test_dash_golden.py:56–67` constructs FakeBeadStore and RunScript inputs; `:83–88` fills new optional fields from current contracts before comparing golden data. `tests/dash/test_dash_starting.py:25–69` tests handcrafted startup states, including pre-manifest Working. `tests/dash/test_dash_api.py:1` describes recorded logs and fake bd as its end-to-end boundary.

**Failure:** Fixtures can agree perfectly with dashboard inference while real producers publish impossible combinations or incompatible records. Golden default filling additionally cannot establish that a producer populates a newly optional field. The inspected tests do not provide evidence that a 90-second delayed startup, bd outage, manifest-only end, cross-repo collision or close/request race behaves correctly.

**Fix:** Add producer-generated read-model compatibility fixtures and deterministic interleaving tests for these failures, asserting last-success age, explicit unknown/stale state and command receipts. Keep layout goldens separate from contract correctness; run no live-state-dependent assertions in logic fixtures.

## Derived semantics that belong in the publication

Working currently means either a live run in a mapped phase or merely bd `in_progress`; asks/looks precede even bd closed status (`views/columns.py:50`). bd supplies task closure/claim while the manifest supplies run liveness, so neither alone describes the operator state. LOST is partly recorded and partly recomputed using local PID/time (`contracts/runlife.py:59`). `starting` is an unbounded slot-metadata inference, not an engine-published startup phase (`views/floor.py:66`). Publish each separately, then publish the resolved operator state and reason.

Epic eligibility is also policy: only `issue_type=epic` counts, work cards exclude epics and infrastructure, open epics depend on direct child status (`views/board.py:25–30`; `views/snapshot.py:30–39`); the client filters cards by direct `b.epic` equality (`static/js/data.js:54–56`). Thus selecting a root does not imply selecting nested descendants. The contract must state whether epic membership means parent or ancestry and supply the intended membership list.

Retry display joins Park with current liveness: cards show transient retry whenever not live/closed without checking the park run, whereas run headers require matching park/run (`views/board.py:120–121`; `readers/world.py:102–106`). This can attach an older park's retry to a newer ended attempt. Publish effective retry eligibility, source run, permanence, wake time and hold precedence together; an elapsed timestamp alone does not establish that the scheduler will retry.

Single-document writes through JsonStore use atomic replacement (`contracts/stores.py:115`), so claiming ordinary manifest readers routinely see partially written JSON would be incorrect. Atomicity ends at that document: `Worlds.world()` reads multiple generations, repeatedly enumerates runs, and mixes independently cached records (`readers/world.py:137–148`). Torn/foreign/unreadable files are still possible and their lossy `get()` path conceals the distinction from absence. Full JSONL readers skip malformed rows (`jsonl.py:14–29`); incremental reads defer an incomplete final line (`:45–47`). Neither behavior proves a complete coherent history after rotation or pruning. FileCache's mtime/size key also has no inode/generation guarantee (`cache.py:60`).

The read surface includes run text and worker output, artifacts, registered-repo gallery images and installation metadata. Static paths reject traversal and resolve under the static root (`assets.py:18–34`); look images require gallery membership, an image extension and realpath containment (`api/looks.py:53–70`); artifact names reject separators/dot names and final symlinks (`api/artifacts.py:22–28`). No general arbitrary-command HTTP route was found: commands are typed verbs, and the dynamic module loader is a startup argument. Remaining file-read risks include parent-directory symlinks/check-open races and unbounded artifact/image reads; use immutable backend-issued artifact handles and bounded reads rather than extending query-selected paths. README's container recommendation of `0.0.0.0` conflicts with the actual unconditional bind refusal (`README.md`, Dashboard; `bind.py:81–83`).

## Proposed engine-owned read contract

Publish a typed `DashboardStatus` in `taskloop.contracts`, with a dedicated engine-side projector as the sole writer of the aggregate. Engines and loop/owner verbs must durably publish lifecycle events or owned fragments to it; HTTP GET must never query bd or reconstruct scheduler state. The projector runs independently of an individual engine so it can publish engine death and backend outages. If it dies, its publication expires visibly rather than becoming an empty board.

The envelope needs `schema_major/minor`, producer build, publication ID/epoch and monotonic revision, generated time, valid-until, capabilities, and source observations containing last attempted/successful time, source revision, health and error. Include coverage/watermark information so a coherent engine generation and an independently observed bd revision are not falsely presented as one database transaction.

Each project needs a stable repo key independent of basename/path, display name and explicit visibility/epic ancestry. Each task needs bd revision/status/assignee, claim generation, current run/attempt, resolved operator state/column/marker with machine-readable reason, state-since, phase/step, blocking ask/look IDs, dependencies, hold/park/stop state, effective retry details and available commands. Keep task status separate from run lifecycle. Slots need stable IDs, startup attempt/target, lease owner/generation/expiry, explicit startup phase and heartbeat, hold/set-aside status, current run and recovery reason. Runs need authoritative created/starting/running/waiting/terminal/lost/suspect state, process start identity, heartbeat/deadline, terminal outcome/reason, owner/session/mode, progress and retained-history boundaries.

Publish stage/pass summaries, waits, stuck episode with explicit open/closed state, totals/cost knownness, ask/ledger/ADR views, lane observation time/health and needs-owner rows. Supply independent snapshot, bead-detail, cost, lifecycle and stream revisions. Artifact references must be opaque project/run-scoped handles with type, size and retained/deleted state. Live cursors must encode run/attempt/source generation and last delivered event, with explicit gap and end markers.

Create the startup record at successful claim, before reset/setup; publish every startup phase, step/call/wait transition, ask/answer, hold/request receipt, park/retry change, reconciliation and terminal transition. Heartbeats refresh health on a documented cadence; bd observations refresh separately with failure metadata. Commands include expected project/bead/run/attempt and an idempotency key, return accepted revision, then expose applied/refused receipt. The projector must serialize updates or compare revisions; independent engines must not overwrite the whole aggregate from their private snapshots.

Write immutable detail generations first, then atomically replace the small status/root document on the same filesystem as the commit point. Readers capture one root and read only its referenced generation; retain older generations until outstanding reads can finish. Use fsync where the contract promises survival across power loss, and preserve the last valid root on decode/I/O/version failure. No operation claims atomicity with bd: publication records which source revision was incorporated and whether synchronization is pending.

This would delete dashboard `readers/beads.py` and its shared disk cache, `readers/observed.py` reconciliation reconstruction, most `readers/world.py`/`records.py` storage discovery, `readers/runlogs.py`, and `views/runfacts.py` log replay. Move `views/columns.py` operator precedence, `floor.py` startup detection, `board.py` retry joins, `needs.py` health inference and `queue.py` scheduling interpretation into the projector. Replace `api/live.py` raw-file cursor machinery with a generation-aware stream reader, and remove `Writes.run_of` plus dynamic engine-module injection. Keep HTTP serialization, conditional response handling, presentation formatting and tested layout builders; they consume declared facts rather than infer engine policy.

## Findings ranked

| Rank | Findings |
|---|---|
| P1 | F01 stale bd observations renewed as fresh; F04 project/run identity collision can misdirect stop; F09 owner POSTs lack browser-origin protection. |
| P2 | F02 blocking backend acquisition; F03 ambiguous startup/claim lifecycle; F05 unscoped actions and absent application receipts; F06 backend/schema version skew; F07 lossy generationless cursors; F08 missed terminal notification and stale liveness; F11 fixture-only consistency evidence. |
| P3 | F10 distributed paths and runtime/semantic coupling beyond static import rules. |

## Beads to file

- **Preserve backend observation health and last-success age** — Stop timestamp renewal on failed bd reads and expose stale/degraded data in every resource (F01).
- **Scope dashboard identities and commands by immutable repository key** — Verify repo, bead, run, attempt and claim generation at command acceptance (F04).
- **Protect dashboard owner writes from cross-origin requests** — Validate Host/Origin, request header and media type; define tailnet owner access (F09).
- **Publish an engine-owned dashboard status generation** — Introduce typed lifecycle/startup/hold/retry projections and atomic generation publication (F03, F10).
- **Move source acquisition off HTTP request threads** — Bound background refresh, coalesce reads and expose source failures (F02).
- **Record accepted and applied owner-command receipts** — Add expected-run preconditions, idempotency and terminal-race handling with revision invalidation (F05).
- **Negotiate dashboard/producer compatibility** — Include backend/contracts identity and reject incompatible publications visibly (F06).
- **Make live streams generation-aware and lossless** — Page from last delivered event, report retained gaps and deliver lifecycle-only updates (F07, F08).
- **Exercise real producer contracts under deterministic interleavings** — Cover outage, delayed startup, duplicate IDs, retention, version skew and command-close races (F11).

These are proposed issues only; no issue tracker commands were run. Validation was source inspection and rechecking the cited lines, not execution of tests.
