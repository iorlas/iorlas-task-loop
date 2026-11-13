# Grilling record: candidate 1, the tracker seam (2026-11-13)

## Settled
- The seam has beads and a fake now; the owner plans more backends. **For now local beads is always the claim store**; Jira and GitHub Issues are task sources (import) and sinks (report back), see brief-external-sources.md. Long term the claim store should be a server; keep the interface able to host one.
- Outcome types are **generic classes in the factory's tracker module** (claim lost, blocked, already closed, ...), never beads-specific. `beads_client` keeps its own types. Unexpected failures throw one `TrackerFault` family carrying kind, operation, task and text, so the UI can show a blocker with a copy-context button for an agent.
- Beads-specific text and commands live only in the adapter. The factory writes a concrete but tool-neutral sentence; the adapter supplies the deeper explanation per outcome type.
- One shelf package per backend; clients must not know the factory. The three-tier question (shelf, modules of an app, app) is parked.
- Actor default stays `taskloop`, configurable. The `adapter` column stays; `'beads'` stops being spelled in 6 queries (one parameter).
- Config in three places: repository file (shared), global machine config, and a `.local` file in the repository for per-person preferences.

## Rules the owner wants in the constitution (drafts; CLAUDE.md and AGENTS.md are mirrored)
1. **No magic strings.** A closed vocabulary is an enum or a class. A string appears only at the edge that stores or prints it (database, logs, CLI), through one codec per vocabulary. (120 `Literal[...]` types in 38 modules today.)
2. **Challenge every glossary addition.** Before adding a term: is it needed, is the name right, does it fit the domain around it.
3. Adapter details never leak: no tool names, commands or error strings of a backend outside its adapter.

## Open
- Pickup rule shape (assignee default, optional label); config-tier invariant; pydantic or stdlib; admission lifecycle (candidate 11) before the tracker verbs.
- Naming of the `held` replacement waits for brief-review-model.md.

## Round 4 additions (2026-11-13)
- Pickup rule: all listed conditions must hold; label `auto` stays the default; assignee is an optional, project-specific condition (me / unassigned / named); an empty rule is refused.
- `.local` invariant accepted: facts deciding what is verified or landed come only from the Git profile.
- Admission/release are acquire/release (front and back gate). Depth A, B (idempotent outcomes) and C (adopt "claimed, no attempt") wanted; names of outcomes follow the vocabulary decision.
- Data contracts: owner prefers best third-party libraries if tests shrink; enums stay stdlib. Evidence: a2kay depends on pydantic>=2, pydantic-settings, jsonschema; no "too heavy" decision found. Tradeoff to check: entry-process import closure (see .importlinter contract `entry-never-imports-the-command-surface`).
- Glossary diet wanted (137 rows, 52 KB): delete a term if plain English or derivable by chaining defined terms. Proposals: round→tick (drop move, settle); admission→acquire; repeat→retry attempt; advance→next-step attempt; "check" only for the profile's named validation; land_check→land_candidate.

## Round 5-6 additions (2026-11-13)
- Scheduler: tick, reconcile, backoff, wake; `tl tick [--every N]`; no shelf extraction yet (local `ticker.py`, ~60 lines). `move`, `settle` dropped.
- Check family: check (named validation), check suite (was block), check run (was check result); SQL CHECK = constraint. Step and land re-run are one concept (suite at commit C) with two owners.
- Renames accepted: launch -> spawn. Pydantic v2 at the edges. Idempotency depth C.
- Terminology rules wanted (constitution or glossary; mirror CLAUDE.md/AGENTS.md):
  1. A new term borrows GitHub's word first.
  2. Else it chains existing terms (e.g. retry attempt).
  3. Before a term is added, present options and the rationale to a human and wait for the decision.
- Opus naming report: reserve/release (admission), place, bind; `check suite`/`check run` from GitHub Checks; delete candidates listed in the report's card 12.

