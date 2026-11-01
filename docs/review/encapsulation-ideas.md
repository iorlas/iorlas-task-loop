# Lens 6 — idea/workflow: shrink the factory until its promises mean something

Static review, 2026-11-01. Verdict: **refuse-and-redo the workflow model**. The owner's product is an autonomous factory that lands reviewed code from beads, safely, cheaply, and observably. The implementation sells a much larger product: a planner repair service, model-family traffic controller, live software upgrader, tracker-backed resource manager, and operator console. Every extra product gets its own recovery vocabulary. The owner pays for the joins.

Read [architecture](architecture.md) and [dataflow](dataflow.md) first; references below use **A.Fxx** and **D.Fxx**. Those findings own their specific races, crash windows, and fixes. This review challenges the features that keep creating those obligations. It does not relabel those bugs as new discoveries. All implementation evidence below was read with numbered source lines. No tests, git, task-loop commands, network, credential files, or files outside this tree were accessed. `_delegate/` is the supplied source copy, not proof of the installed router's behavior. Proposed tests are acceptance requirements, **untested** here.

P1 means the product can authorize delivery without the promised evidence, or unnecessarily changes its execution contract during work. P2 means an unattended workflow can waste capacity, misclassify work, or mislead its owner. P3 means avoidable conceptual or operational burden.

## The deletion decision

**Keep** beads as the requirements inbox and dependency graph; git as the code delivery authority; persistent workspaces for expensive setup; a deterministic executor for repository checks; independent review; bounded recovery; an operator inbox. Those are the factory.

**Delete** automatic engine hops inside a task, arbitrary public stage selection, word-overlap acceptance certification, and a separate lifecycle for each spelling of waiting. **Merge** the retry budgets, execution state, and completion obligations. **Refuse-and-redo** the assumption that any ready bead is a production job. **Untested**: the economic superiority of fresh reviews after every stage and of a different model family after every write. Neither source inspection nor old trace counts prove that these are the cheapest way to obtain reviewed delivery.

The smallest useful factory admits an immutable job, reserves one workspace, plans once, writes with cheap feedback, checks a candidate, obtains independent review of that candidate, lands it, and settles its obligations. Failure preserves the candidate and names exactly what change permits another attempt. A scheduler repeats that operation. A dashboard shows its recorded facts. Nothing in this minimum requires replacing the running engine.

## I.F01 — P1 — Refuse-and-redo: live self-update is the wrong product feature

**Evidence.** `src/taskloop/app/run/reload.py:68` defines step-boundary replacement; line 88 switches to the discovered install and line 119 executes it through the script runner. `src/taskloop/app/write/stage_loop.py:45` does this before ordinary writes. `src/taskloop/app/run/run_once.py:177` explicitly moves before land so close and land use the newest code. Delegate selection independently changes per call at `src/taskloop/app/run/delegation.py:12` and line 24. `src/taskloop/contracts/config.py:248` deliberately gives a person-written profile no version.

**Why the idea fails.** The most consequential operation, delivery, is deliberately handed to code that did not admit the job or accept its stages. A stage boundary is a cursor position, not a proof that new code understands every prior decision. The factory gains no delivered-code value from upgrading in the middle of one bead. It buys a distributed upgrade protocol across engine, router, profile, checkpoint, and worker session instead.

**A.F04 is too soft:** negotiating checkpoint ranges still preserves an unnecessary live-upgrade feature. A.F06 and D.F10 document further costs of that choice. Do not repeat those repairs as the product plan. Delete the feature. Checkpoint recovery is valuable; live replacement is not a prerequisite for it.

**Target interface (4 lines).**
```text
admit(bead_revision, profile_revision, engine_digest, delegate_digest) -> Job
start(Job, workspace) -> Attempt
resume(Attempt, same_execution_bundle) -> Attempt
upgrade_factory(bundle) -> next_job_default
```

**Migration.** First record and retain the admitted execution bundle and profile snapshot. Then stop re-resolving delegate during that job and disable engine safe-point hops. Finally move upgrade/rollback to drained workers between jobs; retain an explicit offline migration command for old interrupted jobs. A newly unsupported profile rejects admission before any claim; changing the main checkout cannot mutate an admitted job.

**Proof test.** Install bundle B and advance the served repository's profile while A is writing. Every later call and land in that job must use A and the original profile; the next admitted job uses B. Kill A and recover from its retained bundle. An unavailable retained bundle produces an owner wait, never a fresh plan under B. This targets incidents 2, 3, 9, and 10 by removing their mid-job trigger.

