# Encapsulation review 3: APIs and contracts

Static review, 2026-11-01. Verdict: **refuse-and-redo the compatibility boundary**. The code has typed objects, but it does not consistently have typed agreements between independently running versions. A JSON integer is not a compatibility policy. English diagnostics are still control inputs. Several readers turn protocol failure into legitimate absence, cleanliness, or successful worker termination.

This is additive to [architecture](architecture.md) and [data flow](dataflow.md), referenced as A.Fxx and D.Fxx. Those findings are not reproduced here. The sibling delegate copy under `_delegate/` was inspected; no installed plugin, credential file, served repository outside this tree, network, git command, tracker command, or test runner was accessed. Tests named below are proposed acceptance tests unless explicitly described as inspected. **Runtime behavior is untested.** File references identify source read during this review, not a claim of reproduction.

P1: a boundary can erase authoritative information or bypass a decision prerequisite. P2: a boundary misattributes failure, blocks legitimate work, or spends repeated work under version skew. P3: an interface lacks enforceable evolution rules. “Keep” approves the specific interface property stated, not all of its implementation. “Untested” withholds approval. Every refuse-and-redo inventory row maps to a finding and its concrete migration/test below; inherited findings map to the remediation table near the end.

## Corrections to the earlier reviews

**A.F08 is too soft:** incompatible request flags are no longer merely hypothetical. This tree's sibling delegate advertises contract 3 and rejects flags this engine generates. See F01. A test of this engine's own argv proves nothing about that other parser.

**A.F01 / D.F01 are stale for the main profile reader.** `src/taskloop/app/wire/slots.py:42` now distinguishes an absent committed file from a failed read; lines 55–65 raise `ProfileReadError`. `cfg_source` at line 80 discovers the base without decoding the whole local engine block. Keep those changes. The slot-only reader at line 97 still returns default slots on file/JSON errors, so do not declare all profile consumers repaired. A.F05 / D.F10 still own the multiple-revision problem. F07 below addresses the separate missing schema/evolution contract.

**A.F10 / D.F08 / D.F09 require revalidation against the new outbox.** `src/taskloop/app/land/followups.py:48` saves pending work, line 54 looks up an exact key label including closed beads, and lines 60–69 retain created/refused results. `packages/kernel/src/tlkernel/followups.py:10` defines an outbox v1. Keep the direction; crash behavior remains untested here. Do not file the old “no durable outbox” finding again. F04 instead concerns the still ambiguous bd response used by that lookup and by ask reconciliation.

The old first-line-only lint parser is also gone: `src/taskloop/adapters/bd.py:113` combines stderr and the JSON error before extracting headings. Keep extraction before clipping. Refuse its continued reliance on English and heading typography, as F05 explains.

## Process interface inventory

Column shorthand: “typed” means runtime boundary validation, not merely Python annotations. “Versioned” names a checked wire revision where one exists. C denotes the task-loop config directory described by `packages/kernel/src/tlkernel/paths.py:10`; these are code-described paths, not files opened on this machine. B is a bead ID, R a run ID, K a repository key.

### tl verbs and exit codes

The complete top-level parser and dispatcher are `skills/task-loop/tl.py:151`, `:192`, `:227`, `:280`, and `:397`. All verbs inherit argparse exit 2 for parser misuse and Python exit 1 for uncaught ordinary exceptions; these are not equivalent to a typed domain refusal. No global CLI protocol revision is negotiated. A zero exit often means “the query worked,” not “the thing queried is healthy.” Do not invent one shared interpretation of exit 1.

| Interface, including exits | Producer | Consumer(s) | Typed? | Versioned? | Leaks internals? | Behavior under version skew | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `actor`: 0, actor line | CLI identity | coordinator/scripts | argv only | no | actor naming | identity spelling changes consumers | Keep as opaque text; do not parse its components |
| `bd ARGS...`: bd code; close guard can refuse 1; rejected `dolt push` corrected to 1 | tl / bd | owner, scripts | partial adapter | assumes bd 1.3.1 | arbitrary bd JSON and error words | passthrough inherits all bd changes | Refuse-and-redo F04/F05 |
| `register`: 0 registered, 1 refusal | tracking verb | owner/dashboard | argv | no | repository paths | persisted repo index changes independently | Untested |
| `claim`: 0 claimed, 1 refusal | tracking verb | coordinator | argv, bead adapter | no command revision | assignee, slot, paths | ownership fields/guards can change | Refuse-and-redo inherited A.F03 |
| `land ID --sha`: 0 recorded, nonzero guard refusal | CLI land | coordinator | argv / typed receipt | receipt v1 | SHA, worktree path | receipt writer/reader skew | Refuse-and-redo inherited D.F04/D.F07 |
| `close`: 0 closed, 1 refusal; `block`: 0 blocked, 1 refusal | tracking verbs | coordinator | partial | no | reasons and assignees | guard semantics and bd words vary | Refuse-and-redo inherited A.F03; F05 |
| `slot list/init/take/release/hold`: 0 success, 1 refusal; dispatcher 2 misuse | slot verbs | owner / coordinator | argv, partial records | no CLI revision | slot titles, paths, holder PIDs | meanings of refusal not encoded | Untested |
| `slot reset/setup`: 0 success, 1 explicit refusal, 2 misuse, 3 slot_broken **or transient**, 4 busy, 5 bead_pinned | slot verbs | coordinator | `SlotFailCode` internally | no | error detail | cannot distinguish transient from broken by code | Refuse-and-redo F06 |
| `worktree start/sunset`: 0 success, 2 unsupported operation in underlying verb | slot wiring | sessions | argv | no | cwd / checkout paths | ownership layout can change | Untested |
| `worktrees [clean]`: list 0; clean 0 all handled, 1 any refused | ownership code | owner | `Owned` partly typed | record unversioned | paths and kind strings | new kinds can enter old cleanup policy | Refuse-and-redo inherited D.F04; F07 evolution rules |
| `ask list/show/answer/withdraw/age`: 0 success, 1 missing/refused or age faults, 2 missing required bead | asks CLI | owner | typed asks, argv | Ask v3; command unversioned | IDs, text, option indexes | older ask reader cannot interpret new ask shape | Refuse-and-redo inherited A.F09 at shared answer port |
| `answer`, `hint`, `hold [--release/--until]`, `override`, `park`, `note`: 0 accepted, 1 refusal, 2 invalid request | asks CLI / Intake | owner | partial typed action | no command revision | free-text approval, ask IDs, cap names | accepted action vocabulary changes | Untested beyond inherited A.F09 |
| `dash ensure/stop/url`: 0 handled, 1 startup/address failure; `dash status`: 0 running, 1 absent | dash launcher | owner / factory | weak version probe | code hash, no protocol range | PID, script path, binds | new dashboard can be restarted by older launcher | Untested |
| `factory start`: dashboard ensure code after factory start; `status`: 0 live, 1 absent; `stop`: 0 requested, 1 absent; `logs`: 0 read; caught failures 1, interrupt 0 | factory CLI | owner | plain output | no | PID/log path/version | start can return failure after loop started | Untested; do not infer rollback from nonzero |
| `run-task`: normal stage/engine code, early RunReport refusal 1, preview 0/1, invalid profile 78; stdout last line and optional outcome file | engine child | loop/coordinator | RunReport validated | v2 | paths, reason, free `kind` | old parent can reject new child's completed outcome | Refuse-and-redo F10 |
| `lanes`: 0 filed or no route, 1 status filing failure | status bridge | dashboard/owner | partial snapshot parser | local v1; upstream v ignored | lane names/words | zero can mean no snapshot producer | Refuse-and-redo F03 |
| `usage WINDOWS`: 0 fed or no route, 1 delegate failure | usage bridge | coordinator | JSON text input | upstream status v not checked | vendor window shape | schema changes bypass run-contract admission | Refuse-and-redo F03 |
| `land-lock -- CMD`: child's code; 2 no command; 75 wait timeout | lock wrapper | scripts/delivery | argv only | no | command, lock path | child exit namespace collides with wrapper 75 | Untested |
| `land-stack`: 0 delivered; first failed external command code, local refusal 1, wait timeout 75 | stack | coordinator | typed PR JSON, partial errors | no command revision | PR URL text, refs | gh output/error changes reach orchestration | Refuse-and-redo F09 for text classification; PR read adapter kept below |
| `trace`: 0 including no matching traces | tracking CLI | owner/coordinator | typed stored traces; JSON option | trace v2 | transcripts/paths | older log readers omit foreign rows | Untested |
| `reflect digest`: 0 on normal return, including no work / dry run | report CLI | owner | partial JSON projection | no external revision | source cause text | projection/schema drifts | Untested |
| `next`: 0 candidates, 1 none; `loop status`: 0 query returned; `loop run`: 0 normal stopping conditions, 2 configured refusal paths; no coherent exception envelope | loop | owner / factory | partial LoopState | v2 files | PID/paths/reason | handover and outcome compatibility differ | Refuse-and-redo F10; inherited A.F06 |
| `stop`: 0 request written, 1 no loop | loop command writer | loop/owner | LoopCommand | v2 | PID/start target | old/new loop command reader mismatch | Refuse-and-redo inherited A.F06 |
| `lint`: delegated lint result; explicit 2 when neither bead nor `--ready`; lint success/refusal must not be inferred from text | lint CLI | owner | bead rules, no result envelope | no | messages | lint vocabulary and bd edits change | Untested |
| `prune`: 0 normal return, diagnostics are not a complete success receipt | prune CLI | owner | partial | no | paths/kinds | deleting across record revisions | Refuse-and-redo inherited D.F04 |
| `report`: 0 score passes, 1 fails; planner-only 0; `lost`: 1 if any lost, otherwise 0 | report CLI | owner | JSON option, stored typed inputs | no report revision | git identities/text | old log omission alters score | Untested |
| `pin`, `rollback`: 0 accepted/display/clear, 2 invalid or unavailable version | pin writer | installs/owner | Pin | v1 | installation directory/version strings | accepting a version is not pair compatibility | Refuse-and-redo F01/F10 |
| `cutover check`: 0 no live runs/loops, 1 live | cutover CLI | release coordinator | JSON option | no protocol revision | liveness/PIDs | numeric process identity is inadequate | Refuse-and-redo inherited A.F11 |
| `status`: 0 query returned; `handoff write`: 0; `handoff show`: 0 content, 1 absent | status CLI | coordinator | partial projection / Markdown | no status/Markdown revision | paths, names, text | changing projection/omitted old rows | Untested |
| `wait`: 0 ended OK, 10 ask, 11 ended not OK, 12 lost, 13 no run, 14 timeout, 2 parser misuse | wait CLI | coordinator | explicit exit vocabulary | no command revision | one-line details | meanings depend on manifest reader | Keep explicit codes (`src/taskloop/cli/wait.py:20`); liveness inherited A.F11 |
| `check` / alias `gate`: list 0; run 1 reds, otherwise 0, preparation may propagate stage code; unknown check/read failure 1; invalid profile 78 | check launcher | owner / gate wrapper | CheckRun | v1 | argv, logs | new check status/fields can invalidate old receipts | Refuse-and-redo F07/F08; inherited D.F02 |
| `green`: 0 green, 1 not green | cache predicate | pre-push hook/scripts | typed pass input | PassRecord v1 | tree/base/check names | key semantics can change with unchanged shape | Untested |
| `hooks install`: 0 installed, 1 refusal | hooks CLI | git hook process | argv / script text | no hook protocol revision | install script paths/env | hook can outlive engine installation | Untested |
| `doctor`, `selftest`: success 0, detected failure 1 | diagnostics | owner/release | text / test flow | no result revision | installed paths | real installed pair not proved by fake lane | Untested |

