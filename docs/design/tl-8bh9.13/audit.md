# Untouched files and behaviors without a complete disposition

Task: tl-8bh9.13. Evidence checked 2026-11-09. Recommendations remain proposed unless an existing owner decision
is explicitly identified. This is a gap analysis, not successor feature completion or a cutover receipt.

## Exact comparison

Reference: `731b7c76ef214ce35229f77814f98b6e1d6d5c0f`, the recorded baseline before successor construction.
First successor source change: `256d4643ba899cdd7e68e655a071a093a37c74b9`.
Compared head: `fffbc4e99581b38ff94b288fd58b683ae30d8d91`.
The later audit documents themselves are outside this frozen comparison. This interval is the successor change
series; it does not pretend to establish when every earlier design conversation or external-library edit began.

Git tree comparison and every changed path in `git log --name-only <baseline>..<head>` agree: all 198 surviving
byte-identical paths were never changed in this interval. No modified-then-reverted path hides in that set.

| File category | Count | Meaning |
|---|---:|---|
| Baseline tracked files | 2,570 | Includes source, tests, documentation, tools and configuration |
| Deleted paths | 2,357 | Deliberately absent from the successor; not individually certified as reviewed |
| Modified paths | 15 | Includes the retained package initializer and rewritten build/instruction assets |
| Added paths | 52 | Includes successor source, focused tests and the redesign documents |
| Surviving paths never changed | 198 | 173 Markdown/text documents or fixtures, plus the 25 paths below |
| Current tracked files | 265 | Before this audit's new documents |
| Baseline production Python files | 842 | Python under src, or packages/*/src; excludes tests/dev/docs |
| Unchanged surviving production Python | 0 | 841 baseline production files deleted; initializer modified; current source has seven files |

[files.tsv](files.tsv) accounts for every path in the union: 2,622 records, including old/current blob IDs,
change history, inspection evidence and a current disposition. It includes all 198 untouched paths rather than
only a shortlist. The earlier adapter inventory covers 38 modules. This pass read selected regions of additional
source and their callers; it did not read all 842 production files line by line.

The inventory's exact-path references are search aids only. No reference, an existing reference, deletion and
selected-region inspection are different evidence levels. In particular, no exact-path mention does not prove
that nobody ever discussed a file. Documentation using a basename or a broader workflow is not counted by that
literal search. Do not use its counts as a percentage of architecture coverage.

## All 25 unchanged paths outside Markdown/plain text

| Paths | Count | Assessment and recommendation |
|---|---:|---|
| .agents/skills/beads/agents/openai.yaml; .beads/.gitignore, config.yaml, metadata.json and hooks/{post-checkout,post-merge,pre-commit,pre-push,prepare-commit-msg} | 9 | Task-tracker integration, not factory machinery. Retain; no deletion authority from this audit. |
| .claude/settings.json; .codex/{config.toml,hooks.json}; .cursor/{hooks.json,rules/beads.mdc} | 5 | Inspected callbacks invoke bd, not the removed task-loop hooks. Retain tracker integration. |
| .gitignore; .python-version; mise.lock; LICENSE | 4 | Repository rules, interpreter/tool pins and licensing. Pins match current declarations. Retain. |
| .task-loop.json | 1 | Historical recipes name removed dev/affected.py and old just targets. No successor profile reader exists. Known latent cutover gap, already acknowledged in foundation evidence; preserve until the normal profile task replaces it. |
| docs/design/dashboard/{dash-round-6b.html,dash-round-7b.html,dash-round-8b.html,dash-round-9-app.html,dash-round-9.html} | 5 | Historical UI prototypes, excluded from the installed package. No fetch/WebSocket callers found in these files. Preserve design evidence; no live factory workflow demonstrated. |
| docs/design/spike/artifact-add-server.py | 1 | Explicit throwaway spike referenced by its design. No current activation/package path found. Do not promote it to the production artifact owner. |

No live obsolete factory activation was found in those 25 paths. This does not audit installed plugin caches,
external launchers or the person's other checkouts. Existing Beads hooks are distinct from factory hooks removed
from the foundation; their final product retirement remains proposed in the operations review. No process, hook,
configuration or existing user-evidence file was changed during this analysis.

## Gaps found by following the old behavior

All baseline source paths below refer to the exact reference revision above. The removed source is available
through Git history; a read-only extraction at /tmp/taskloop-gap-baseline-731b7c76 was used for rg and source reads.
These are not claims that an old service is running in the successor.

Source shorthand: kernel/, work/, asks/, land/, dash/ and artifacts/ mean packages/<name>/src/tl<name>/;
delegate/ means packages/delegate/src/delegate/. app/ means src/taskloop/app/. Full paths and blob IDs are in
the inventory. Shared shelf-library source and edits are outside this factory-repository comparison.

| Behavior and concrete source | Recommendation and what disappears | Existing owner |
|---|---|---|
| A second protected-file approval gate: kernel/trustroots.py:13-33 includes .task-loop.json, mise.toml and agent instructions; work/write/review_round.py:39, app/workers/worker_request.py:58 and land/lander.py:83 call it before review/land. | Do not carry overlapping special profile approval. This implements the existing decision, but the hidden second caller path was not fully dispositioned. Losing that gate must not remove admitted execution permissions or deliberate reviewer instruction-source selection. | tl-8bh9.1.3, .4.3 and normal land/review |
| Review verdict rewriting: work/review/findings.py:94; work/work/ledger.py:44; work/review/routing.py:63-115; caller work/write/review_round.py:145. Word overlap and prose categories suppress unmet findings or turn them into follow-ups/unverified delivery. | Remove lexical completion authority; use the one required review's structured acceptance disposition. Lose automatic suppression of repetitive or impossible reviewer demands. Explicit unmet acceptance remains blocking unless actually resolved or its scope deliberately changed. | tl-8bh9.3.1 and tl-br2.19; .5 check/review consolidation |
| Automatic stray-file quarantine: work/write/newfiles.py:56-71 moves unexplained untracked files to evidence/strays; land/lander.py:165, land/tries.py:87 and land/rebase.py:282 call it. | Do not carry automatic movement based on plan/reviewer classification. Preserve unresolved files and return the issue to the owning agent. Lose automatic clearing of a worktree to allow land. This follows the accepted preservation/completion contract. | tl-8bh9.2, .3.3 and .9 |
| ADR prompt/reuse/aging subsystem: work/plan/decisions.py:30-49 injects newest 20 decisions with 600-character truncation; adrsync.py:9-21 retains stale cached decisions on read failure; kernel/adrs.py:70 counts citations. asks/raiser.py:28-39 attaches matching decisions; asks/stick.py:69-77 files retirement tasks. | Propose leaving out citation counters, similarity policy, aging suggestions and dedicated retirement-task machinery. Keep deliberate Git-owned decisions and task-associated answers. Lose repeat-question hints and automatic reminders. Matching does not itself answer a question; prune files a task, not an age-based deletion. .6.1 previously said inspect/remove, not an agreed blanket cut. | tl-8bh9.6.1, STORE .26.9 and .7 |
| Planning assumption conversion: work/plan/planner.py:139 and :194 invoke work/plan/assume.py:29-59 to convert questions/missing references into assumptions or deferred matches, sometimes with another model call. | Keep reasonable explicit assumptions in the committed plan; remove blanket conversion of unavailable essential evidence and the separate correction machinery. Lose automatic continuation through missing references. Typed planning result distinguishes a usable assumption from a blocking unknown. | tl-8bh9.3.2, .6.1 and .4.3 |
| Historical account/model circuit breakers: delegate/domain/health/ledger.py:27, app/fleet.py:112 and app/run.py:340-355 fold history into benches and launch a separate 30-second model canary. | Propose deferring the bench/canary policy. Keep actual provider restrictions and the accepted bounded retry owner. Lose automatic shielding of other tasks from repeatedly failing account/model pairs; avoid carrying another log-derived policy owner and extra model calls without a demonstrated need. | tl-8bh9.4.3, tl-7i9k.56.1 and quota tl-7i9k.16 |
| Account capacity ignores a still-live lease after output silence: delegate/domain/accounts/leases.py:9-29 and app/lease.py:65. | Remove silence-based capacity release. Count occupied capacity through its execution/permit owner until safe release is established. Lose speculative capacity recovery before the watchdog actually stops the worker. Static code confirms the exclusion; no concurrency collision was reproduced. | tl-8bh9.4.2/.4.3/.4.5 and execution ownership |
| Dwell state and min_dwell_minutes: delegate/domain/routing/dwell.py, router.py:31, app/decide.py:256; picker.py:17-27 returns the first usable account. | Leave out the unused dwell policy/state. The audited picker does not read it; no demonstrated selection behavior is lost. Constructor/state writes and a setting are not evidence of effective anti-flapping behavior. | tl-8bh9.4.3 and configuration simplification |
| Account discovery can change authorization/config: delegate/app/fleet.py:73-88 enables a ready undecided account for this call; app/run.py:117/app/decide.py:269 persist enables. | Propose read-only discovery/status plus explicit account enable/decline configuration. Lose automatic onboarding of already-configured accounts. Do not silently restore this policy while migrating mechanisms to shelf. | tl-8bh9.4.3 and configuration owner |
| Provider routing carries concrete quota/billing policy: delegate/domain/accounts/account.py:49-104; app/usage.py:71; app/harnesses.py:21 and launch.py:273/:302; domain/routing/tiers.py:19/:54. | Keep native allowance/freshness/reset facts and subscription/free-only constraints when each provider is introduced. Defer multi-provider ladders; explicitly assess reserves, relaxed ceilings, strain concurrency and cross-model aggregation. No task money/token budget is not permission to drop provider restrictions. Lose policy if indiscriminately deleted; copy speculative scheduling if indiscriminately retained. | tl-8bh9.4.3, tl-7i9k.16 and configuration owner |
| Dashboard learning/ADR governance: dash/views/learning.py computes weekly ask/repeat/durable/send-back metrics; static/js/views/decisions.js:97-118 offers unused-30-day ADR prune; snapshot.py builds both. | Propose deferring the learning-score and age-based decision-governance UI. Keep task history, linked decisions and actual per-attempt usage. Lose those weekly summaries and prune suggestions. This is additional scope beyond the already-agreed removal of automatic reflection/digest. | tl-8bh9.7 and .6.1 |
| Artifact storage optimization: artifacts/keep.py:49-118 scans earlier evidence, compares bytes, hard-links duplicates and accounts against a cap; store.py:46-49 uses it per add. work/look/shots.py:51 also uses it. | Propose leaving out cross-attempt dedup/inode accounting until measured need. Keep exact-content references, validation, explicit refusal/limits and owning publication/readers. Lose storage savings; no quantified performance claim. The normal add path raises Refused on cap exhaustion; it is not a silent successful drop. | tl-8bh9.7.6 and .8.5 |
| Check environment shaping: kernel/childenv.py:62-124 strips ambient environment/credentials or substitutes HOME/XDG; app/checks/shell.py:107 consumes it independently of the network prefix. | Preserve intentional per-call environment and avoid accidental factory-environment leakage. Assess scratch-HOME and credential filtering before restoring them wholesale. Normal host networking does not decide these behaviors. No new environment framework proposed. | tl-8bh9.5.1, .4 and .8 |

## Untouched instructions and deleted tools also matter

The unchanged skills/task-loop/SKILL.md still advertises tl run-task, file checkpoints, cached passes, automatic
ownership recovery and blanket merge authorization. Lines 8-15 alone conflict with the lightweight skill and
actual current command set. Its removal/rewrite is already owned by tl-8bh9.8.6; the file's unchanged bytes are
not retained product requirements or current authority. Prior instruction review was directional, not adoption.

Developer tools have three useful purposes whose individual disposition was missing from the broad tool review:

| Baseline file | Preserve the purpose, assess the mechanism |
|---|---|
| dev/killpoints.py:6 | Test crash boundaries before an effect, after it and after state acceptance. Use the actual new STORE/land/attempt owners; do not copy old checkpoint runtime. |
| dev/record_exchange.py:6 and record_corpus.py:6 | Owner-selected prompt/answer replay examples. Defer a replacement until the execution consumer exists; assess library-owned recording support then. No automatic harvesting or new agent-analysis service. |
| dev/dash_check.py:6 | Fixture-backed browser acceptance and phone/desktop screenshots when dashboard work exists. Do not restore the old server/runtime just for its harness. |

The dependency-graph Goals view (dash/static/js/views/goals.js) is presentation, not a scheduler. Removing areas,
manual queue ordering or epic scheduling does not itself justify deleting useful dependency visualization. Defer
the particular UI until the shared task/read model exists; do not reintroduce separate ordering policy through it.

## What to do with the gaps

Recommendations are routed to existing task owners, not a parallel backlog in this document. Apply settled
removals while implementing their consumers; explicitly decide the proposed ADR/health/analytics/storage extras
before carrying them. Retain provider correctness and crash/acceptance scenarios without retaining the old machinery.
Do not restore a package because it contains one useful behavior.

This pass found concrete missing dispositions. It does not establish an exhaustive behavior audit of kernel,
providers, HTTP/browser behavior, all dev tools or all tests. No live Unity/model run, provider billing test,
cross-process collision reproduction or runtime test suite was executed. The file enumeration is exhaustive for
the exact Git comparison; the source-read/caller audit is intentionally bounded and labeled as such.