## I.F02 — P1 — Refuse-and-redo: naming an acceptance item is not proving it

**Evidence.** `src/taskloop/domain/review/switch.py:15` lets `review-off` override the profile. Lines 25–32 decide coverage by shared words: at least two, and half of the shorter side. `src/taskloop/app/write/review_round.py:51`–64 uses that coverage to permit the last stage to skip its reviewer. `tests/review/test_review_switch.py:56` explicitly expects landing with zero reviewer calls. The test at line 31 checks missing vocabulary, not contradictory behavior.

**Why the idea fails.** The same generative pipeline can write a criterion and supply a command whose output does not establish it. Shared words do not make the command an independent oracle. “Account deletion preserves audit history” and “account deletion removes audit history” can share enough words to pass this coverage test. A green command named with either sentence proves only what the command actually asserts. The product promised reviewed code; it quietly substitutes a lexical match.

This is additional to D.F02: even perfectly bound tree/base evidence can be evidence for the wrong behavior. It is also separate from D.F06's draft-plan validation window.

**Target interface (4 lines).**
```text
Criterion(id, requirement_revision)
Evidence(criterion_id, candidate_digest, approved_oracle_id, result)
Review(candidate_digest, criteria_revision, findings, reviewer_identity)
authorize_delivery(candidate, required_evidence, Review) -> Permit
```

**Migration.** First stop treating `covered()` as authority to bypass final review. Next assign stable criterion IDs and let repository policy name approved deterministic oracles. Then retire `review-off` as an ordinary bead label; any exceptional delivery waiver must be an explicit owner decision attached to the candidate. Keep deterministic mechanical-change exemptions only where a specific invariant is proved, and display the exemption rather than calling it a review.

**Proof test.** A negated criterion and an unrelated green command with matching nouns must not obtain a delivery permit. Changing the candidate invalidates its review. A bead label alone cannot remove the job's required review.

## I.F03 — P2 — Refuse-and-redo: replan is being used as a universal repair button

**Evidence.** `src/taskloop/app/write/check_round.py:84`–95 nests check tries inside rounds; exhausted rounds return REPLAN. A writer calling a check impossible also requests REPLAN at lines 59–70. `src/taskloop/app/write/review_round.py:185`–188 turns review exhaustion into the same action. `src/taskloop/app/run/run_once.py:197`–207 increments another counter, clears the accepted index list, and asks the planner again. Defaults at `src/taskloop/contracts/config.py:205`–220 include separate rounds, check tries, replans, fix rounds, same-red, and total-review caps. `src/taskloop/app/plan/planner.py:74`–82 separately exempts some owner/comment amendments from its planner count.

**Why the idea fails.** These are different causes with the same expensive remedy. A wrong implementation may need a patch. An impossible repository command needs a configuration fix. A capacity stop needs availability. None inherently needs a new decomposition. Finite caps prevent infinity; they do not make repeated unproductive computation useful. A model can change its prose without changing the evidence that caused failure.

**Keep** same-red detection and hard cost caps. **Refuse-and-redo** the default automatic transition from round exhaustion to planning. The old study at `docs/design/stages.md:89` already describes repeated plans that cannot change engine checks. That historical report is **untested** against today's implementation; it remains a reason to demand a discriminating cost test, not permission to quote old outcomes as current measurements.

**Target interface (4 lines).**
```text
Failure(cause, scope, evidence_digest)
next_action(failure, changed_inputs, remaining_job_budget) -> Repair | Wait | Revise
Repair(candidate, failure) -> candidate
Revise(new_scope_revision, reason) -> new_plan_revision
```

**Migration.** First record one failure signature and total job expenditure across the existing counters. Next require a typed explanation of what input changed before repeating a failed operation; allow a bounded transient retry. Then replace ordinary automatic replans with one targeted repair allowance and an explicit blocked condition. Replan only for changed scope or a diagnosed invalid decomposition. Owner-approved extra spending remains possible but cannot erase prior spending.

**Proof test.** Repeated identical compiler output with an unchanged candidate cannot consume a fresh planner budget. A provider outage never calls the planner. Changed acceptance creates a new plan revision while preserving old receipts and charging the same job ledger. Compare dollars and successful delivery on a fixed failure corpus before adopting the new default; that economic result is currently **untested**.

## I.F04 — P2 — Refuse-and-redo: “another family per stage” is ceremony without a stable review object