Exit evidence: `src/taskloop/app/run/entry.py:165`, `:173`, `:362`; `src/taskloop/cli/factory.py:22`; `src/taskloop/app/slots/verbs.py:14`; `src/taskloop/cli/asks.py:98`; `src/taskloop/cli/report.py:79`; `src/taskloop/cli/status.py:10`; `src/taskloop/cli/loop_cmd.py:31`; `src/taskloop/app/land/cmds.py:25`. These are a command-local inventory, not a promise that all uncaught failures are normalized. That absence is itself untested.

### Delegate and other subprocesses

| Interface | Producer | Consumer(s) | Typed? | Versioned? | Leaks internals? | Behavior under version skew | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `route.py run ROLE --brief FILE --cwd DIR --schema FILE --unattended --parent --task --title` | RunRequest | delegate parser | flags parsed | shared contract 3 | temp paths, session IDs | parser and advertised request set can disagree | Refuse-and-redo F01 |
| Optional run `--resume --authored-by --call-id --timeout --idle`, repeated `--engine-only`, `--engine-only-advisory`, repeated `--only-family` | engine | delegate | partial; two flags absent in sibling | nominal 3 | thread references, policy in flags | contract-3 sibling rejects advisory/family | Refuse-and-redo F01 |
| Sibling-only run `--premium [FAMILY] --allow-degraded --claude-usage --cap`; brief also supports stdin | external caller | sibling delegate | argparse | 3 | vendor families/window data | engine does not exercise these flags | Untested; do not claim task-loop uses them |
| run answer: `contract,stop,data,text,ref,lane,model,effort,family,flag,cost,tokens,denied,secs,run_id,call_id,transcript,transcript_info,transcript_status,say,git_violation,usage`; optional worker/exit/context/fallback/diagnostics/agent handoff | delegate | adapter/worker policy | permissive manual decoder | contract 3 checked | transcript path, PID/PGID, message text | unknown execution enum defaults to OK; malformed fields escape | Refuse-and-redo F02 |
| `stop`: null success or agent handoff; object `{reason,scope,permanence,retry:{kind,at},ref,fix,resumable,partial}` | delegate classifier | lane policy, parks | reason open; fact vocabularies checked partly | shares 3 | text/ref, cause transformations | new reasons safe only if facts remain authoritative | Refuse-and-redo F02; inherited A.F07 |
| `route.py status --json [--cheap] [--claude-usage JSON/@file/-]`: `{v:1,ts,lanes,cockpit,running,needs_input,holds,asks,health,roles,network,...}` | delegate status | lanes snapshot / role gate / usage | three different reading paths | emitted v1, not checked by tl | raw status strings, PIDs | role reads bypass snapshot validation entirely | Refuse-and-redo F03 |
| `route.py net [--host ...]`: `{up,why,hosts}` | RouteProbe / delegate | network retry | bool coercion | none | host names | `"false"` becomes true in adapter | Refuse-and-redo F03 |
| `contract.json`: reasons, facts, run_args, answer_schema, status_schema | sibling maintainer / fixture vendor | resolve, synthesis, tests | loosely read dictionary | contract 3 | wording is mixed with semantics | actual run_args are not checked | Refuse-and-redo F01/F02 |
| `DELEGATE_LIVE_FILE`, first WorkerStarted and live JSONL events | engine path / delegate worker | liveness, logs, dashboard | local event union | v1 locally | command text, cwd, PID/PGID | new event tags/readers diverge | Untested |
| Repo check argv, prepare argv, slots setup argv, land argv | profile | spawner, git, container | list-of-strings validation | profile unversioned | logs/paths/rc | same field defaults can change policy | Refuse-and-redo F07 |
| `engine.plan_cmd ... --base SHA --paths-stdin`; NUL-separated path stdin; GatePlan `{version,base,empty,full,full_reasons,steps}` | repo producer | check selection | typed, extension-tolerant | version 1 checked | argv/recipe/check names | producer base is read but never matched | Refuse-and-redo F08 |
| `bd --actor ACTOR ... --json` | BdStore | show/list/ready/create/update/claim/unclaim/heartbeat/close/comments/label/provenance | projected records; writes check rc | executable version not negotiated | error text / metadata | malformed successful reads look absent; claim outage looks contention | Refuse-and-redo F04/F05 |
| `bd sync --no-adopt`: 0 synced/quiet skip, 1 error, 2 conflict, 3 exhausted, 4 stuck; rejection text can override 0 | BdStore | land/stack | code plus prose | assumes bd release behavior | regex of git words | quiet skip and success collapse; localized errors missed | Refuse-and-redo F05; settlement inherited D.F07 |
| git queries: refs/rev-parse/show/ls-tree/log/config/status/diff/ls-files/check-ignore/grep/worktree list | Git adapter | engine, cleanup, checks | mixed NUL/line parsers | git porcelain, no supported-version check | quoted paths, raw stderr | failure maps to empty; filenames not uniformly framed | Refuse-and-redo F09 |
| git mutations: fetch/checkout/worktree/clean/add/commit/amend/branch/rebase/push/LFS | Git adapter / land command | engine/stack | typed exceptions plus English | no machine error revision | messages parsed as classes | wording decides retry vs slot fault | Refuse-and-redo F09; ownership inherited D.F04 |
| gh `pr view/list --json number,state,headRefName,headRefOid,baseRefName,mergeCommit,url,title` | gh | Forge | runtime projection | gh schema unversioned | refs/URLs | additive keys ignored; new state remains arbitrary string | Keep selected-field projection; enum evolution under F07 |
| gh `pr create/edit/merge/close`; merge `--match-head-commit OID` | Forge / gh | stack | argv; create URL read from human stdout | none | URL line and command failure tail | changed create output is a delivery failure after PR creation | Untested; keep merge head precondition |

