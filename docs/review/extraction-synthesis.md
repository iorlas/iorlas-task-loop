# Extraction synthesis (phase 1, second pass at the "default EXTRACT" bar)

Five read-only Codex lenses, one document each: `extraction-stdlib.md` (A), `extraction-taskloop-substrate.md` (B1),
`extraction-delegate-dash.md` (B2), `extraction-duplication.md` (C), `extraction-shelf-reuse.md` (D). A sixth, cross-repo
(a2kay, homelab, a2peer), is still running. Every number below is the lens's own count, not re-measured by the author of this page;
the lenses overlap (the same git, JSONL, process and record code appears in several), so they are NOT added together.

## The honest number

The 50% target (about 71,800 of 143,632 counted lines: src, dashboard, tests, skills, dev of task-loop and delegate) is not reachable
by extraction. All five lenses say so independently, and none of them hid behind risk or refactor cost:

| Lens | Approved to move or delete | Share of its denominator |
|---|---:|---:|
| A stdlib / 3rd-party | 7,799 gross | 5.4% |
| B1 task-loop substrate | 18,646 incl. 8,129 vendor | 13.0% (7.3% without vendor) |
| B2 delegate + dashboard | 3,018 | 14.9% of its own scope, 2.1% globally |
| C duplication | 7,069 (+8,129 vendor conditional) | 4.9% |
| D shelf reuse | 7,149 (+8,129 vendor, +276) | 5.0% (10.8% with conditional) |

Deduplicated, the supported total is about **13%**: roughly **5-7%** is fresh generic code that moves or is deleted, and about
**5.7%** is the 8,129 lines of shelf packages the apps already carry as checked-in vendor copies (not new generic code, only a
distribution problem). What does not move is mostly app tests, contracts, goldens and fixtures that encode the factory's domain
(about 70k test lines), and the domain code itself (land/gate/close, lanes, slots, runs, routing): refused by naming the rule,
in each lens's "25 largest remaining files" table.

Consequence: the 50% target is not a plan, 13% is. The reachable gains come from a few big mechanisms, not from many small ones.

## Ranked, deduplicated phase-2 order (lines per risk, with dependencies)

| # | Package (shelf) | Lines out | Risk | Why now / dependency |
|---:|---|---:|---|---|
| 1 | **D0 vendor distribution** (replace checked-in shelf copies by hash-verified released artifacts) | 8,129 | 5 | Biggest single volume cut. Not new generic code. Needs a design first: PEP 723 `tl.py` can resolve tags, the plain-python3 PreToolUse hook cannot (no deps): keep stdlib-only vendoring for the hook or build a private self-contained artifact at release; prove clean/offline launch, hooks, reexec, rollback before deleting. Experiment, not a refactor. |
| 2 | **git-porcelain convergence** (task-loop + delegate git adapters, the 1.8k-line git simulator, contract suites) | 3,300-4,266 | critical | Largest real duplication. Sequence: read-only parity and error compat first, then simulator and contracts, mutation families last. Touches land authority: every step announced; GITREAD fault semantics are the baseline. |
| 3 | **stream_proc.testing** (process simulation + no-spawn guards + fake clocks, both procsim modules) | 325-361 | low | Lowest-risk start; four lenses name it. Tests only; no factory behaviour changes. |
| 4 | **check-output** (build diagnostics parser, report trimming, 1,488-line checklogs corpus) | 558-628 | low-med | Pure functions with fixtures. |
| 5 | **typed-json / record-schema** (strict records, schemas, golden harness; both codec dialects) | 694-768 | med-high | Delegate first, task-loop after; app wire goldens stay app-owned. |
| 6 | **jsonl-log evolution** (bytes parser, byte-budget tails, cursors, compaction, append pool) | 478-642 | med-high | Dashboard poll adapter first. |
| 7 | **source-audit / blueprint** (AST measurement, ratchets, structural rule runner) | 298-530 | low | Gate machinery, app rule tables stay local. |
| 8 | **browser harness + formatting** (iframe/layout JS, neutral UI primitives, timefmt dialects) | 323+112+42 | low | Dashboard and delegate cockpit. |
| 9 | **agent-stream** (vendor event/transcript/usage decoders for codex, claude, opencode) | 470-651 | med | Replay each vendor on synthetic fixtures; settlement stays in delegate. |
| 10 | **process-lock / stream-proc completion** (cancellation, ticket queue, captured runs, recorded handles) | 240-400 | critical | Shared prerequisites for later migrations; carries the pid-fence and stale-takeover history. |

The remaining items (HTTP/static, caches, network probe, shell syntax facts, time input, ids, config overlay, memory facts,
bd transport) are small, listed with exact spans in the lens documents.

## What the owner's refinement changes (critique before extraction)

The lenses list candidates and the lines that would move. Per Denis's order, each phase-2 package starts with a **critique**:
what gets simpler once the abstraction exists (same job in several shapes becomes one; arguments and branches that exist only
because the abstraction is missing disappear). The package is then written to the redesign, and the apps are refactored onto it
(usually more than a small change). Volume is therefore counted after the refactor, not by the donor spans alone: the real
reduction can be larger than the table, and the critique is where it shows.

## Start order (proposed)

1. Now: **stream_proc.testing** (3), **check-output** (4): low risk, tests only; they establish the whole pipeline (shelf worktree, tag, app pins).
2. In parallel: the **D0 design** (1) as a read-only critique, because it decides how every later package is consumed.
3. Then: **source-audit** (7), **browser harness** (8), **typed-json** (5), **jsonl-log** (6); **git-porcelain** (2) starts with read-only parity once (3) has proved the release mechanics; **process-lock/stream-proc** (10) when a migration needs it.

## Gaps and caveats

- Each lens counted lines by `wc`; none ran the code. A candidate's contract tests are proposed, not written.
- The cross-repo lens (a2kay, homelab, a2peer) is not in the table yet; lifesim is owned by the lifesim session.
- The stdlib/3rd-party lens found almost no drop-in replacement it was willing to claim (0 lines booked): the hand-rolled code mostly encodes behaviour the libraries do not (fences, byte budgets, locks with holder files).