**Evidence.** `src/taskloop/app/write/review_round.py:36` passes the writer's family into each review call. Lines 146–152 warn when the actual result is same-family, but the acceptance rule at lines 167–174 still accepts a clean answer. Review can also be off, sampled, or mechanically skipped at lines 31 and 43–82. `src/taskloop/app/run/run_once.py:172` pushes WIP after each accepted stage and lines 181–195 may then rebase before the next stage. `docs/design/stages.md:30` describes fresh reviewers; lines 76–81 report historical no-change writes and repeated reviews.

**Why the idea fails.** Family diversity is a routing preference, not evidence of independence, correctness, or coverage. Intermediate review may be useful for a risky interface, but the factory's useful artifact is the final candidate. Making review frequency follow planner-created stage count makes cost depend on arbitrary decomposition. Advertising another family while accepting a warning-only fallback also makes the claimed policy impossible for the owner to rely on.

**Keep** independent final review and early review for explicitly high-risk changes. **Untested**: whether always using another family improves escaped-defect rate enough to justify its availability/cost penalty. Do not claim the opposite either.

**Target interface (4 lines).**
```text
ReviewPolicy(required_independence, early_review_triggers)
review(candidate_digest, acceptance_revision, check_receipts, policy) -> Review
repair(candidate_digest, Review.findings) -> new_candidate
permit(candidate_digest, Review) -> Permit | Wait
```

**Migration.** First record actual reviewer identity, independence, candidate digest, and exemption. Next make unavailable required independence a visible wait; remove silent weakening of that policy. Then run a single final-candidate review by default, retaining early review only for named risks. Evaluate intermediate-review savings and escaped defects before deleting the old option.

**Proof test.** A final candidate with an unreviewed changed file cannot land merely because earlier stages were accepted. A same-family result cannot satisfy a policy requiring another family. Two equivalent plans with different stage counts incur the same mandatory final-review count. Economic benefit remains **untested** until measured.

## I.F05 — P2 — Refuse-and-redo: check scheduling policy has become a harness permission requirement

**Evidence.** `src/taskloop/domain/checks/writer_split.py:13`–15 and lines 25–35 derive engine-only status from duration, command-name heuristics, container needs, and overrides. Lines 37–44 export only exact two-token `just recipe` commands as enforceable recipe names. `_delegate/src/delegate/domain/routing/router.py:16`–19 limits enforcing runners; lines 39–49 filter write lanes accordingly. Task-loop automatically turns restrictions advisory when a pinned family and recipes coexist (`src/taskloop/app/run/worker_request.py:21`–38).

**Why the idea fails.** “This command is expensive” is a scheduling fact. “This worker is authorized to execute it” is a capability fact. A learned duration crossing a threshold should not change which model family can write code. Pinning a family should not implicitly decide that a restriction can be weakened. The syntax restriction also makes equivalent commands receive different handling. The owner ends up debugging model availability to solve a build scheduling problem.

**A.F08 is too narrow for the product decision:** a request handshake is necessary for the present interface, but it cannot justify coupling these policies. The supplied delegate parser at `_delegate/src/delegate/cli/parser.py:62`–67 exposes the older run flags; the installed pair and newer advisory semantics are **untested** here. This review does not repeat A.F08 as a new compatibility finding.

**Target interface (4 lines).**
```text
Check(id, argv, resources, cost_class)
request_check(attempt, candidate_digest, check_id) -> Receipt | Wait
WorkerCapabilities(files_write, command_policy)
route_worker(role, required_capabilities, family_preference) -> Worker | Wait
```

**Migration.** First distinguish hard denied commands from the advice to leave slow work to the executor. Remove automatic advisory inference from family pins. Next use check IDs and one executor/resource lease for expensive checks; workers request results instead of guessing command ownership. Finally remove recipe-name enforcement as the scheduler's lane-selection mechanism. Genuine hard command restrictions still require an enforcing harness or an admission refusal.

**Proof test.** Changing historical duration from 59 to 61 seconds changes scheduling advice, not writer capability. Pinning a family cannot change a hard denial into advice. Equivalent registered commands share one check identity and resource policy. An unsupported hard restriction stops admission with its actual cause, addressing incident 4 without merely polishing its text.

## I.F06 — P2 — Refuse-and-redo: a bead is an inbox object, not necessarily a production job