The user's “run/status only” description is not the whole current process surface: code also invokes `net` (`src/taskloop/adapters/delegate.py:157`). Status usage forwarding is at `src/taskloop/app/wire/usage.py:16`. This is a boundary inventory correction, not permission to call those commands during review. The sibling run parser returns a JSON `bad_request` with exit **0** on bad flags (`_delegate/src/delegate/cli/parser.py:39`); other parser errors exit 2. Its answer emitter returns 0 whenever it prints the answer (`_delegate/src/delegate/app/answer.py:67`). An exit-0 delegate response therefore never means worker success by itself.

### HTTP API

`src/taskloop_dash/http.py:29` routes GETs; `src/taskloop_dash/api/reads.py:66` supplies query errors; POST records and verb registry are `packages/kernel/src/tlkernel/dash.py` (`AnswerReq` through `WRITES`). This service has writes. Calling its package “read-only” conceals its actual process contract.

| Interface | Producer | Consumer(s) | Typed? | Versioned? | Leaks internals? | Behavior under version skew | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| GET `/api/version`: version,pid,urls,started,script,binds,port; 200 | HTTP server | launcher/page | raw dictionary | code hash, no API revision | PID and installation path | hash identifies code, not supported request schema | Untested |
| GET `/api/snapshot[?since=...]`: Snapshot; 200/304 | views | browser | server typed, JS unchecked | v1 + content version | run/slot IDs | stale page reloads only after a readable snapshot | Refuse-and-redo F11 |
| GET `/api/bead?project=&id=`: BeadDetail; 200/304/400/404 | views | browser | server typed | v1 | IDs/log projections | browser does not check v | Refuse-and-redo F11 |
| GET `/api/cost?window=24h/7d&last=N&project=`: CostPage; 200/304/400 | cost view | browser | server typed | v1 | model/lane names | read schema differs without request negotiation | Refuse-and-redo F11 |
| GET `/api/live?id=&since=&wait=`: LivePage, 200/404; JS also sends project, which route ignores | live reader | browser | server typed | v1 | cursor/run/log identity | project scoping is not actually part of lookup | Untested; API documentation must describe actual identity scope |
| GET `/api/look-shot?repo=&path=`, `/api/artifact?bead=&name=`: binary 200, 404 absent | artifact readers | browser | paths validated by reader, not JSON | none | filesystem selectors | storage layout is part of the URL interface | Untested |
| POST `/api/answer {project,ask,kind,option?,text}` and `/api/look {project,bead,verdict,note}` | browser | owner ports | strict record decode | unversioned | option index, ask/bead IDs | new field is 400 on old server | Refuse-and-redo F11; answer race inherited A.F09 |
| POST `/api/stick {project,ask,outcome,text}`, `/api/cause {project,bead,cause,ask?}`, `/api/ack {project,bead,ack}`, `/api/prune {project,adr}` | browser | owner ports | strict records | unversioned | target IDs | server reconstructs some targets rather than accepting expected revision | Refuse-and-redo F11 |
| POST `/api/park {project,bead}`, `/api/stop {project,bead}`, `/api/note {project,bead,text}` | browser | run request writer | strict records | unversioned | newest-run lookup hidden behind bead | old page can submit without server compatibility check | Refuse-and-redo F11 |
| POST result `{ok,message}`: 200 business acceptance/refusal; 400 bad body; 404 unknown verb | writes dispatcher | browser | Result typed on normal path | none | message only, no refusal code | backend exception has no equivalent structured response | Refuse-and-redo F11 |

GET exceptions become 500 `{error: "Type: text"}` at `src/taskloop_dash/http.py:74`; POST backend exceptions are outside the JSON parse guard at line 82. The 64 KiB request limit truncates the read rather than defining an explicit 413 protocol. Keep bounded reads, but the error contract fails F11. Do not label GET's exception string a machine-readable error kind.

## Disk and environment inventory

### Disk formats

The disk tree is already mapped in D “Authorities and storage”; this table judges compatibility rather than repeating ownership races. Nested records inherit their container version; they do not independently emit `v`. `wire.load` checks exact version and rejects unknown fields (`packages/kernel/src/tlkernel/wire.py:35`, `:83`), whereas `JsonStore.get` collapses Torn/ForeignVersion/Absent (`packages/kernel/src/tlkernel/stores.py:104`). These are opposite compatibility policies depending on which helper the caller chooses.

