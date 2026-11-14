# Header
Task: tl-8bh9.14.167.2
Base: e752ae5d6944787089e270cceaa50faf7207d55e
Depth: medium; two behaviours.
Decisions settled; no explicitly unlanded dependency.
Evidence budget: 12 calls.
Size: 17 changed files incl. tests/plan; 2 behaviours; 75 implement calls.

## Outcome and non-goals
Record idle/active clock discrepancies and deliver one timeout comment despite lost acknowledgement. Preserve allowance/capture. Exclude dashboard durations, keep-awake, deadline/schema redesign and new channels.

## Settled decisions
- Supplied owner decision: harness timeouts use monotonic time; keep-awake is unnecessary.
- Attempts and test_attempt_runtime already deliver runtime allowance and timeout capture.
- Idle describes a rounds wait; active describes agent execution, not host-wide activity.
- Discrepancy is diagnostic evidence, not proof of sleep or a timeout/hold cause.
- Reuse task_hold intent/lease/result; reconcile external success before retrying.
- Emit when absolute wall-delta minus monotonic-delta exceeds one second, in either direction.
- Retain hold/saved-work context; describe runtime exhaustion without epoch deadline or CLI instructions.

## Open decisions
- None.

## Change map
- `src/taskloop/clock_jump.py` (new): observer, enums, evidence model/codec; used by Attempts, CommandSink and rounds.
- `src/taskloop/attempt.py`: Attempts._start/_call observe handoff/run boundaries, including exceptions.
- `src/taskloop/command_sink.py`: CommandSink.feed/poll/end sample an optional observer.
- `src/taskloop/evidence_files.py`: EvidenceFiles owns capped clock artifact append/read.
- `src/taskloop/rounds.py`: _pause observes waits; _Log emits idle evidence.
- `src/taskloop/round_log.py`: format clock records within existing grammar.
- `src/taskloop/recovery/native.py`: _run observes continued execution using app clocks.
- `src/taskloop/hold.py`: _comment passes timeout identity and records reconciled success.
- `src/taskloop/hold_cause.py`: cause describes runtime exhaustion.
- `src/taskloop/tracker_client.py`: Comment/tracker_holds.comment reconcile identity before posting.
- `tests/steps/test_clock_jump.py` (new): observer/codec behaviour.
- `tests/steps/test_attempt_runtime.py`: active evidence with existing allowance fixtures.
- `tests/steps/test_rounds.py`: Bench separates clocks; idle evidence/scheduling.
- `tests/steps/test_hold.py`: Bench tests wording, repeated/concurrent holds and restart.
- `tests/steps/test_tracker_holds.py`: identity, structured reads, actor checks, failures.
- `tests/steps/test_clock_jump_files.py` (new): EvidenceFiles caps and write-failure isolation.
- `docs/design/tl-8bh9.14.167.2/plan.md`: contract.
- Consult `src/taskloop/composition.py`: Attempts caller; also test_attempt.AttemptSurroundings.
- Consult `src/taskloop/cli_composition.py`: RoundsPorts caller; also test_rounds.Bench.
- Consult `src/taskloop/round.py`: _held calls hold_task; also test_hold.Bench.move.
- Consult `src/taskloop/merge/resolve.py`: WatchedHooks/CommandSink caller; preserve optional observer compatibility. Other callers: attempt._call and recovery.native._run above.
- Consult `src/taskloop/hold_status.py`: cause produces timeout hold eligibility.
- Consult `src/taskloop/hold_text.py`: comment/_answer retain evidence and consume cause.
- Consult `src/taskloop/hold_guide.py`: render consumes cause.
- Consult `src/taskloop/hold_store.py`: intent/lease/result owner.
- Consult `src/taskloop/tracker.py`: task_comments structured reader.