**Evidence.** `src/taskloop/app/loop/queue.py:140`–145 excludes epics, open-child umbrellas, and slot labels. `src/taskloop/app/run/run_once.py:129`–131 requires acceptance prose. `src/taskloop/app/plan/planner.py:169`–181 blocks an empty implementation plan and handles existing work/follow-ups separately; lines 197–200 use stage count to ask whether the ticket is too big. `README.md:57`–59 makes a reusable workspace itself a bead with a claim and lease.

**Keep** the current umbrella exclusion and NOOP block. They contain the old “umbrella done” failure; claiming that unconditional empty-plan closure still exists would be a bad review. **Refuse-and-redo** the larger assumption: labels, acceptance prose, and a model's stage count do not establish one bounded deliverable. A research request, approval, epic, infrastructure repair, and code change can all be valid beads but demand different completion evidence. Encoding a machine resource as another issue further conflates backlog state with resource state.

**Target interface (4 lines).**
```text
classify(bead_revision) -> Delivery | Research | Aggregate | Decision
compile(Delivery, repository_policy) -> Job | AdmissionError
Job(source_bead_revision, acceptance_ids, delivery_target, budget)
complete(Job, delivery_receipt, settlement_receipts) -> Completion
```

**Migration.** First add an admission result distinguishing executable delivery from valid non-delivery work. Then require a bounded delivery contract before taking a costly slot; route aggregates and research to explicit handlers instead of inventing code stages. Finally move slot inventory out of the tracker, keeping temporary slot-bead compatibility records until old clients drain. Do not make the planner auto-split and auto-close the parent as a substitute for owner scope.

**Proof test.** An umbrella, an owner approval, and a research bead consume no writer slot and cannot close as code delivered. A genuine already-satisfied delivery needs an explicit existing-delivery receipt or owner disposition. A large implementation is rejected before expensive setup, independent of how a model divides it into stages. This makes incident 6's category error impossible rather than maintaining another NOOP exception.

## I.F07 — P2 — Refuse-and-redo: the waiting vocabulary describes implementation accidents

**Evidence.** `src/taskloop/contracts/parks.py:18`–25 combines same-text question counts, run identity, pause reasons, retry time, and attempts. `src/taskloop/app/asks/parks.py:27` treats release of hold metadata as one park's wake; line 29 also reads the Ask store. `src/taskloop/app/loop/settle.py:94`–107 separately reconstructs pause/rest/role timing. Lease code heartbeats both task and slot beads (`src/taskloop/app/slots/lease.py:18`–38). Admission contention becomes Result.TAKEN at `src/taskloop/app/loop/verdict.py:72`–73.

**Why the idea fails.** The owner must learn claim, slot, lease, hold, lock, ask, park, pause, stop, taken, paused, and parked to answer two questions: who may act, and what permits progress? These are not twelve independent product concepts. A.F07 and D.F11 own concrete wake failures. Renaming their records without replacing the competing policies leaves the same product defect.

**Minimal vocabulary.** Keep **job**, **attempt**, **workspace**, **reservation**, **wait**, and **completion**. Claim is the tracker adapter's reservation projection; lease is reservation expiry; lock is a local enforcement primitive. Neither is another owner-facing state. Ask is an owner-action payload of a wait. Hold/park/pause become wait reasons. Taken is a rejected reservation request, not a job outcome. Stop is a command ending an attempt; its result must say whether the job is canceled or waiting for explicit restart. Paused and parked disappear as separate statuses.

**Target interface (4 lines).**
```text
Reservation(resource_id, attempt_id, generation, expires_at)
Wait(scope, cause, wake=Time | Capability | OwnerAction | ExplicitRestart)
JobState = Queued | Active(attempt) | Waiting(Wait) | Complete(receipts) | Canceled
transition(expected_revision, command) -> new_revision
```

**Migration.** First add the normalized state as a projection over legacy fields and show contradictions. Next make one transition owner write the wait and wake together; adapt queue, CLI, and dashboard to consume it. Then remove old independently writable park/hold/later policies. Preserve imported legacy waits as explicit owner waits when their wake cannot be established.

**Proof test.** Construction rejects a waiting job with no wake rule. Replaying a wait transition does not advance its retry episode. Contention cannot count as a failed bead. An owner stop cannot wake from a lane timer. These test the product invariant behind incident 7 rather than each spelling individually.

## I.F08 — P2 — Refuse-and-redo: public modes expose two orchestration products