| Interface | Producer | Consumer(s) | Typed? | Versioned? | Leaks internals? | Behavior under version skew | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Repo `.task-loop.json` | served repo owner | engine, loop, slot/check/dashboard loaders | strict records, selected retired keys ignored | **none** | executable argv, paths | additive key breaks old reader; default changes invisible | Refuse-and-redo F07; snapshot ownership A.F05 |
| bd Dolt data, metadata, labels, leases; passive `.beads/issues.jsonl` | bd / tl metadata writes | BdStore | bd JSON projections, open metadata | bd owns DB; tl namespace not schema-versioned here | slot/fence/cap conventions | same label/metadata key can change semantics | Refuse-and-redo F04/F05; fencing A.F03. Do not import passive JSONL as wire |
| `.task/engine.lock`, `engine.take`; C locks and `.holder` hints | engine/lock adapter | admission/reconcile/dashboard | EngineLock/LockRecord | v3 / v1; OS lock not JSON | PID/worker identity | foreign lock shape must not imply free | Refuse-and-redo inherited A.F11; F07 evolution policy |
| `runs/R/manifest.json` | locator | loop/wait/dashboard | RunManifest | v2 | PID/cwd/owner paths | old reader can omit incompatible runs | Refuse-and-redo inherited A.F11; F10 |
| `checkpoints/B.json` | engine | resume/close | Checkpoint | v3 | plan/cursor/worktree | `.get()` erases incompatibility | Refuse-and-redo inherited A.F04 |
| `checkpoints/B.call.json`, raw answer JSON pointers | CallState | worker attach | dataclass, loose JSON | v1; accepts missing/older v | absolute answer path/ref | unknown fields dropped, phase is free string | Refuse-and-redo F07; consumed crash D.F12 |
| `runs/R/<node>-N.raw.json`, interpreted `<node>-N.json`, `plan.json` | delegate adapter / engine | worker memo, dashboard | envelope manually decoded; node answers typed elsewhere | envelope contract3; standalone answers no common v | transcript/ref/check names | prompt/schema change can invalidate saved answer | Untested; F02 owns envelope validation |
| `runs/R/done.json` | done memo | worker attach | DoneMemo | v1 | answer filenames and prompt hash | old memo reader cannot reuse new shape | Refuse-and-redo inherited D.F12 |
| `runs/R/pause.json`, `reexec.json`; C `reexec/B.json`, `pauses/B.json` | reload | replacement engine/loop | RunCounters, ReexecNote, NetPause | v1 each | install dir/PID/run identity | checkpoint/profile/readers not negotiated together | Refuse-and-redo inherited A.F04; F10 |
| `runs/R/handoff.json`, brief Markdown, replan Markdown | engine | worker/dashboard | HandoffMirror typed; prose untyped | mirror v1; prose none | filenames/context | content and record schema evolve separately | Untested |
| `runs/R/owner-request.json` and lock | CLI/dashboard | live engine | OwnerRequest | v1 | by/timestamp; no request receipt ID | exact-v reader versus newer command writer | Refuse-and-redo F11 compatibility rules |
| `parks/B.json` | parks | entry/queue/loop | Park | v1 | reason/role/wake time | open reason translated by several policy tables | Refuse-and-redo inherited A.F07/D.F11 |
| `asks/B.json`, sweep markers | ask store / sweeps | Intake/CLI/dashboard/engine | Ask | v3; marker mtime unversioned | ask IDs/option text | foreign ask must remain visible/refused | Refuse-and-redo inherited A.F09; F07 |
| `ask-ledger.jsonl`, `decisions/K/ADR-N.json`, `uses.jsonl` | ask/ADR stores | planner/dashboard | LedgerEntry, Adr, AdrUse | v1 each | source ask and owner text | unknown ledger records can disappear from projection | Untested |
| `followups/B.json` | checkpoints/outbox | filing/recovery | FollowupOutbox | v1 | exact key and created bead IDs | requires preserved namespace semantics across versions | Keep durable outbox interface; crash/retry untested |
| `landed/B.json` | land recorder | close guard/report | Landed | v1 | commit/base/ref | immutable receipt meaning needs explicit evolution | Untested; settlement D.F07 |
| `engine/R.jsonl`, `events.jsonl`, `traces.jsonl`, `loop/K.jsonl` | engine/event/trace/loop writers | dashboard/report/recovery projections | tagged unions / typed trace | v3/v3/v2/v4 | paths/commands/diagnostics | old readers skip foreign records | Refuse-and-redo F07 for migration policy; observation limits D |
| `engine/R.live/*`, stderr, command/check logs, copied artifact files | worker/spawner/checks | dashboard/evidence | live typed union; others bytes/text | local live v1; logs none | commands/paths/PIDs | new live tags unavailable to old reader | Untested; logs must not authorize transitions |
| `loop/K.PID.json`, `died-PID.json`; `K.command.json`, `K-rest.json` | loop / owner | loops/CLI/dashboard | LoopState/Command/Rest | v2 each | PID/start/install paths | foreign state can vanish; target identity differs after uv | Refuse-and-redo inherited A.F06 |
| loop `<B>-<timestamp>.outcome.json`, `.log` | run-task | parent loop | RunReport / plain text | v2 / none | log parsed on exit78 | new completed child can look failed to old parent | Refuse-and-redo F10 |
| loop `exits.jsonl`, `loop.pid`, factory logs | loop/factory | status/factory | exit dict untyped; PID scalar | no | numeric PID and reason keys | last-exit schema has no reader policy | Untested (`src/taskloop/app/loop/files.py:126`) |
| `slots/K/sequence.json`, `seq`; `slots/path-hash.setup` | waiter/setup | slot scheduler | Ticket / SlotSetupMarker; seq scalar | v1 / v1; seq none | PID, path hash | unreadable ticket skipped | Untested |
| `worktrees/K/key.json` | ownership writer | cleanup/survey | Owned, free kind | **none** | absolute path, kind, host | new kind silently enters old policy | Refuse-and-redo F07; cleanup D.F04 |
| `slot-state/K/slot/`, `.task/checks/`, artifacts and build scratch | repo tools | subsequent commands | opaque tool-owned formats | tool-owned | filesystem layout | tl cannot promise tool cache compatibility | Untested; treat as opaque, never authority |
| `engine-checks.json`, `.rN.json`; results/pass/base-red; durations | checks | gate/dashboard/cache | CheckRun, PassRecord, BaseRedRecord, Durations | v1/v1/v1/v2 | tree/base/command fingerprints | field-compatible default change can invalidate meaning of pass | Refuse-and-redo F07/F08; evidence identity D.F02 |
| `prepare.stamp`, `plan-note-hash` | preparation/gate-plan | engine dedup | fingerprint text / existence marker | no | input-derived hashes | hashing policy changes independently | Untested |
| `host.json` | machine owner | resource selector | HostResources | none | local resources | absent means all; present empty means none | Refuse-and-redo F07: this is policy, not disposable cache |
| snapshots/K.name.json, sessions/id.json, repos.json, shared/K.json | status/session/registration | dashboard/brief/coordinator | StatusSnapshot, SessionIndex, ReposIndex, SharedNotes | v1 each | repository/lane/session names | incompatible snapshot can look absent | Untested; upstream status F03 |
| `pinned.json`, `bad-versions.json` | owner pins / install recovery | loop/reload | Pin / BadVersions | v1 each | install identifiers/paths | compatibility isn't established by a pin | Refuse-and-redo F01/F10 |
| releases/last.json, suite-green.json; suite logs; plugin/marketplace version JSON and manifest | release process | release/doctor/update | ReleaseResult, SuiteGreens; tool-owned manifest | v1 for records; release version separate | install paths/hash/command logs | suite green does not negotiate active run formats | Untested; cutover A.F04 |
| reflect-digest.json, reflect-view.json, usage-history.jsonl | reflection/status | digest/dashboard | ReflectState / projection / UsageRow | v1 for state/usage | grouped reason/window strings | changed categories silently regroup history | Untested |
| dash.json, dash.pid, handoff/K.md, githooks scripts | launcher/handoff/hooks | owner/browser/git | DashState typed; prose/scripts mixed | DashState v1; others no common revision | PID, path, executable location | older service/hook can read newer mutable state | Untested; HTTP skew F11; bd projection now lives only in factory.db |

Record evidence: `packages/kernel/src/tlkernel/run.py:16`, `:58`, `:87`, `:132`, `:180`; `contracts/checkpoint.py:162`; `contracts/loop.py:40`, `:56`, `:89`; `contracts/snapshots.py:47`, `:90`, `:100`, `:115`, `:130`, `:148`, `:156`; `contracts/checks.py:154`, `:205`, `:224`, `:244`; `contracts/usage.py:15`; `contracts/paths.py:22`, `:122`, `:182`, `:237`. All paths in this sentence are under `src/taskloop/`.

### Every registered environment name

The complete registry is `packages/kernel/src/tlkernel/envvars.py:7–41`. All values cross an untyped string boundary. JSON handovers have their own decoding rules; scalar strings have no independent revision. Ambient standard/tool variables are a separate interface at `src/taskloop/adapters/childenv.py:32`: PATH, HOME, USER, LANG, TERM, TMPDIR, SHELL, git author/committer fields, UV, SSH_AUTH_SOCK, GIT_SSH_COMMAND, LC_* and GIT_CONFIG_*. Their **names and handling code only** were inspected; no credential files or values were read.

