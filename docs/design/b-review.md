# B-REVIEW: the review stage without the engine (tl-e5t0.33)

Design and slicing only; no code moves with this note. Follows `stage-isolation.md` (sections 1.1 and 7), `facts.md` (the `RunFacts` and ports shape), `attr-map.md` and `engine-order.md`, and takes `b-look.md` as its pattern. Checkpoint on disk unchanged. Measured on origin/main, 2026-11-06, by an AST scan of `packages/work/src/tlwork/review` (attribute reads off the host) and a grep of every writer; nothing was run.

## What the stage is today

`app/review` is four parts, 604 lines, all built by the engine with itself (`app/run/parts_plan.py`), all but one taking `host: Any`:

| part | file (lines) | takes | distinct engine members it reads | what it does |
|---|---|---|---|---|
| `Routing` | `routing.py` (140) | `Any`, `git` | 10 | the ledger of unchecked items, where an item goes (a fix, a follow-up, the owner), engine-side proof steps |
| `Settles` | `settles.py` (194) | `Any`, `git` | 12 | what the engine proves itself before it asks anyone: tool unused, work summary, evidence text |
| `LinkCheck` | `link_check.py` (70) | `Any` | 8 | opens the links a review cites, once per run |
| `Verifier` | `verifier.py` (200) | `Any` | 27 | one read-only verifier call before a verify ask; settles, defers, or hands a wrong item to one fix round |

The review *round* (the prompt, the reply, the follow-ups) is not here: it is `app/write/review_round.py` and moves with B-WRITE. Callers of this stage from outside: `e.verifier.run` (`run/stages.py:276`, `run/run_once.py:108`), `e.routing.ledger` (plan x2, write x3), `e.link_check.link_judged` (`write/review_round.py:163`). That is the stage's whole public surface: three entry points.

## The 41 members the four parts read, classified

By reads and writers, not by which directory mentions a name (stage-isolation section 7, point 5).