**Evidence.** `README.md:31`–35 says run-task executes the recorded next stage, while lines 39–42 describe the full engine. `src/taskloop/app/run/stages.py:105`–131 runs one operation and calls an ordinary successful non-land step Kind.DONE. Its `finish_step` directly closes the bead and drops the checkpoint at lines 232–238. Full execution instead uses `RunOnce.close` and the closer (`src/taskloop/app/run/run_once.py:225`–245). `src/taskloop/app/launch/check.py:64` starts a separate stage run, and line 75 selects gate checks by default. The public registry advertises `check`, `gate`, `land-stack`, loop, and arbitrary `--stage` (`skills/task-loop/tl.py:18`, `:31`, `:36`, `:41`–43).

**Why the idea fails.** A user has to know whether success means “one step completed,” “task done,” “checks green,” or “delivered and settled.” Public access to internal cursor labels creates a second coordinator which must reproduce restore, validation, and settlement semantics. This is more than A's inventory of mutation paths: the two entry modes carry different meanings of completion by design.

**Target interface (4 lines).**
```text
run(job_id, until=Complete | NextTransition) -> JobState
inspect(job_id) -> JobState
check(candidate, check_ids) -> Evidence
deliver(candidate, Permit) -> DeliveryReceipt
```

**Migration.** First give step success its own transition result, never task DONE. Next drive continuous and single-transition operation through the same state machine; keep `run-task --stage` temporarily as a checked compatibility adapter. Then remove arbitrary stage jumps. Keep `check` as a diagnostic evidence producer; merge `gate` into its named policy. Keep `land-stack` only as a batch delivery adapter requiring a permit for every candidate, not another completion workflow. Loop only schedules jobs; it does not reinterpret their terminal facts.

**Proof test.** Drive the same scripted job continuously and one transition per invocation, injecting a restart at every boundary. The final receipts, follow-up obligations, and bead disposition must match; a successful plan-only invocation must never publish task completion. Existing stage tests are **untested** for this equivalence in this review.

## I.F09 — P2 — Refuse-and-redo: local slot quarantine is the wrong unit for shared infrastructure faults

**Evidence.** `src/taskloop/contracts/config.py:142`–144 sets two quick failures and a 720-minute set-aside default. `src/taskloop/app/loop/settle.py:42`–58 places a timed hold on one slot. Its quick streak is keyed by slot at lines 60–76. `src/taskloop/app/loop/verdict.py:54`–58 now requires typed slot-broken evidence and, for pre-engine faults, failed recovery. Separate network handling at `src/taskloop/app/loop/settle.py:78`–92 can stop new claims across the loop. `src/taskloop/app/run/budget.py:28`–29 excludes shared-resource waiting from charged minutes.

**Keep** typed slot-fault classification and the network-wide stop. The present code does not simply quarantine every fast failure; that would misstate incident 8's current containment. **Refuse-and-redo** the remaining product model: a failed setup using a shared package source, disk, or toolchain can manifest as broken setup in several slots. Putting each workspace aside for twelve hours treats a service failure as damaged equipment. Conversely, a timer expiring proves nothing about repair. Free budget waiting can still consume real workspace capacity.

**Target interface (4 lines).**
```text
Fault(cause, scope=Job | Workspace | Repository | Host | Provider, evidence)
Circuit(scope, fault_signature, retry_probe, next_probe_at)
admit(job, circuit_state) -> Reservation | Wait
probe(circuit) -> Healthy | Fault
```

**Migration.** First retain structured setup diagnostics and attach a scope to faults. Next introduce shared circuits before dispatch, using the existing network path as the first adapter. Then replace blanket slot timers with workspace-specific repair probes; release expensive reservations for external waits once all workers have actually stopped and the candidate is preserved. Genuine workspace corruption still quarantines that workspace.

**Proof test.** A shared setup outage across three slots opens one repository/host circuit after bounded probes and claims no further beads. It does not create three twelve-hour holds. One dirty or corrupted workspace quarantines only itself. A waiting provider neither holds a build slot indefinitely nor loses an active child through premature release.

## I.F10 — P2 — Refuse-and-redo: the Board draws a successful story from facts that do not establish it

**Evidence.** `src/taskloop_dash/views/columns.py:50`–59 chooses one column from ask, look, closed, or current phase. Lines 66–69 label a claim without a live run RUN. `dots_of` marks a phase done if visited, or every phase done if the bead is closed (lines 106–115). `tests/dash/test_dash_columns.py:106`–107 explicitly enshrines all-done dots for a closed bead. `src/taskloop_dash/views/needs.py:8`–9 admits that storm stops, a beadless network wait, and some parks are not shown. Lines 48–55 calculate readiness differently when there is no live loop.