| Interface | Producer | Consumer(s) | Typed? | Versioned? | Leaks internals? | Behavior under version skew | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `TL_SLOT` | slot env | checks/tools | string | no | slot name | naming changes external recipe behavior | Untested |
| `TL_ARTIFACT_DIR`, `TL_ARTIFACT_STEP` | checker | repo commands/evidence | path/id strings | no | directory/check identity | changed layout affects scripts | Untested |
| `TL_RUN_ID`, `TL_RUN_DIR`, `TL_ATTEMPT` | run env | tools/delegate/checks | string/integer text | no | run path/attempt | scripts bind to storage organization | Untested |
| `TL_WORKTREE`, `TL_BRANCH` | run env | tools/workers | strings | no | checkout/ref | mutable branch name is not input identity | Untested |
| `TL_BOX_CWD` | container setup | container check | path string | no | host/container mapping | new mount policy changes recipe meaning | Untested |
| `TL_WORKER_MB` | suite owner | suite workers | number text | no | resource cap | units/default interpretation external | Untested |
| `TL_LAND` | pusher | pre-push hook | convention `1` | no | bypass marker | hook and caller can come from different installs | Untested; marker is not proof of ownership |
| `TL_REEXEC` | exec handover | replacement engine | Reexec JSON | v1 checked | old PID/run/owned slot | record alone does not negotiate checkpoint/report | Refuse-and-redo F10; inherited A.F04 |
| `TL_LOOP_STATE` | exec handover | replacement loop | Carry JSON | **Carry has no V** | rests/counters/worktree/install | adding defaulted field breaks older strict decoder | Refuse-and-redo F07; identity A.F06 |
| `TL_RELEASE_REEXEC` | release exec | release process | flag convention | no | handover state | value semantics implicit | Untested |
| `TASK_LOOP_SLOT_BEAD` | loop/entry | run-task | parsed bead ID | no | tracker identity | identity scope/metadata changes | Untested; fencing A.F03 |
| `TASK_LOOP_ACTOR`, `TASK_LOOP_SESSION` | identity export | child identity | strings | no | actor/session | actor is not generation | Untested; fencing A.F03 |
| `TASK_LOOP_LOOP_PID` | loop | run-task / displays | integer text | no | PID | uv topology breaks identity assumptions | Refuse-and-redo inherited A.F06 |
| `TASK_LOOP_WORKER` | child environment | worker guard | flag convention | no | worker role | enforcement depends on downstream install | Untested |
| `TASK_LOOP_DASH_BIND`, `TASK_LOOP_DASH_PORT`, `TASK_LOOP_DASH_DEV_PUBLIC`, `TASK_LOOP_DASH_IDLE_H` | owner | dash launcher/server | manually parsed scalars | no | binds/port/time | malformed inputs have no common config result | Untested |
| `TASK_LOOP_SUITE_HOST`, `TASK_LOOP_SUITE_WORKERS` | owner/CI | suite | scalar strings | no | scheduling settings | units/defaults tied to suite version | Untested |
| `TL_CHECK_LOG_<mangled ID>`, `TL_CHECK_RC_<mangled ID>` | checker | dependent checks | path / integer text | no | earlier check log and exit | mangling changes dependency names | Keep collision rejection and same-lane graph validation (`contracts/config.py:322`); runtime external recipe consumption untested |
| `DELEGATE_LIVE_FILE`, `DELEGATE_DEPTH` | tl child environment | delegate / guard | strings | delegate-owned | log path/delegation marker | not covered by TL registry equality | Untested |
| Tool allowlist and exec/child scrubbing | childenv | git/checks/worker subprocesses | names registered, values not validated centrally | no | git config injection / install paths | changing filtering alters check behavior with same profile | Untested (`adapters/childenv.py:67`, `:109`, `:141`) |

## Ranked findings and concrete replacements

### F01 — P2 — refuse-and-redo: contract 3 admits a demonstrably incompatible delegate parser

**Evidence:** `packages/kernel/src/tlkernel/delegate.py:60` adds `--engine-only-advisory`; line 63 adds `--only-family`. `src/taskloop/app/run/worker_request.py:21` chooses pinned families and line 38 enables advisory for pinned writes with engine recipes. `_delegate/src/delegate/cli/parser.py:62–67` supports neither flag. `_delegate/skills/delegate/contract.json:179–197` advertises neither flag but line 2 still says 3. `src/taskloop/adapters/delegate.py:108–113` accepts numeric equality without checking `run_args`. `tests/contracts/test_delegate_wire.py:62` only tests local flag construction.

**Failure:** this exact pair passes admission, then the sibling parser produces `bad_request` without starting a worker. This is a source-proved incompatibility, not a claim that the sibling copy is currently installed. A.F08 is too soft because the missing feature advertisement already exists. The “bump when flags change” prose at contract.json:3 did not enforce anything.

Target interface (four lines):

```text
DelegateHello {answer_versions, run_features, status_versions, build_digest}
RequiredRun {answer_version, features}
admit(hello, required) -> CompatiblePair | Incompatible
RunRequest.pair_digest: str
```

Migration: first compare generated request flags with existing `run_args` before dispatch; release that refusal without changing flags. Next add explicit semantic features and pair digests to producer and consumer. Finally require pair admission before claim and before changing delegate artifacts. Never silently omit family or enforcement flags to get an old parser to accept work.

**Proof test:** build requests for unpinned write, pinned write, reviewer and resume against the sibling parser's advertised flags; the pinned cases must refuse before claim/spawn. A matching future producer must accept every required flag. This addresses update incident 9 and prevents another engine-only mismatch in incident 4.

### F02 — P1 — refuse-and-redo: the tolerant answer decoder manufactures execution facts

**Evidence:** `src/taskloop/adapters/delegate_wire.py:168` maps an unknown `worker.end` to `"ok"`; lines 169–172 coerce flags and weakly filter survivors. `result_of` at line 180 checks only object/contract/stop presence before manual conversion. Line 193 iterates `git_violation` without requiring a list. `src/taskloop/adapters/delegate.py:209–222` accepts any final-line JSON object regardless of subprocess returncode. `_delegate/src/delegate/app/answer.py:69–74` promises validated output and nonzero only for a router crash.

**Failure:** a future `worker.end="containment_failed"` becomes `ok`; `git_violation="checkout"` becomes characters; an integer there raises TypeError rather than the advertised synthesized stop. A plausible answer object plus nonzero process exit is accepted without a transport conflict. Downstream validation of model `data` cannot restore these lost execution facts. Do not claim this necessarily lands code: the defect is that the boundary lies about what it knows.

Target interface:

```text
decode_run(stdout, stderr, rc, expected_call) -> RunReply | ProtocolFault
RunReply {stop, data, execution: WorkerEnd, diagnostics}
ProtocolFault {code, raw_artifact, producer_digest}
unknown execution enum -> ProtocolFault
```

Migration: retain raw output and strictly validate known execution/denial fields while continuing to ignore unknown telemetry fields. Then enforce exit/envelope consistency and call identity when supplied. Add explicit extension containers rather than defaulting unrecognized safety facts to success.

**Proof test:** mutate a valid envelope with an unknown end, string/integer survivor or violation collections, string booleans, nonzero router exit, and missing required execution facts. Every case must produce a typed protocol fault, no decoder exception, no success default. Valid unknown telemetry keys remain accepted. This is the contract-level defense against incident 4's misleading stop, distinct from D's diagnostic truncation inventory.

### F03 — P2 — refuse-and-redo: status has a version that none of the important readers enforces

**Evidence:** `packages/kernel/src/tlkernel/delegate_status.py:27` reads ts/lanes/cockpit without checking top-level or cockpit `v`. `src/taskloop/adapters/delegate.py:139–154` directly extracts roles/lanes, bypassing that reader. `find_route` at line 116 resolves a path without `resolve`'s run-contract equality test. `RouteProbe.up` at line 168 coerces `up` with bool. `tests/adapters/test_delegate_status.py:44` tests dropped keys; its schema helper at line 63 explicitly checks keys only, not scalar types.