| class | members | goes to |
|---|---|---|
| **owned state, checkpointed** | `unchecked`, `unverified` (read here; two of the four lists `RunState.review` carries, with `filed`, `unfiled`) | `ReviewState` stays the one record; the stage owns the live object (see Target) |
| **owned state, not checkpointed** | `verified` (verifier, settles, routing append; read by the trace and the bead text), `link_ok`, `link_bad`, `link_tries` (link_check only), `link_fn` (a test hook; a constructor argument instead) | `ReviewLive` (below) |
| **run facts** | `bead`, `cfg`, `wt`, `run_dir`, `evidence_dir`, `scope` (the bead's acceptance text; written once by `run_once`/`stages`, read here) | `RunFacts`; `scope` is a call argument of `Verifier.run` (it is an input of the call, not a fact of the run) |
| **ports the shell holds** | `log`, `warn`, `steps` (begin/outcome/move, 11 uses), `budget.labels`, `stores` (`check_run`), `checkpoints` (`keep_pending`), `comment` | `Narrate`, `StepBook`, `BudgetView`, `Stores`, `CheckpointsPort`, `BeadComment` |
| **one worker call** | `ai`, `at_stage`, `last_flag`, `writer_family`, `Blocked`, `blocked_for` | `AskAi` returning a typed result (stage-isolation point 6); `at_stage` is an argument, `last_flag` and `writer_family` come back in the result and the caller records them |
| **other stages' parts and hand-offs** | `checkout` (tree_hash, task_diff, changed_paths, base_sha), `diff_text`, `on_path`, `sh` (land/run); `cases.case_checks`, `briefs.text`, `briefing.where`, `plan_data` (plan, write); `judge.is_look`, `look_verify`, `look_verdict` (look); `fixer.fix` (land); `leftovers`, `fixes`, `last_run` (hand-offs; `last_run` is the check run the settles read: an argument) | one small port each, defined by this stage (below) |
| **review's own parts** | `settles`, `routing`, `verifier`, `link_check` read each other | stay inside the stage as constructor arguments |

So the stage is four parts and seven fields of its own, and what it needs from outside fits in nine ports. The engine does not need to be a type any review code can see.

## Target

**State.** `app/review/state.py`:

- `ReviewLive`: a plain dataclass of the non-checkpointed fields (`verified`, `link_ok`, `link_bad`, `link_tries`). The engine holds one (`engine.review_live`); `LinkCheck`, `Settles`, `Routing` and `Verifier` get it by constructor.
- the checkpointed lists: `ReviewState` (`contracts/review.py`) stays the record. Today the engine holds `unchecked` and `unverified` as plain lists and `run/review_glue.py` (`review_of`, `apply_review`) converts at the two seams. Review does not own these lists alone: `write/review_round.py` (3 writers), `run/stages.py`, `run/resume.py`, `land/record.py` and `run/review_glue.py` also write `unchecked`; `land/record.py` and `run/review_glue.py` write `unverified`. They are shared between review, write and the shell, so the first slice does **not** move them off the engine; it gives them one owner object (`ReviewItems`, two lists with the `Open`-dict shape they have now) so a later stage can take them through a port without a cycle. See decision 1.

**Entry.** Constructor injection, in the order ENGINE-ORDER fixed (layer 4: `verifier` last; `settles` and `routing` layer 1-3): `Routing(facts, ports, live)`, `Settles(facts, ports, live, routing_ports)`, `LinkCheck(facts, ports, live, link_fn)`, `Verifier(facts, ports, live, items, settles, routing, link)`. No `Any` host survives; `Blocked` becomes the typed result of `AskAi`.

**Ports** (this stage declares them in `app/review/ports.py`; no more than eight, none with more than six methods):

| port | methods the stage calls | provider |
|---|---|---|
| `Narrate` (kernel, FACTS) | `note`, `warn` | `RunLog` |
| `StepBook` (kernel, FACTS) | `begin`, `outcome`, `move` | `Steps` |
| `AskAi` (ASKAI) | `call(node, prompt, ...) -> AiAnswer \| AiRefusal` | the worker call |
| `TreeView` | `tree_hash`, `task_diff`, `changed_paths`, `base_sha`, `on_path(path)` | `Checkout` (land) |
| `CaseBook` | `case_checks`, `plan_cases`, `is_look` | plan and look, folded into one read-only view |
| `FixRound` | `fix(items) -> FixResult` | land's `Fixer`; the verifier hands one wrong item batch to a fix round at land |
| `LedgerSink` | `add_leftover(item)`, `add_fix(item)` | the shell: today `leftovers` and `fixes` are lists several stages append to; the sink makes the hand-off visible |
| `BriefView` | `text()`, `where(stage)` | plan's `Briefs` and write's `Briefing` |

Not ports: `stores.check_run` is one verb of the kernel `Stores`; `checkpoints.keep_pending` is `CheckpointsPort`'s; `comment` is `BeadComment`; `budget.labels` is a value passed in the call. Those come from `RunPorts` (FACTS) unchanged. `sh` goes to `Settles` only and is a `Spawner`-level `Shell` verb (`RunPorts` already holds `spawner`).

**Hand-offs out.** What `Verifier.run` returns today is the list of items for the owner, and it appends to `engine.unverified`, `engine.leftovers`, `engine.fixes` on the way. After: `run(gaps, scope) -> VerifyResult(owner_items, wrong, verified, leftovers)`; the pipeline appends them. That makes the three engine lists written by the shell alone, which is the one condition the amend-family note in `attr-map.md` asks of a hand-off.

## Slices (each a PR that passes `just test` alone; behaviour unchanged)

1. **ReviewLive and ReviewItems.** Add the dataclasses; `LinkCheck`, `Settles`, `Routing`, `Verifier` read `self.live` instead of `engine.link_*` / `engine.verified`; `run/fields.py` builds one `ReviewLive`; `link_fn` becomes a constructor argument (the tests that set `engine.link_fn` pass it). Engine attribute count drops by 5. No checkpoint seam moves: `review_of`/`apply_review` read the same lists.
2. **Hand-offs as a return value.** `Verifier.run` returns `VerifyResult`; `run/stages.py:276` and `run/run_once.py:108` append `leftovers`, `fixes`, `unverified` from it. `tests/review` assert on the result, not on engine lists.
3. **Ports.** `app/review/ports.py`; `TreeView`, `CaseBook`, `FixRound`, `LedgerSink`, `BriefView` get one adapter each on the Engine (structural, no class changes) and a fake in `tests/review/testing.py`; the four parts take `facts` and the ports instead of the host; `FakeReviewPorts` replaces the engine in `tests/review`. Depends on FACTS slices 1-2 (`RunFacts`, `Narrate`, `StepBook`) and ASKAI slice 3 (`AskAi`).
4. **Conformance and report.** One conformance test per new port runs the Engine adapter and the fake through the same probes; a mutation of the fake (drop a verb, return a different diff) fails it, as in #285. Record the stage's forward import closure and the engine attribute count before and after in `architecture-vertical.md`; T-BUDGET ratchets it.

Slice 1 touches `run/fields.py`, which B-LOOK slice 1 and FACTS slice 2 also edit (a few lines each); whoever lands second rebases. Slice 3 waits for FACTS and ASKAI; slices 1-2 do not.

## Tests

`tests/review` holds 1,095 lines in 11 files, and `tests/review/test_follow_ups.py` builds an `Any` engine (`eng: Any`). After slice 3 each file builds its part from `FakeReviewPorts` and `fake_facts` and imports nothing of `app/run`; `just test-pkg review` is the developer shortcut (a tool, not a gate: `just test` stays the only gate).

## Owner decisions, with a recommendation

1. **Who owns `unchecked` and `unverified`?** They are written by review, write, land (restart) and the shell (resume, stages). Recommend: review owns the *type* (`ReviewItems`) and the engine keeps the one instance until B-WRITE and B-LAND have moved their writes behind `LedgerSink`-style ports; do not split ownership in slice 1.
2. **`VerifyResult` instead of appending to engine lists (slice 2).** Recommend yes: it is the only way the pipeline, and not four stages, owns `leftovers`, `fixes` and `unverified`.
3. **`CaseBook` folding plan and look into one read-only view.** Recommend yes: review reads three look verbs and two plan verbs that are all "what the cases say"; two ports for one read would double the fakes.
4. **Is `review_round.py` in this bead?** Recommend no (B-WRITE); this bead is `app/review` only, as the bead's own text says (4 of 5 files take an `Any` host; the fifth is `__init__.py`).

## Not verified

The member counts are from an AST scan of the four files and a grep of writers, not from running anything. The scan sees reads off `e`/`host`/`self.e` only; a part reached through a local alias or `getattr` is not counted. Whether `RunState.review` is the only checkpoint record that carries review state was read from `run/review_glue.py`, not from `contracts/checkpoint.py` in full. The method lists of the ports are the verbs the four files call today; a method another caller needs later is a port change, made in that stage's PR.

## Slice 1 as built (tl-e5t0.33)

One object, `ReviewLive` (`app/review/state.py`), held as `engine.review`, carries `unchecked`, `unverified`, `verified`, `link_ok`, `link_bad`, `link_tries` and `link_fn` (the test hook stays an attribute, not a constructor argument: four tests set it). It is one type, not two as sketched above: the shared lists and the private ones live together, and decision 1 still holds (the engine keeps the one instance; `review_glue` converts at the two checkpoint seams, so the record on disk is unchanged). The look stage reads `unverified` through an `OwnerItems` Protocol in `look/host.py`, since the slice table forbids `look` importing `review`. `tests/support/builders.make_engine(attrs=...)` routes these names to `engine.review`; two older tests that set `unchecked` on the engine had been setting an attribute nothing read.

## Slice 2 as built (replaces VerifyResult)

`VerifyResult` as sketched would have changed behaviour: inside one `Verifier.run`, `defer()` appends a leftover and then `checkpoints.keep_pending` and `Routing.has_leftovers`/`ledger()` read it in the same pass, so deferring the appends to the pipeline changes what they see. The lead chose the sink (2026-11-07): the review parts no longer write the engine's lists themselves. `ReviewLive.add_verified(item, verdict, why, evidence)` and `ReviewLive.add_unverified(item, why)` carry the two writes of the stage's own state (five call sites become methods; the dedupe by text moves in), and `Routing.add_leftover(lo) -> bool` is the one place review adds a follow-up bead to the engine's leftovers (once per title). Timing is unchanged. Slice 3 turns `add_leftover` into the `LedgerSink` port. A stage that writes typed records needs the run-log port, not `Narrate` (pix-dash-3, 2026-11-07); the verifier writes none today.

## Slice 3 as built (a typed host first; constructor injection is slice 3b)

The four parts no longer take `host: Any`: they take `ReviewHost` (`app/review/host.py`), one Protocol of the 29 engine members the stage reads, composed of small Protocols named for the capability (`TreeView`, `CaseBook`, `BriefView`, `Briefing`, `LookView`, `FixRound`, `PendingKeeper`, `ReviewSteps`, `ReviewBudget`, `ReviewLog`, `ReviewStores`, and `SettlesView`/`RoutingView` for the stage's own parts that read each other). This is the look pattern (`LookHost`, #295): an inventory the type checker enforces, with `tests/review/test_review_host.py` proving the Engine has every member. `Blocked` gets a base in `contracts/stop.py` (`Stop`: `why`, `kind`) so the verifier catches a typed stop without importing the run slice. Constructor injection (`facts`, `ports`, `FakeReviewPorts` for the tests) is not in this PR: it moves each of the 29 reads to an argument and rewrites `tests/review`'s engine setup, and wants B-LOOK 3 and B-WRITE to settle which of the ports (`TreeView`, `CaseBook`, `FixRound`) are shared first. Two casts the typed host made redundant (`int(cfg.max_fix_rounds)`) are gone.