## Round 7 (2026-11-13)
- Accepted: the three terminology rules (GitHub word first; else chain existing terms; options and rationale to a human before any term is added). To be written into CLAUDE.md and AGENTS.md (mirrored) by whoever the owner authorizes.
- `land_check` kept (it runs a check suite at S as a subtask of landing); no `land_validate` term; one word family for validation: check.
- Open: reserve/release vs another name, first/retry attempt, keeping `dispatch`.

## Round 8 (2026-11-13)
- Accepted: reserve/release (admission and its release; `tl step start` = reserve + spawn); first attempt / retry attempt (advance, relaunch, resume dropped as terms); keep `dispatch` (the once-only permit to run the agent).
- Open question raised by owner: why a separate Python entry process per attempt (cost?). See answer in chat; alternatives: coordinator-supervised, or detached agent + reconcile.

## Round 9 (2026-11-13)
- Kept: one entry process per attempt (restart rule of 2026-11-08); document it. Measure its start-up once pydantic is in; if slow, consider detached agent + reconcile.
- Rule to document: drain before a schema-changing upgrade (same schema: running entries keep writing; new schema: old entries cannot write and the database is discarded).
- Remote agents: the entry process is close to the seam; the database must then be reachable (ties to the storage interface).

## Round 10: tracker interface (2026-11-13) - accepted
- One `Tracker` module replaces `ReadyRows`, `TrackerClaims`, `TrackerHolds`; the dashboard gets a read-only type.
- Reads: ready(rule), task(id), comments(id), titles(ids). Writes: claim, unclaim, heartbeat, close(id, reason), comment, review-marker verbs (placeholders until the review-model bead).
- Outcomes are generic classes (Claimed/HeldElsewhere; Closed/AlreadyClosed/ClaimLost/Blocked/Missing); unexpected failures throw TrackerFault. Capabilities: lease_ttl, sync hint.
- Claim holder and expiry live on the task facts.
- Factory-side FakeTracker plus one contract suite over the fake and the real beads adapter (marked). It must prove: idempotent claim, fenced close/unclaim, lease lapse on an injected clock, distinct missing/blocked/unavailable.
- Tests that patch `Bd` are deleted; behavior tests through the interface stay.

## Not yet decided / follow-ups
- Review model and the name for `held` (bead). External sources and code host (bead). Glossary diet (bead). Constitution rules text (no magic strings; terminology rules; no backend details outside its adapter).
- Still unexplored candidates: 2 (VCS seam), 3 (storage), 4 (message owners), 5 (folders), 6 (tests), 10 (per-step settings), shelf adoptions (9).

## Round 11-13 (storage and composition)
- Decided: replace `held` with markers needs-info / review-requested / blocked (umbrella: waiting). Import = command `tl task import <ref>` + source adapter. Land mode `push|pr` optional + code-host seam. Manual `tl task refresh`. One factory per repo. Glossary diet in two stages. Constitution draft + beads sent to parent session.
- PR comments: come back as a retry attempt; person merges (Q7 accepted).
- Owner direction: vertical slices over a shared `state/` folder; service per slice; sqlite-store grows into a real DB library/ORM (no shortcuts); row-mapping helper belongs in shelf; dashboard writes too (same transitions); SQLite single writer -> short transactions.
- Open: golden source later? (factory.db is disposable today by the 2026-11-08 rule; not changed.)
- Composition map: composition-map.html (15 Store(SCHEMA) sites, 24 sqlite importers, 20 Connection signatures, 5 GitViews sites, land_check/validate import the root).

