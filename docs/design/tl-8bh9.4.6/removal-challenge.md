# Removing adapters: behavior counterfactuals

Owner sharpened the review on 2026-11-09: what if the behavior disappears, what breaks, is that loss acceptable,
and what simpler system remains? Astra challenged all 38 modules against the frozen baseline source. This is
source reasoning, not a production incident or a claim that the successor already supplies the guarantees.

Deleting a wrapper, deleting its feature and preserving its invariant through a simpler owner are different choices.
An existing caller is evidence of use, not a reason to retain behavior. Moving code to shelf is not a justification.
The [original audit](plan.md) supplies purpose/cost/callers; this supplement supplies the removal consequences.

| Baseline adapter | What is lost if behavior disappears | Decision / minimal retained behavior |
|---|---|---|
| `__init__.py` | No behavior is lost. | Packaging only; no extracted utility. |
| `agent.py` | Execution handle, live progress and surviving-worker discovery disappear; unsafe reuse becomes possible. | Remove implementation, retain truthful execution/liveness in shared agent owner; test survivor plus query failure. |
| `delegate.py` | Agent calls, model/account controls, continuation and normalized failure information disappear. | Retain required execution contract directly; separately question account-management UI and network pre-probes. No temp-file/argv/JSON in-process transport. |
| `delegate_wire.py` | Malformed result and stop/usage distinctions can reach workflow unchecked. | Shared agent contract validates them; delete duplicate coercion, including unknown worker end becoming ok. |
| `runner.py` | Outer cancellation, bounded execution and survivor reporting disappear. | Keep guarantees in shared agent lifecycle; delete polling and synthetic subprocess wrapper. |
| `spawner.py` | Repository commands and external tools no longer execute, or timeout cleanup is lost. | Keep only necessary external execution through owning library; remove self-CLI calls for native operations. |
| `procs.py` | Capture/stream/output/process-tree cleanup disappears. | Shared process API owns required behavior; not every old launch is worth retaining. |
| `pidcheck.py` | PID reuse may be mistaken for original-holder liveness. | Keep identity-aware liveness where required in process owner; avoid competing probes for agent workers. |
| `threadflag.py` | Naively shared flags mix timeout/success across concurrent commands. | Delete ambient flags; typed per-invocation result preserves isolation. |
| `halt.py` | Shutdown may abandon workers or interrupt state transitions. | Keep scoped internal cancellation and safe boundaries; delete duplicate global signal plumbing. |
| `deadline.py` | Commands, nested retries or waits can exceed the admitted budget. | Keep explicit per-execution remaining time; remove process-global budget list. |
| `locks.py` | All-exclusion removal permits competing writers; deleting holder hints only loses diagnostics. | Separate correctness-critical reservation/critical sections from optional display sidecars; test two threads as well as processes. |
| `landlock.py` | Same-host delivery contenders may race/retry more; no distributed exclusion is lost because none existed. | Keep custody and safe conditional delivery; justify local serialization separately. Arbitrary-command launcher is not required. |
| `ram.py` | Admission no longer waits below configured available RAM (default 1024 MB). | My recommendation: omit the proactive RAM threshold initially; accept loss of automatic low-memory throttling and use bounded slots plus actual failure evidence. Memory-pressure failures remain a real risk. Proposed, not approved. |
| `factory.py` | Detached loops can sleep with an idle Mac, delaying unattended work. | My recommendation: retain keep-awake while the factory runs, including timed waits, so unattended work can resume. A small OS helper has a concrete purpose; no new framework/native binding solely for this. Proposed, not approved. |
| `git.py` | Checkout/ref/commit/worktree/delivery behavior disappears. | Shared Git owner supplies only required operations. Do not carry automatic cleanup/reset/commit-all solely because callers exist. |
| `git_base.py` | Checkout pinning, failure-versus-absence and fsmonitor policy can disappear. | Retain justified semantics in Git owner; remove duplicate runner/classifier. |
| `git_ops.py` | Diff/index/delivery observations disappear; deleting history rewriting also removes rebase/amend/lease-force workflows. | Keep required observation/conditional delivery; rejected task-history rewriting is deliberately lost. |
| `git_pool.py` | Library errors may lose domain distinctions/full diagnostics. | Consume shared typed failures; retain only necessary factory interpretation, not generic reclassification. |
| `gitrepo.py` | Repository and checkout topology can bind work to the wrong place. | Shared Git API owns topology and pinning; no handwritten factory .git readers. |
| `gitmemo.py` | Repeated Git observations may cost more; fresh reads do not inherently lose correctness. | Settled direction: remove cache AND redundant caller queries. Pass operation inputs/results; fresh reads only at boundaries requiring current state. No relocation of the memo layer. |
| `ignored.py` | Custom dirty-path suppression and factory-selected commit filtering disappear. | Challenge auto-staging policy itself. Agent resolves committed-step edits; shared ignore query only for a real retained consumer, with explicit failure. |
| `slotcheck.py` | Worker/check Git may target a different checkout even if factory Git is pinned. | Retain actual checkout/custody invariant; preparation suffices only if later operations stay bound. Delete redundant probes/policy, not protection. |
| `ident.py` | Configuration placement and actor/session attribution become ambiguous. | Minimal explicit roots and execution identity at composition; delete historical fallbacks/layout gates. |
| `land_probe.py` | No current default protection is lost (GUARD_MAIN is false); future hook convenience is lost. | Exclude disabled feature; a lock observation never authorizes a push. |
| `check_probe.py` | Early missing-command/recipe/path/order diagnostics disappear, along with base-check probes and planner rewrite overhead. | Accept loss with retired planner DSL; actual commands fail truthfully and semantic task acceptance remains reviewed. |
| `check_net.py` | An enabled restriction disappears and checks may access external network. | Proposed product cut requiring explicit choice. Default-off is not deletion approval; if retained choose unsupported-host behavior. |
| `links.py` | Automatic host-side URL reachability/filtering is lost. | Accepted feature removal. Repo/task-specific link validation can still be requested; no replacement service. |
| `bd.py` | Task admission/context/claims/mutation/settlement disappear. | Thin replaceable task-tracker adapter; preserve typed failure/uncertainty and actual conditional semantics. |
| `beadtools.py` | Construction/PATH/error-rendering convenience disappears. | Use composition/CLI directly; deleting failure-as-empty helpers improves truthfulness. |
| `bdbackup.py` | Existing daily exports are lost before maintenance protection is verified. | Tracker-maintenance ownership agreed; preserve exports until real coverage/recovery is verified. Count check is not restore proof. |
| `closes.py` | Blind deletion resets failure streaks/deduplication and may permit more retries. | Replace accepted retry accounting with actual DB attempts, then delete log-derived control; rotation cannot reset policy. |
| `factorybackup.py` | Recovery of local execution state from old snapshots is lost. | Accepted tradeoff: deliberate DB discard repeats ordinary steps; intact DB still resumes unfinished work. |
| `layout_paths.py` | Migration journal/retired-path naming disappears. | Accepted compatibility removal; no independent capability. |
| `layout_migrate.py` | Old-layout conversion/detection and command gating disappear. | Accepted compatibility removal. Startup must not move/delete prior user work or evidence. |
| `key_migrate.py` | Historical-key discovery/rekey/retirement disappears. | Accepted compatibility removal; current identity has one owner. |
| `looks.py` | Screenshot conversion/copy for old visual review disappears. | Accepted visual-only workflow removal; no invented generic artifact consumer. |
| `markers.py` | Textual markers in otherwise merged files can escape this extra scan; unmerged-index checks do not replace it. | Delete script/process hop. Prefer repo-owned marker policy if needed; retain unresolved Git-conflict refusal and distinguish scan failure if scan remains. |