**Failure:** a v2 status retaining the old key names is silently accepted; a renamed role field becomes unknown availability; `{"up":"false"}` becomes online. Snapshot, role admission and retry probe disagree about what “valid delegate state” means. This is a separate seam from A.F08's run flags.

Target interface:

```text
read_status(raw, supported_versions) -> DelegateStatus | StatusFault
DelegateStatus {v, at, lanes, roles, network}
role_status(status, role) -> Availability
NetworkState.up: bool | None
```

Migration: validate v1 and boolean fields centrally; route all three status consumers through the same decoder. Next advertise supported status versions with the pair handshake. Keep unknown availability explicit and bounded by the caller's policy; do not convert invalid state to an empty valid snapshot.

**Proof test:** feed v2 with identical keys, missing v, roles.usable as text, unknown lane states and `up="false"` to every consumer. They must yield the same typed incompatibility/unknown result. Test a valid additive telemetry key separately. Incident 7 cannot be repaired if wake decisions read different status dialects.

### F04 — P1 — refuse-and-redo: bd malformed success is indistinguishable from authoritative absence

**Evidence:** `src/taskloop/adapters/bd.py:102–106` maps invalid JSON to None; `beads_of` at line 83 maps unexpected shapes to an empty collection; `show` at line 215 returns None when decoding yields no bead. `comments` at line 218 returns empty on command failure. `claim` at line 240 reduces every nonzero failure to false. The consumer consequence is concrete: `src/taskloop/app/asks/sweeps.py:39–42` interprets `show(...) is None` as “the bead does not exist”; lines 60–63 close that ask. Its empty-list guard at line 57 does not save a missing individual row when other rows exist.

**Failure:** a changed `show` wrapper or truncated exit-0 output can close a live owner's ask after a successful nonempty list omitted that row. Claim transport failure is reported as contention. This is upstream protocol ambiguity, not A.F03's fence race or A.F09's superseded ask race. The new follow-up exact-key lookup also cannot safely use malformed “empty” as permission to create.

Target interface:

```text
show(id) -> Found[Bead] | Missing | BdFault
find(query) -> Complete[list[Bead]] | BdFault
comments(id) -> Complete[list[Comment]] | BdFault
claim(id) -> Claimed | Contended | BdFault
```

Migration: first reject invalid JSON, wrong top-level shapes and malformed rows as BdFailure. Then distinguish explicit not-found from unavailable and claim contention from transport failure. Finally require complete reads in reconciliation and idempotency lookup; retain prior state on fault.

**Proof test:** nonempty list plus one omitted ask bead, followed by invalid-JSON or wrapped-object show, must leave the ask open. Malformed follow-up lookup must not call create. Claim timeout 124 must surface infrastructure failure, never “already claimed.”

### F05 — P2 — refuse-and-redo: bd's English is still the error protocol

**Evidence:** `src/taskloop/adapters/bd.py:19–21` matches push rejection and lint wording; lines 114–120 classify missing headings, not-found and contention from words. `src/taskloop/adapters/bdcreate.py:25–38` retries with synthesized sections based on that classification. `src/taskloop/domain/land/matchers.py:13` and `:34` recognize no Dolt remote by English. `BdStore.dolt_push` at `adapters/bd.py:202–206` combines real exit codes with rejection-word overrides.

**Failure:** a bd wording change can suppress the retry, add the wrong placeholders, or misclassify a remote/configuration failure. Headings not emitted as `##` leave no actionable section list. The multiline fix contains incident 5's exact parser bug; it does not turn prose into a stable API. Do not discard that fix while replacing the boundary.

Target interface:

```text
BdError {v, code, message, details}
MissingSections.details: list[SectionId]
SyncResult {state: synced | skipped_no_remote | conflict | retryable | failed}
legacy_text(raw) -> explicit LegacyBdError
```

Migration: preserve full raw diagnostics and mark the current parser as a version-specific legacy adapter. Add machine codes/section IDs in bd, then consume them with an explicit supported-version test. Remove English-driven control only after the oldest supported bd supplies that shape. Until then, pin/test the legacy dialect and refuse unknown errors; do not claim broad bd compatibility.

**Proof test:** identical machine code with completely different, multiline or localized message yields identical behavior. Include a misleading “not found” inside unrelated diagnostic context, headings without Markdown, zero-exit push rejection, and explicit no-remote skip. No filing obligation is discharged because wording changed.

### F06 — P2 — refuse-and-redo: the public slot exit code destroys the new failure classification

**Evidence:** `packages/kernel/src/tlkernel/slots.py:12` distinguishes `slot_broken`, `bead_pinned`, `busy`, `transient`. `src/taskloop/app/slots/verbs.py:14` maps both broken and transient to exit 3; reset/setup return that mapping at lines 123 and 132. Internally, `src/taskloop/app/loop/verdict.py:54–58` carefully requires slot_broken before counting quick slot failures.

**Failure:** an external coordinator using the supported CLI cannot preserve the distinction the loop now relies on. Exit 3 can mean “repair this slot” or “retry infrastructure.” That is the public-contract version of incident 8's twelve-hour slot exile. This review does not claim the internal loop still classifies all infrastructure as slot breakage.

Target interface:

```text
SlotReply {v:1, state, fault: SlotFailCode | None, retry_at, diagnostic}
tl slot ... --json -> SlotReply
legacy exit3 stays ambiguous during migration
new exit6 = transient
```

Migration: first add a JSON result with original fault code while preserving old exits. Upgrade callers to consume it; publish a distinct transient exit in an explicit CLI revision. Reject callers asking for an unsupported revision rather than requiring stderr parsing.

**Proof test:** the same reset/setup fixture through CLI JSON and the in-process path yields the same fault classification. A transient failure cannot increment a slot-broken counter or request a twelve-hour hold.

### F07 — P2 — refuse-and-redo: “human written” policy is used as an excuse for no schema revision

**Evidence:** `packages/kernel/src/tlkernel/config.py:247–252` explicitly omits v because a person writes the file. Lines 269–276 define ignored, removed and renamed keys; `load` at line 374 strips retired keys before strict decoding. Defaults such as budget/review/check policy are code values at lines 201–227. `Owned.kind` is a free string and has no V (`packages/kernel/src/tlkernel/worktrees.py:8–17`). `Carry` is unversioned (`contracts/loop.py:40`). `CallState.phase` is free text and its reader accepts missing/older versions (`stores/call_state.py:28`, `:106`).

**Failure:** these are machine-consumed contracts regardless of who edits them. A new default or newly ignored policy key changes behavior without a schema change; an added key can break the old reader while the same unversioned profile still looks legitimate to its author. Closed domains such as worktree kind and call phase remain strings where an unknown value must not select a default lifecycle behavior. A.F05 / D.F10 own which profile revision is used; this finding owns which grammar and semantics that revision promises.

Target interface:

```text
RepoProfile {schema:1, requires: Features, engine, slots, loop}
decode_profile(raw) -> EffectiveProfile | Unsupported | Invalid
Owned {v, kind: slot | loop, ...}
CallPhase = calling | returned | consumed
Carry {v, ...}
```

Migration: accept current profiles as explicit legacy schema0 with reported effective defaults. Add schema1 plus a profile validation command that refuses unsupported features before claim. Convert code-owned state to versioned closed vocabularies with strict readers; retain legacy readers until all live writers are retired. Defaults that alter gates, budgets or wake behavior require a semantic revision or explicit profile setting, not merely a release note.