## Round 14-18 and Haiku rounds 1-3
- Decided: slice = folder owning one noun (use-case modules, store.py, api.py); plan and implement thin step folders; steps implement engine-owned Step contract; flow table = data in code; rework = backward edge, cap per task; engine owns attempt/reservation/slot tables, steps own result tables; migration: slot release -> checks as step -> land; tests mirror folders; ratchet enforcement; ADR per decision naming enforcing test; policy numbers to config tiers; mechanism constants one owner per slice.
- Composition: per-slice compose(ports) + thin root per process (proposed, awaiting yes). Crash tests: table-driven (state x crash point), measure cost first.
- Findings (rounds 1-3): A restart gaps (dispatching/registered -> stuck:entry_lost, captured pending -> abandoned, claim w/o attempt only with --retake-lapsed, evidence and remote-branch orphans); B trust (profile setup/checks run on host with HOME+network from the commit under test; logs served by dashboard w/o auth; evidence files default umask); C growth (attempts evidence never deleted, 9 grow-only tables, quick_check per RW open, attempts() scans history, board rebuilt every 2 s); D single-tenant (origin, task/, actor, git identity, profile name fixed; land only main; beads in 13 modules, Codex in 8 outside adapters); E operator (~20 refusal kinds w/o next action, no doctor); F tracker.gone() matches bd error text at 6 sites; G vocabulary (no Enum, 78 Literals, 58 word sets, 318 inline string compares, Conclusion defined twice, step names in 4 places, ids minted in 7 logic places); H docs/CLI (README stale, 17 docs no status, --checkout 4 shapes, exit 3 meaning differs, rounds --json prints 2 documents); I Git surface (74 call sites ~12 methods; jj: worktree->workspace, branch->bookmark ok; index, detached HEAD, hooks, .git pointer no clean fit); J shelf reuse (timefmt, app-dirs, verb-cli, jsonl-log, any-proc, sqlite-resource, due-schedule; promote UTC stamp x4, canonical-JSON-hash x3, ticker x4); K clean (dead code 1 constant, 4 near-duplicates, no external call in a write tx, no mocks, no ambient clock in logic).
- Round 4 running: module->slice map (Opus), step prompts/agent settings, first-run/packaging, docs authority map.

## Haiku round 4 (stop: yield is docs, packaging and refinement; no new structural risk)
- Module->slice map (Opus, slices.py in scratchpad): 72 edges break the target rules after the move (27 upward, 12 step->step, 33 engine/hold/tracker peers; peer rule assumption); 17 hold->engine.attempt, 11 land->checks; hardest: attempt_types, attempt_reads, operations (596 lines), factory_schema, attempt_status, check_store. Migration order: kernel (ids, outcomes, Tx) + layer contracts in report mode -> per-slice DDL, sqlite3 behind store.py -> steps registry to compose, split operations -> break land->checks via port, dash_composition into dash -> settle hold's layer -> move folders and enforce.
- Open design question: hold's layer (above the engine, or injected read ports for check/setup stores).
- Step prompts: code strings in plan_step/implement_step; agent hard-coded CodexHarness (attempt.py:208); model/effort only CLI flags; no per-step override. StepKind: data = name, environment, answer_schema; code = rules, input_text, decode, artifact, feedback.
- First run: not possible from docs alone (slots, Codex auth, bd, first task missing); README pins git-porcelain 0.15.0 vs 0.18.1 in pyproject; no CI (.github absent); codex/git/Python 3.15/tailwind unpinned; version "0".
- Docs: INDEX.md omits 48 of 106 files; layers.md is "proposed"; README stale; 20 files describe unimplemented designs; 10 decisions live only in plan/trial files (ADR candidates).

## Round 19-20 (candidate 4: message owners)
- Decided (owner): outcomes are typed values, no parsing of strings into pieces (no regex, startswith, split for control); strings are parsed only as JSON (or YAML for human-authored files). Tokens matter: tabular output may be TSV; owner open to shorter formats (S-expressions, CSV/TSV) instead of JSON everywhere. Slice-owned message catalogs keyed by the outcome enum (yes), one command table in the CLI (yes). Raw errors/tracebacks are readable in the dashboard but attached as detail under a typed statement (outcome of the stage, failure, ...), never inside the sentence. printable.py moves to shelf (reusable). Failures are also recaptured in history/log.
- Owner vision: workflow (steps and flow) later in a YAML file; some steps reused from code and cited in the YAML with when/how/parameters; the CLI should discover available steps/commands dynamically. Asked about a CLI library (Typer?). shelf `verb-cli` already maps a pydantic-annotated function signature to argparse flags (stdlib only); research agent comparing click/Typer/cyclopts/cappa running.
- Synthetic measure: 20 rows x 8 fields: TSV = 42% of the characters of compact JSON (token counts not measured).
- Tests: table tests (parametrize) welcome; split suites in tiers; few string permutations because strings stay at edges. Niche pytest plugin research running.