## Changes to the earlier recommendations

1. Checkout correctness is stronger than pinning factory Git. `RunParts.assert_tree` requests unpinned/ambient
   Git; workers/checks may resolve a different checkout. A preparation-only assertion is sufficient only if later
   execution remains bound to that checkout. Keep this invariant before removing the eleven-probe implementation.
2. RAM and idle prevention are real unattended-operation behavior, not incidental adapters. Their removal needs
   an explicit product choice; do not automatically extract a host-observation framework or native power binding.
3. Remote-keyed land locks serialize local contenders. They never fenced remote writers. Correct expected-head/
   non-force publication and shared-checkout custody remain required even if optional local serialization is cut.
4. Git memoization is an observation cache, not an operation snapshot. Its fixed config-file list misses included
   configuration dependencies (source inference, not a reproduced incident). Removing it favors fresh observation;
   replacing all live reads with an old admitted snapshot would be wrong too.
5. Marker scanning, dirty-path suppression, account-management UI and network pre-probing each need a concrete
   retained purpose. They do not all become new shelf APIs merely because they exist in the baseline.

## Source traces for controversial cuts

- Ambient checkout: `app/run/parts_run.py:106` -> `adapters/slotcheck.py:37`; check actual worker/check environment.
- Planner convenience and duplicate work: `parts_run.py:115` -> `tlwork/plan/probe.py:37` and `tlgate/domain/lint.py:90`.
- Mutable config cache: `adapters/gitmemo.py:19`; fixed signatures do not enumerate include/includeIf targets.
- Host policy: `app/loop/waits.py:8` consumes RAM; `app/loop/factory_verbs.py:164` attaches keep-awake to loops.
- Lock scope: `tlland/lander.py:120` and `tlrelease/push.py:19`; remote advancement still needs independent handling.
- Routing policy: `app/workers/account_acts.py:90` and `app/loop/settle.py:89` use network/offline facts. Remove
  pre-probing only with a clear policy for actual typed provider failures, not blind launches or unlimited retries.

These paths name baseline code retained at commit `731b7c76ef214ce35229f77814f98b6e1d6d5c0f` and in the original
review worktree. The source foundation introduces none of these mechanisms. Concrete implementation tasks retain
invariants; Git memo retirement/query consolidation is now settled direction. Unresolved host/network/delivery convenience cuts stay proposed until selected. Do not turn this
analysis into a new runtime monitoring system or file one task per adapter.


## How recommendations are presented

Owner clarification, 2026-11-09: prepare an engineering judgment before asking for approval. For each proposed
behavior cut, state the user-visible loss, whether I judge that loss acceptable, the concrete reason/risk and the
simpler retained behavior. Ask for a product choice only after that recommendation is concrete. Do not reopen
already accepted cuts. "There are callers" and "we can move it to shelf" are not recommendations.

For Git memoization the chosen strategy removes unnecessary observations, rather than accepting extra Git
processes as the inevitable cost of deletion. See ../tl-8bh9.9/plan.md for the exact operation-data-flow contract.