**Proof test:** old/new reader matrix covers an additive field, enum member, changed default, ignored retired key, removed key and unknown worktree/call kind. Every combination must either preserve the same effective policy or refuse before mutation. Include an older tl with a newer lifesim-style profile without needing the real lifesim checkout. This is the schema defense for incidents 3, 9 and 10.

### F08 — P1 — refuse-and-redo: gate-plan output contains an input identity that the consumer ignores

**Evidence:** `packages/kernel/src/tlkernel/gateplan.py:21–28` requires `version`, `base`, `empty`, `full`, `full_reasons`, and steps. `src/taskloop/app/checks/gateplan.py:91–101` passes a base and paths to the producer, decodes its reply, then builds skips exclusively from `s.run`. It never compares `plan.base` to the requested base. Its parse checks at lines 32–40 enforce names and duplicates, not that identity.

**Failure:** a cached/stale producer answer naming another base can suppress checks for the current base. Hashing its output proves which wrong answer was used, not that it describes this invocation. This is earlier than D.F02's post-execution gate-token race and needs its own admission fix. The consumer currently demands fields it then ignores; that is schema theater.

Target interface:

```text
PlanInputs {base_oid, tree_oid, paths_digest, registry_digest}
GatePlan {version:2, inputs:PlanInputs, decisions:list[CheckDecision]}
accept_plan(expected, reply) -> Decisions | RequireAll
```

Migration: immediately require v1's non-null returned base to equal the requested base or fall back to all required checks. Add full input identities in v2, support both during producer rollout, then remove the ambiguous v1 skip authority. Define `full`/`empty` semantics or remove them from required fields; they cannot contradict executable decisions unnoticed.

**Proof test:** return a well-typed plan for a different base with every step skipped; every configured check must run. V2 must reject mismatched tree/path/registry digests. Valid matching plans retain intentional skips. This is a new contract failure, not a claimed replay of any supplied incident.

### F09 — P1 — refuse-and-redo: git failure is presented as clean/empty and English decides recovery

**Evidence:** `src/taskloop/adapters/git_base.py:84–86` returns empty output on any failed `_ask`; `src/taskloop/adapters/git.py:39–40` therefore reports a failed status query as not dirty. `adapters/git_ops.py:25–33` similarly reports failed diffs as empty changes. `src/taskloop/adapters/git_base.py:18–40` classifies failure words into mutation/retry classes. `src/taskloop/domain/land/matchers.py:11` treats any `rejected` as a push race; `src/taskloop/app/land/push.py:86–94` responds by retrying main movement. Git locale variables are inherited (`adapters/childenv.py:41`).

**Failure:** an unreadable checkout can masquerade as clean; a failed diff can look like no changed files. A hook rejection containing “rejected” is called “main moved,” and localized lock messages miss the special recovery class. A.F02 / D.F04 own unsafe worktree mutation; this finding identifies the adapter contract that denies their callers the facts needed to refuse it. The gate-plan code already compensates for one empty-diff ambiguity at `app/checks/gateplan.py:89`; requiring each consumer to invent that defense is unacceptable.

Target interface:

```text
GitRead[T] = Value[T] | MissingRef | GitFault
status() -> GitRead[list[StatusRow]]
diff() -> GitRead[list[DiffEntry]]
push() -> Accepted | NonFastForward | HookRejected | TransportFault | UnknownFault
```

Migration: first move decision-critical status/diff/ref reads from `_ask` to checked results. Then use porcelain/NUL output and operation-specific status probes; pin locale only for unavoidable legacy diagnostics. Keep unknown errors explicit and non-destructive. Separate remote non-fast-forward from hook refusal before enabling retry policy.

**Proof test:** failed status must never satisfy “clean”; failed diff must never satisfy “no changes.” Exercise hook output containing “rejected,” non-English lock diagnostics and filenames with newlines. Assert no cleanup/skip/retry classification is authorized from a failed or ambiguous read. This strengthens the contract behind incident 1 without re-filing D.F04's ownership race.

### F10 — P2 — refuse-and-redo: the old parent cannot necessarily understand the new child's final report

**Evidence:** `RunReport` is strict v2 (`packages/kernel/src/tlkernel/run.py:16–36`); `kind` and role are unrestricted strings despite outcome being an enum. `src/taskloop/app/loop/verdict.py:95–101` maps any decode error to FAILED and interprets `fault_slot` by string equality. The no-file exit78 path at lines 87–91 reparses an exact diagnostic prefix, substring and suffix from the log. `src/taskloop/app/loop/run.py:79` can restart an early-crashed newer engine on the old install.

**Failure:** a legitimate new report field or v3 final report can be rejected by the still-running old loop and charged as a failed bead, even when the child completed correctly. The profile-reader improvement introduced a brittle English recovery path for its exact diagnostic. A.F04 is too narrow if repaired only with checkpoint reader negotiation: the surviving parent is also a reader that must understand the replacement child's completion protocol.

Target interface:

```text
ChildHello {report_versions, checkpoint_readers, profile_readers}
ParentRequest {report_version, run, attempt}
ChildReport {v, run, attempt, outcome, fault_code, diagnostic_ref}
IncompatibleReport -> machine pause, never task failure
```

Migration: add a stable admission-failure report for profile/read/skew faults instead of scanning stdout. Negotiate the old parent's report revision before exec/fallback and preserve that encoder for the life of the parent. Close the `kind` vocabulary or provide an explicit unknown fault variant; do not treat transport/reader incompatibility as evidence against the bead.

**Proof test:** old parent receives new child success, pause and unsupported-schema replies during a hop. Success remains success, incompatibility becomes machine pause, and no task-failure or slot-broken counter increments. Change the entire profile diagnostic text and preserve the same result. This addresses incidents 2/3/9 at the process contract, separate from A.F06's PID identity defect.

### F11 — P2 — refuse-and-redo: typed dashboard requests have no client/server compatibility agreement

**Evidence:** POST uses strict `wire.load` but unversioned request types (`src/taskloop_dash/api/writes.py:62–72`); Result carries only ok/message (`packages/kernel/src/tlkernel/dash.py`, Result/WRITES). `src/taskloop_dash/http.py:82–91` catches malformed JSON, not backend exceptions. `src/taskloop_dash/static/js/api.js:29` reloads on a changed server code hash only after successfully decoding a snapshot; lines 84–92 reduce non-2xx replies to HTTP text. Snapshot/bead/live have v1, but the JS reads data without checking v at lines 28–30 and 113–118.

**Failure:** after a server update, an old tab can send a stale strict request before its next successful snapshot reload. It gets an unexplained 400 or a dropped connection on a backend exception. There is no stable refusal code for “client too old,” “target superseded,” or “backend unavailable.” A code hash reload is a convenience, not write admission. A.F09 owns the specific expected-ask race; fixing that field alone does not fix protocol skew.

Target interface:

```text
Command {api:1, request_id, expected_server?, payload}
Reply {api:1, request_id, ok, code, message, target_revision?}
GET /api/version -> supported_api_versions
unsupported -> 409 typed reply before backend dispatch
```

Migration: first give all error paths a typed Reply with stable codes, including exceptions and oversized bodies. Add optional API revision accepted by both old/new server during rollout, then require it for writes. Make JS validate response versions before replacing state or submitting commands. Carry expected object IDs/revisions through ports as required by A.F09.

**Proof test:** hold an old tab across a server upgrade, submit before polling, and assert explicit incompatible-client refusal with no backend call. Inject BdFailure/OSError and oversize JSON, assert parseable consistent errors, and verify a compatible client still receives business refusals without interpreting message text.

## Evolution rules: who bumps what

**Refuse-and-redo the present practice** of using a plugin release number, a record V, a JSON schema and an informal fixture as interchangeable proof of compatibility. They are different artifacts. F01, F07, F10 and F11 supply the target interfaces, rollout steps and proof tests for this policy.