## Read list
- `src/taskloop/attempt.py:149-275` — allowance and hooks.
- `src/taskloop/command_sink.py:1-65` — live callbacks and failure isolation.
- `src/taskloop/evidence_files.py:113-180` — artifact ownership.
- `src/taskloop/rounds.py:32-85` — injected ports and log failure reporting.
- `src/taskloop/rounds.py:110-176` — round loop, pause and stop boundaries.
- `src/taskloop/round_log.py:1-35` — existing evidence word grammar.
- `src/taskloop/recovery/native.py:40-82` — continued execution hook producer.
- `src/taskloop/merge/resolve.py:54-78` — other live-sink caller; optional argument compatibility.
- `src/taskloop/hold.py:180-230` — abandonment, leased comment effect and result.
- `src/taskloop/hold_cause.py:133-145` — timeout wording shared by comment/guide.
- `src/taskloop/hold_text.py:165-211` — explanation and comment assembly.
- `src/taskloop/hold_guide.py:68-83` — shared cause consumer.
- `src/taskloop/hold_status.py:40-66` — timeout hold eligibility producer.
- `src/taskloop/hold_store.py:1-95` — durable intent and lease semantics.
- `src/taskloop/tracker_client.py:230-325` — Comment port and external writes.
- `src/taskloop/tracker.py:134-158` — structured comments.
- `src/taskloop/composition.py:113-132` — production Attempts clocks.
- `src/taskloop/cli_composition.py:287-302` — production rounds clocks/log port.
- `src/taskloop/round.py:294-310` — hold caller.
- `tests/steps/test_attempt.py:72-92` — semantic Attempts construction.
- `tests/steps/test_attempt_runtime.py:1-125` — allowance/timeout contracts.
- `tests/steps/test_rounds.py:24-90` — scheduling clock fixture and log expectations.
- `tests/steps/test_hold.py:95-132` — semantic hold fixture and effect wiring.
- `tests/steps/test_tracker_holds.py:1-80` — scripted adapter fixture.

## Contract
Clock evidence: observation intent has no control effect. Above threshold emit context/direction enums, both paired samples and signed discrepancy through one pydantic v2 edge codec. Reset baseline after each sample and restart. Idle records use rounds.log; active records use a capped attempt artifact with an owning reader. Write failures follow existing diagnostic handling and cannot affect execution, capture or scheduling. No database fields change.

Notification: Comment gains optional typed timeout attempt identity; other requests retain their semantics. Adapter encodes/validates a structured metadata trailer and checks only factory-authored comments, never prose or timestamps. Under the existing lease: matching task/attempt identity means success; absent means post; failed read means unavailable without posting. External calls stay outside write transactions. Ambiguous success leaves pending intent; restart before commented_at reads/adopts the posted comment. Existing lease and bounded calls fence concurrent writers. Distinct attempts have distinct identities; task_hold remains state owner.

Only captured genuine runtime timeout facts select timeout identity; jumps, admission expiry, lost entries and non-timeout stops cannot synthesize it. Preserve current hold eligibility and retained-work context. Timeout wording states the situation and held decision.

## Work packages
1. Clock observer/files, Attempts/CommandSink/native/rounds integration and observer/artifact/runtime/wait tests close acceptance 1-3.
2. Comment request, hold._comment, tracker reconciliation, cause wording and hold/adapter crash tests close acceptance 4-6.
3. Use focused isolated tests during implementation. Last run `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40` once each; no live tests.

## Acceptance behaviours
1. Forward/backward discrepancies emit the observing path's idle/active context; subthreshold drift emits none.
2. Handoff, quiet polling, return and continuation preserve active evidence without extra runtime consumption or false timeout.
3. Idle jumps preserve wake/stop scheduling; evidence failure cannot alter execution/capture or become control state.
4. Genuine timeout produces an owner-visible hold comment describing runtime exhaustion/held decision, retaining evidence/saved work, without CLI instructions.
5. Repeated/concurrent rounds, failed reads and restart after ambiguous posting yield one notice per attempt; absent notices retry until delivered.
6. Another timed-out attempt gets its own notice; jumps, admission expiry and non-timeout stops produce no timeout notice.