**Why the idea fails.** Visiting a phase is not passing it. Closing a bead is not proof of checks, review, delivery, or settlement. A claim without a process is not running work. These are product semantics, additional to D's stale-cache discussion and A.F09's answer race. A perfectly fresh snapshot can still tell this false story. The Board currently makes the owner infer operational truth from a stage metaphor that falls apart during exactly the incidents that need supervision.

**Keep** the Board as navigation, its goal tree, the slot timeline, and the owner inbox. **Refuse-and-redo** stage columns as the primary operational status and green completion implied by traversal. Show queued, active, waiting, delivered-but-unsettled, complete, and canceled; keep phase as secondary text. A closed externally managed bead can be closed with execution evidence unknown.

**Target interface (4 lines).**
```text
JobView(revision, state, phase, wait, reservation, evidence, observed_at)
PhaseEvidence = Passed(receipt) | Failed(receipt) | Exempt(decision) | Unknown
FactoryView(circuits, available_workspaces, executable_queue, owner_actions)
owner_command(job_id, expected_revision, action) -> Accepted | Superseded
```

**Migration.** First stop painting closed/visited phases as passed and label claims without execution as reserved or orphaned. Next publish every circuit and wait from the engine, including when no loop is live. Then make the Board consume the same eligibility and state projection as dispatch, with age/unknown markers. Keep owner commands revision-bound; A.F09 owns the existing expected-ask repair.

**Proof test.** A manually closed bead with no receipts has unknown review/check dots. A failed visited check remains failed. A stopped loop with an outstanding park still shows its owner action; a provider circuit appears without any active bead. The executable count matches admission decisions for the same revision.

## Storage: merge authorities, not log files

**A.F12 is too soft:** relocating effectful contracts and removing aliases will improve code, but the product still asks recovery to join too many independently authoritative stories. **Refuse-and-redo** that ownership model. Do not turn this into a crusade against the number of files: full logs, raw answers, screenshots, and check caches earn their storage. The defect is the number of facts that independently authorize the next action.

Evidence: `src/taskloop/contracts/paths.py:93`–124 separately addresses delivery, park, checkpoint, owner request, exec pointer, network pointer, and follow-up outbox. `src/taskloop/stores/bundle.py:20`–36 exposes their separate stores alongside events, traces, checks, and loop state. `src/taskloop/contracts/checkpoint.py:74`–106 carries overlapping plan, writer, progress, review, and follow-up state; lines 176–180 add settlement receipts and cursor progress. This is the substrate of I.F01, I.F07, and I.F08, not an eleventh reissue of D's crash-window findings.

**Keep** the newly visible pending leftovers and follow-up IDs (`contracts/checkpoint.py:104`–105), and the durable outbox (`contracts/paths.py:122`–124). D.F03 and D.F09 describe earlier omissions; they must not be repeated as unchanged findings. Their end-to-end recovery is **untested** here. Also **keep** strict profile read refusal now visible in `src/taskloop/app/wire/slots.py:49`–65; A.F01/D.F01's silent malformed-profile fallback is not the current code at those lines.

The replacement has three authorities: bd for requirement revisions and human dependency policy; git for candidate/delivery identity; one local transactional execution store for jobs, attempts, reservations, waits, receipts, and pending external effects. Logs and dashboards are projections. Artifacts are immutable content addressed files. Delegate owns provider routing and worker facts, not job disposition. Cross-authority effects still require an outbox and reconciliation; a local transaction cannot atomically commit a remote push.

The target transition interface is the four-line interface in I.F07, extended by `commit(expected_revision, transition, pending_effects) -> revision`. Implement it behind the existing stores, first importing legacy state under quiescence, then switching one job writer at a time, then removing legacy reads as authority. Do not leave two authoritative write paths operating indefinitely. The proof is a kill test at every import and external-effect boundary: one current attempt, durable unsatisfied effects, no authorization inferred from an absent projection. This is part of I.F07/I.F08's migration, not an independent giant database rewrite prerequisite.

## Plan reuse: keep the optimization, refuse the permission shortcut