| Change | Additive or breaking? | Required owner/action | Verdict |
| --- | --- | --- | --- |
| Add optional telemetry under an explicitly open extension object | Additive only when old readers ignore it | Producer adds it; consumer's extension test proves compatibility | Keep this limited rule |
| Add defaulted field to ordinary Rec | **Breaking for old readers**: unknown keys forbidden | Record owner bumps writer revision; ship old/new reader matrix and migration before writer | Refuse-and-redo F07/F10 |
| Add required field, remove/rename field, change units/defaults or semantic meaning | Breaking even if JSON types unchanged | Schema owner bumps semantic revision; explicit converter or next-run cutover | Refuse-and-redo F07 |
| Add enum member to closed scope/permanence/retry/execution vocabulary | Breaking for old readers | Delegate or tl contract owner bumps supported revision/capability; unknown execution never defaults to OK | Refuse-and-redo F02/F03 |
| Add open stop reason preserving closed facts | Structurally additive; operational compatibility requires facts-driven fallback | Delegate owns reason facts; tl tests unknown reason uses those facts and preserves original reason | Keep open reason, refuse independent permanence reconstruction under A.F07 |
| Add run flag or change advisory/enforcement semantics | Required capability change, not harmless optional syntax | Delegate publishes actual parser feature; tl declares requirement; pair admitted before claim | Refuse-and-redo F01 |
| Change status schema | Independent of run answer revision | Delegate owns status v; tl routes all consumers through one checked reader | Refuse-and-redo F03 |
| Change bd JSON/errors | Upstream protocol change | bd supplies codes; tl adapter owns supported dialect and fixture refresh; caller never parses words | Refuse-and-redo F04/F05 |
| Change git/gh command output handling | Operation-specific compatibility change | Adapter owner supplies checked parser and opaque raw diagnostic; never universal English regex | Refuse-and-redo F09 |
| Change dashboard write grammar/results | API change independent of server code hash | Server/JS owner updates supported API revisions and stale-client tests together | Refuse-and-redo F11 |
| Update vendored delegate fixtures | Evidence update, not a runtime handshake | tl integration owner records producer build/digest and imports authoritative contract fixtures; test real parser acceptance | Refuse-and-redo F01/F02 |

There must be one generated compatibility manifest containing writer revisions, readable revisions and required subprocess features per released artifact. The release owner publishes it; the admission/hop code enforces it. A version bump made only in prose is not a release gate. Do not mark a stale or foreign authoritative document absent; migrate it explicitly, pin its compatible reader, or stop before mutation.

For inherited refusal rows, retain the earlier findings rather than duplicate beads. Their required interface work is:

| Prior finding | Target interface (at most five lines per cell) | Small releasable migration | Proof |
| --- | --- | --- | --- |
| A.F03 / D.F05 | `mutate(bead, expected_actor, expected_generation, effect) -> Applied | Stale | Unavailable` | fail closed first; then atomic conditional mutation; upgrade every writer | retake between old guard/write cannot close, push or checkpoint |
| A.F02 / D.F04 | `mutate_tree(DirectoryLease, ExpectedHead, operation) -> Receipt` | read-only probes first; require lease at all mutation entries; retire bypasses | concurrent foreign live engine makes cleanup/reset refuse |
| A.F04 | `admit_hop(current_state, candidate_manifest) -> Migration | Refuse` | strict reads; pre-hop compatibility probe; retained checkpoint/converter | new writer/old rollback never restarts from absent state |
| A.F05 / D.F10 | `EffectiveProfile {schema,digest,commit,engine,slots,loop}` | snapshot engine and slots together; persist; carry on resume/hop | main fast-forward cannot alter admitted run policy |
| A.F06 / A.F11 | `Execution {id,birth,process,successor}` | publish stable ID; acknowledge takeover; retire predecessor | real uv chain plus concurrent stop leaves one logical owner |
| A.F07 / D.F11 | `Pause {episode,reason,facts,wake}` | persist every pause; scheduling reads one decision; dedup by episode | owner-only pause cannot timer-wake; second network pause advances deadline |
| A.F09 | `answer(expected_ask_id, action, text) -> Applied | Superseded` | add optional expected ID end-to-end; require on owner writes | replacement ask between read/write receives no old answer |
| D.F02 | `GatePass {captured_tree,captured_base,profile_digest,results}` | keep captured identity; compare before mint/push; reject drift | concurrent mutation cannot certify another tree |
| D.F07 | `Completion {delivered,synced,closed,pending_effects}` | retain pending settlement; retry outbox; expose partial completion | pushed code plus failed bd close retains actionable obligation |
| D.F12 | `CommittedCall {envelope,memo,cursor_ack}` | publish recoverable memo first; then consume; retire only after cursor | kill between writes never dispatches same completed call again |

## Top 10

Ranks are contract-specific. F11 remains a P2 finding outside the ten; inherited state races keep their earlier rankings and are not counted twice.

| Rank | Priority | Finding | Concrete risk |
| --- | --- | --- | --- |
| 1 | P1 | F04 — malformed bd success becomes absence | live ask closed; exact-key lookup unsafe |
| 2 | P1 | F09 — git read failure becomes clean/empty | prerequisite refusal is impossible for callers |
| 3 | P1 | F08 — gate-plan base ignored | stale plan can suppress current checks |
| 4 | P1 | F02 — decoder invents execution OK | containment facts/defaults and malformed collections misread |
| 5 | P2 | F01 — actual incompatible contract-3 parser admitted | pinned writer cannot run on sibling delegate |
| 6 | P2 | F10 — parent/child report skew becomes bead failure | update charged against work rather than machine |
| 7 | P2 | F03 — unchecked status dialects | wake/admission disagree; false online probe |
| 8 | P2 | F07 — policy/state evolution has no enforced grammar | profile defaults and state enums change invisibly |
| 9 | P2 | F05 — bd English controls recovery | lint/sync/error reclassification on wording changes |
| 10 | P2 | F06 — slot CLI aliases transient and broken | external caller can recreate long slot exile |

## Beads to file

No tracker commands were run; these are proposed titles and scopes, not filed issues. Do not duplicate the inherited A/D beads, and revalidate their stale claims against the fixes noted above.

- **P1: Reject malformed bd read responses instead of returning absence** — implement Found/Missing/Fault and completeness; prove ask reconciliation and follow-up lookup preserve state on malformed exit-0 output (F04).
- **P1: Make decision-critical git reads fail explicitly** — typed status/diff/ref failures, machine push outcomes and path framing; prove errors cannot authorize cleanup or check skips (F09).
- **P1: Bind gate-plan decisions to requested inputs** — compare v1 base immediately, then add v2 tree/path/registry identity and stale-reply tests (F08).
- **P1: Validate delegate execution facts without success defaults** — reject unknown worker ends and malformed collections; reconcile process exit with envelope and retain raw evidence (F02).
- **P2: Refuse delegate pairs missing required run features** — check current run_args before claim, then publish semantic capabilities; sibling-parser matrix covers pinned writes (F01).
- **P2: Negotiate child report version across exec and rollback** — stable admission fault replies, no log parsing, no bead-failure charge for incompatible reports (F10).
- **P2: Unify and version-check delegate status and network decoding** — one reader for lanes/roles/usage, strict booleans, supported status revisions (F03).
- **P2: Version repo policy and close lifecycle vocabularies** — schema0 migration, explicit schema/features, versioned Owned/Carry and closed CallPhase; publish evolution matrix (F07).
- **P2: Replace bd diagnostic parsing with coded errors** — upstream structured lint/sync faults plus pinned legacy adapter until supported; preserve multiline evidence (F05).
- **P2: Preserve transient slot failures in public CLI results** — versioned JSON fault result, migrate callers, separate transient exit from broken (F06).
- **P2: Negotiate dashboard write protocol and normalize errors** — stable refusal codes, stale-client admission and exception/oversize replies; retain A.F09 expected-object identity (F11).