## Round 21 (accepted)
- Q1-Q5 accepted: formats JSON (nested) / TSV (tables) / text (humans), `--json` becomes `--format`, default adapts (not a TTY -> machine format; override by flag or env); YAML only for human-authored workflow/config; suites in tiers; step = class + parameter model, registry waits for the YAML workflow; stopping outcomes (needs-info, review-requested, blocked) are rows in the human-requests slice with typed facts and raw detail, dashboard history reads them, log gets one line per row; CLI generates step commands and flags from the parameter models.
- Q6: argparse + shelf verb-cli (ours, 0.1.0, 225 lines + 220 test lines); owner wants verb-cli grown: move CLI mechanics out of the task-loop package into it; no Typer, click, cappa; cyclopts not needed.
- Q7 and plugin trials: trial many (parametrize, subtests, pytest-impacted, pytest-check vs subtests, pytest-durations, pytest-deadfixtures, syrupy); import-linter stays and grows. Owner asked for a GitHub search for testing nuggets, especially for agentic development (two research agents running: agent-oriented testing; architecture enforcement tools).

## Round 22 (accepted) and candidate 2 start (Git interface)
- Accepted: verb-cli is the future CLI library, upgrade it and move the generic CLI mechanics into it; possible rename to `any-cli` (shelf has an `any-*` family: any-agent, any-proc, any-clock, any-file, any-lease, any-shell-policy...; verb-cli is the outlier); pytest plugins up to me, give time to trial. Default output: not a terminal -> machine format chosen by the result's shape (table -> TSV, nested -> JSON), a terminal -> human text, `--format` overrides; agents capture stdout so they are not a terminal (no environment sniffing needed).
- Candidate 2 facts: git-porcelain (shelf 0.18.1) is already the Git interface with real and fake adapters (real_worktrees.py, fake_worktrees.py); taskloop still parses Git output itself (slot_state: `status -z` records, `.git` pointer regex that duplicates git_porcelain's `real_env.git_dir`; `worktree_state` returns raw bytes), reads trailers by string split (factory_commit:214, prepare:78), hard-codes origin, task/, main, identity (publish, land_push, prepare, git_views, check_admit), prints `git ...` hints in ~20 modules, and writes "Squashed from task/..." in land_summary. Open fact: "C1" = Jujutsu?

## Round 23 (accepted) - candidate 2, the version-control interface
- Decided: Git stays the only VCS for now; the interface is in domain verbs; all Git mechanics move into git-porcelain (shelf), using it properly and adding composite operations there when needed; task-loop parses no Git output (structured output only, trailers through Git's structured output); one `vcs` slice owns the domain rules (branch name, trailers, squash fields, identity, remote) and every other module asks it; config tiers for remote, branch prefix, identity; land accepts any profile target; the Git adapter is the only place the tool is named: "remove any mention of Git from our codebase" (51 of 99 modules mention the word, 317 lines; 30 import git_porcelain); the git-porcelain fake is the test surface and one contract suite runs against real Git on temp repos.
- Correction: "C1 = Jujutsu" was my guess; the owner never said it. The second VCS the owner expects is Anthropic's own (their information; I cannot verify it); not now. Jujutsu is dropped from the notes.
- Open: name of the pull-request/review abstraction (code host vs forge); owner asked how to generalize it.