**Keep** continuing accepted work rather than purchasing a new plan on every invocation. `src/taskloop/app/run/decide.py:106`–119 and `src/taskloop/app/run/resume.py:120`–137 implement that useful behavior. **Refuse-and-redo** “usable plan” as an execution permission: `decide.py:60`–66 uses plan/branch and head relationships, and its World at lines 20–40 carries no admitted execution-bundle identity. A.F05/D.F10 own the configuration-revision gap; this review's answer is I.F01's immutable job, not another missing-hash finding.

A plan is a proposal tied to scope and policy revisions. Accepted-stage receipts belong to candidate content. Reuse planning when those inputs remain applicable; invalidate checks/reviews whose actual inputs changed. A changed requirement creates a new job revision with an explicit acceptance delta. A changed base requires affected validation, not automatic rediscovery of the whole task. “Run again” must name the changed capability, owner decision, or permitted transient retry from I.F03/I.F07. Reuse that merely saves tokens while silently carrying stale permission fails the owner's safety requirement.

## Judgment ledger for inspected material

| Material inspected | Judgment | Reason / disposition |
| --- | --- | --- |
| README workflow, slots, dashboard descriptions | Refuse-and-redo | Next-stage and whole-task meanings coexist; review and read-only language exceed the guarantees (I.F04/I.F08/I.F10; A.F09). |
| A and D reviews | Keep as defect records; refuse-and-redo as the complete product prescription | Their concrete evidence is useful; patching every join leaves unnecessary hop and workflow products alive. Some cited source has since changed, as noted above. |
| Config schema and loader | Keep strict parse refusal; refuse-and-redo unversioned policy and sprawling retry knobs | I.F01/I.F03; strict failure is necessary, not a reason to auto-upgrade a running job. |
| Plan, cap, resume, decision, stage/check/review loops | Keep recovery and bounds; refuse-and-redo orchestration policy | I.F02–I.F04/I.F08: recovery is useful, repeated planning and lexical acceptance are not proof. |
| Reload and per-call delegate selection | Refuse-and-redo | I.F01: delete mid-job replacement. |
| Writer split, worker request, family pin, supplied delegate routing/parser | Keep capability refusal; refuse-and-redo economic/capability coupling | I.F05; compatibility of the installed pair is untested. |
| Parks, leases, loop settlement/verdict, queue | Keep NOOP/umbrella and typed slot guards; refuse-and-redo ownership/wake vocabulary | I.F06/I.F07/I.F09. |
| Store bundle, checkpoint, paths, standalone stage lifecycle | Keep artifacts and durable obligations; refuse-and-redo multiple transition authorities | Storage section and I.F08. File count alone is not the verdict. |
| Board columns/needs and operator model draft | Keep navigation/inbox; refuse-and-redo proof-by-column | I.F10. `docs/design/dashboard/dash-operator-model.md:2` says the draft is not an owner decision; its proposed lifecycle is untested. |
| Historical stage study | Untested for current performance; refuse-and-redo its blanket empty-plan recommendation | `docs/design/stages.md:164` and line 192 favor closure that incident 6 discredited. Its old monolithic line references are not current evidence. |
| Review-switch and Board tests | Refuse-and-redo the assertions identified in I.F02/I.F10; execution untested | They preserve the unwanted product semantics, rather than demonstrating the owner's reviewed-delivery contract. |
| Other test paths located during inspection | Untested | Locating a test is not reading its assertion or running it. No coverage or pass claim is made. |

## Smallest factory and migration order

The minimum record is `Job(id, source_revision, acceptance, profile, bundle, target, budget)`. It has attempts, each with one fenced workspace reservation; immutable candidates; checks and reviews attached to candidate identities; one typed wait; and delivery/settlement receipts. Completion means the required delivery and external effects are acknowledged. An attempt ending is not job completion. Bd status remains a projection of that completion, reconciled through durable effects.

The minimum workflow is:

```text
bead revision -> admission -> immutable job -> workspace reservation
 -> plan -> write/cheap checks -> candidate -> required checks
 -> independent review -> bounded targeted repair -> delivery permit
 -> land -> settle durable effects -> complete
                     failure -> typed wait -> changed input -> next attempt
```

Rebase or repair changes the candidate and invalidates evidence according to its inputs. Persistent workspace reuse remains; destructive maintenance requires the reservation capability even if the tree is clean. A.F02/D.F04 own today's cleanup violations. The point here is to make workspace destruction unavailable to generic branch cleanup by construction, not to add another label check.

1. **Make promises honest.** Remove word-based review bypass and false Board pass indicators. Give step success a distinct result. These are small releasable changes that immediately reduce false confidence.
2. **Freeze admitted work.** Record bundle/profile/source identities, retain their artifacts, disable mid-job hops, and apply updates only before admission. Preserve current checkpoint recovery while draining old runs.
3. **Normalize the job transition.** Add revisions, reservations, typed waits, completion receipts, and a durable effect ledger behind current adapters. Move queue and dashboard eligibility onto that projection. Import legacy jobs while writers are quiescent; unknown state becomes a visible owner wait.
4. **Collapse coordinators.** Drive run-task, one-transition operation, and loop through that transition interface. Remove arbitrary stage selection after compatibility clients drain; adapt stack delivery to the same permit.
5. **Cut purchased ceremony.** Merge retry allowances, add diagnosis/progress requirements, and default to one independent final review. Keep early review only for declared risks; compare delivery cost and escaped defects before removing optional policies.
6. **Separate jobs from equipment.** Add executable-job admission and scope circuits; migrate slot inventory out of bd. Keep persistent setup and resource leases. Make external waits release workspace capacity safely.

The incident scorecard is deliberately about construction: slot deletion requires a reservation capability (incident 1); no live hop means no hop/PID admission fiction (2); versioned admission rejects unsupported profiles before claims (3); structured capability failure survives routing (4); follow-ups remain settlement obligations with repository validation (5; D.F08/D.F09); aggregates never enter delivery (6); every wait has a wake (7); shared failures open shared circuits (8); admitted bundles survive installation changes (9); profile snapshots survive main fast-forwards (10). These are proposed acceptance properties, **untested**, not assertions that this document has fixed the code.

## Top 10

| Rank | Priority | Judgment | Change |
| --- | --- | --- | --- |
| 1 | P1 | Refuse-and-redo I.F02 | Delete lexical acceptance certification and require honest final-review authorization. |
| 2 | P1 | Refuse-and-redo I.F01 | Delete mid-job engine/delegate replacement; freeze the admitted bundle and profile. |
| 3 | P2 | Refuse-and-redo I.F08 | One coordinator and one completion meaning across automatic and single-transition execution. |
| 4 | P2 | Refuse-and-redo I.F07 | One reservation and one typed wait; merge competing lifecycle authorities. |
| 5 | P2 | Refuse-and-redo I.F03 | Replace exhaustion-driven replans with cause-specific, progress-gated repair. |
| 6 | P2 | Refuse-and-redo I.F10 | Show receipts and unknowns; stop presenting visited/closed as validated. |
| 7 | P2 | Refuse-and-redo I.F06 | Compile executable delivery jobs from beads; separate equipment and aggregates. |
| 8 | P2 | Refuse-and-redo I.F09 | Scope infrastructure circuits and stop twelve-hour timer-based equipment diagnosis. |
| 9 | P2 | Refuse-and-redo I.F05 | Separate expensive-check scheduling from worker command capabilities. |
| 10 | P2 | Refuse-and-redo I.F04 | Review final candidates by explicit independence policy; justify intermediate reviews with measured value. |

## Beads to file

Proposed titles and acceptance intent only; no tracker commands or issue creation were authorized in this review.

- **Replace lexical review bypass with candidate-bound authorization** — Contradictory criteria and arbitrary green commands cannot satisfy required review; cover I.F02's negative tests.
- **Pin the admitted execution bundle and profile until job settlement** — Installing a plugin or moving main affects only later jobs; remove safe-point exec and per-call router switching.
- **Unify continuous and single-transition job execution** — Restarted step execution and continuous execution produce identical obligations and completion receipts.
- **Introduce revisioned job waits and workspace reservations** — Replace independently writable hold/park/pause policies; reject waits without wakes and effects without current authority.
- **Require changed inputs or diagnosed progress before another repair** — One durable job spending ledger survives retries; identical failures cannot buy fresh planning rounds.
- **Make Board status evidence-based** — Closed and visited phases do not imply validation; every circuit/wait stays visible without a live loop.
- **Admit delivery contracts before allocating workspaces** — Distinguish delivery, aggregate, research, and decision beads; migrate equipment inventory out of issue state.
- **Replace blanket slot set-aside with scoped fault circuits** — Shared setup failures stop shared admission; workspace faults require workspace-specific repair evidence.
- **Separate check requests from worker capability policy** — Duration and family pins cannot weaken hard restrictions or accidentally eliminate eligible writers.
- **Bind independent review to final candidates and measure early-review value** — Enforce declared independence and compare delivery cost/escaped defects before retaining per-stage ceremony.
