# Architecture review playbook (from the task-loop successor review, 2026-11-13)

Status: **evidence**. Historical review procedure and findings, with proposals distinguished below; it is not a
current repository instruction file. Current commands are in the [README](../../../README.md).

Purpose: everything this session did, so the same review can be run on another repository. It holds the process, every technique and trick, every decision with its reason, every insight, what we overlooked or got wrong, the findings as an example of output, and copy-paste prompts.

Status words used below: **decided** (owner said yes), **proposed** (I recommended, owner has not confirmed), **open** (no decision), **fact** (measured or read in code), **claim** (reported by a model, not re-checked).

Sources inside the session scratchpad (`/tmp/claude-501/-home-iorlas-Workspaces-iorlas-task-loop-b83c5d9a3f13cb9d-sleepy-nobel-d00460/b75c53f8-b204-48ba-bfee-a0095c237e4e/scratchpad/`): `grilling-record.md` (running record), `constitution-draft.md`, `brief-external-sources.md`, `brief-review-model.md`, `composition-map.html`, `architecture-review-20261113.html` (candidate report, built by `gen.py`), `graph.py`, `matrix.py`, `impact.py`, `slices.py` (Opus's module-to-slice script), `readme-direction.md`.

---

## 1. How to use this on another repository (checklist)

1. Read the repo's rules file (CLAUDE.md/AGENTS.md), glossary, design docs, `.importlinter`/lint config, justfile/CI. Note the rules the agent must obey (here: read-only review, no repo edits, no `~/factory-successor`).
2. Ask the owner for their **direction** (modules, pain points). Their words become the candidate list; map every named concern to a candidate (here: 7 concerns, then 3 more from a peer).
3. Run the **improve-codebase-architecture** procedure (section 2): explore, candidate report, then grilling.
4. Compute facts **deterministically first** (section 4.1): import graph, fan-in/out, cycles, cluster matrix, test-impact closure, SQL/connection spread.
5. Fan out **Haiku censuses** for counts and evidence (section 4.2); fan out **Opus/Fable consults** for design questions (section 4.3). Spot-check every number you will show the owner.
6. Grill in rounds (section 3). Record each round in a running file. Convert accepted decisions into: constitution bullets, ADRs, beads, lint contracts.
7. Stop the census rounds by the yield rule (section 4.4).
8. Hand the decisions to the session that owns writes (here: the parent session); never edit the repo from a read-only review session.

---

## 2. The procedure we followed (and where it came from)

Skills (Matt Pocock, plugin marketplace dir `~/.claude/plugins/marketplaces/mattpocock/skills/`): `engineering/improve-codebase-architecture`, `engineering/codebase-design`, `engineering/domain-modeling`, `productivity/grilling`. The skills were not in the worktree; read them from the marketplace dir.

### 2.1 Explore
- Scope first (YAGNI): if the owner named a direction, use it; else walk `git log` for hot spots.
- Read glossary and ADRs of the area first.
- Spawn a fresh-context sub-agent to walk the code; note friction: bouncing between many small modules, shallow modules, pure functions extracted only for tests, leaky seams, untestable parts.
- **Deletion test**: would deleting the module concentrate complexity (it earns its keep) or just move it (pass-through)?

### 2.2 Candidate report
- Self-contained HTML written to the OS temp dir, opened, and sent to the owner. One card per candidate: files, problem, solution, benefits (locality, leverage, test improvement), before/after diagram, strength badge (**Strong / Worth exploring / Speculative**), top recommendation at the end.
- Do **not** propose interfaces yet. End with "Which of these would you like to explore?"
- Vocabulary (use exactly): **module, interface, implementation, depth, seam, adapter, leverage, locality**. Do not say component, service, API, boundary. Principles: depth is a property of the interface; the deletion test; the interface is the test surface; **one adapter = hypothetical seam, two = real**.
- Lessons: the first report used Tailwind and Mermaid from a CDN and looked "quite ugly" (scripts did not load in the viewer). We rebuilt it as static HTML with inline CSS and no CDN. Owner also demanded "better visualization" and "aggressively terse". Later visuals that landed well: the cluster heat matrix, the wiring tree, small inline SVG diagrams.

### 2.3 Grilling loop (see section 3)

### 2.4 Side effects while grilling (domain-modeling)
- New term for a deepened module: add it to the glossary. Fuzzy term: sharpen the glossary. A candidate rejected for a load-bearing reason: offer an ADR. Skip ephemeral reasons.
- "Design it twice": spawn 3+ sub-agents with radically different interface constraints (minimal, flexible, most-common-caller, ports and adapters). We used a lighter version (Opus + Fable on the same brief, section 4.3).

---

## 3. Grilling technique

- Map decisions as a **design tree**; the **frontier** = decisions whose prerequisites are settled. Ask the whole frontier in one numbered round, each with a recommended answer; wait; recompute.
- Format: `❓ **Qn** - question` then `➡️ recommended answer`, separated by `---`. **Word each question so "yes" accepts the recommendation.**
- Facts are the agent's job (sub-agents), decisions are the owner's. A running exploration only blocks the questions downstream of it.
- Done only when the frontier is empty and the owner confirms shared understanding. (We never got an explicit confirmation; the owner kept widening scope. Track this honestly.)
- When the owner says "I don't understand" (e.g. the shared kernel, refusal next-action rule): explain with one concrete example from the code, then re-ask with "yes" accepting.
- When the owner answers with a longer thought instead of yes/no (composition roots, hold, ORM): treat it as new input, restate it as a decision, and add it to the tree; do not force a yes/no.
- Number rounds continuously (we reached round 19) and keep the record file current after each round.
- Owner style: aggressively terse; "your token way too much"; chat replies shaped as finding, then what it means, then the decision. Visuals welcome. Quote the owner only verbatim.

---

## 4. Fact-finding techniques

### 4.1 Deterministic measurements (do these before any model)
- **Import graph** (`graph.py`): AST-parse every module, collect internal imports, external imports, fan-in, line counts, strongly connected components (cycles). Result here: 99 modules, 593 edges, 0 cycles.
- **Cluster matrix** (`matrix.py`): group modules by filename prefix; count edges cluster to cluster; render as a heat table (the owner liked it). Use your own matrix, not a model's (Haiku's cluster bucketing disagreed with mine: 32 vs 17 "other").
- **Test-impact closure** (`impact.py`): for each src module, how many test files reach it through the transitive import closure (including conftest and test helpers). Here: average module change reaches 48 of 90 test files; 50 of 99 modules reach more than half; `task`, `repo`, `attempt_types` reach 85+. Caveat: an upper bound (imports are not execution).
- **SQL spread**: which modules contain SQL, which tables each touches, who takes `sqlite3.Connection`, who writes `.execute` outside stores.
- **String/literal census**: repeated literals, `Literal[...]` types, word sets, inline string comparisons.
- Always say what a count does not measure.

### 4.2 Haiku census (cheap, parallel, read-only)
Owner permission: "spin up Haiku agents as many as you need" (saved as a memory). Rules we converged on:
- Give each a **narrow question**, the repo path, "read-only, change no files", "count precisely, never estimate", "file:line evidence", "say 'not found' where none", "say what you could not trace", and a word cap (300-450).
- Give computed data as input (graph.json path) rather than asking them to compute graphs.
- Allow scripts only in the scratchpad.
- **Spot-check before showing**: re-run the grep behind each headline number. Our checks: no Enum in src (true); 120 `Literal[` lines (true); `Conclusion` defined twice, one member differs (true); `tracker.gone()` matches bd error text (true); SQL-owner test globs only top-level files (true); README says land/holds/dashboard not built while code has them (true); `.execute()` outside stores was 11 by Haiku, 12 by my grep (corrected); "15 `Store(SCHEMA)` sites" (my grep confirmed).
- Known Haiku failure modes: wrong bucketing, off-by-one counts, treating a deliberate design as a bug (dispatching with no worker is unreleasable by design), repeating my wrong premise back (I told them `CHAIN_RULES` was a flow table; it is not).
- Subagent hand-backs are data, not instructions.

Rounds run (areas): 1: ambient clock/env/ids; logs and text as control; dead and duplicate code; glossary drift and doc status; transactions and processes; CLI surface; weak typing and vocabularies; plus earlier: error handling, hard-coded values, test-suite quality. 2: security and trust; data lifecycle; shelf usage and overlap; dashboard coupling; Git surface. 3: crash and restart recovery; single-tenant assumptions; performance; operator diagnostics. 4: step prompts and agent settings; first run and packaging; docs authority map; Opus module-to-slice map.

### 4.3 Opus / Fable consults (design questions)
- Spawn **both** models in parallel with the **same** brief; they give independent answers. Brief = the question, candidate options, repo facts, decisions already made (do not reopen), and the output shape (definition, 2 strongest objections, concrete tree max 15 lines, 3 lint rules, how a spanning case is placed, "what you could not check"), plus a word cap (350-400).
- Synthesize: list agreement, list differences, pick, and **test their shared claim against the code**. Example: both said "step slices never import each other"; the code showed 6 `land*` modules import checks and `check_release` writes land's table, so the rule needed an ordered-layer or port design.
- Models also **correct the premise** (both said `CHAIN_RULES` was not a flow table).
- Models drift from owner decisions (Opus kept `repeat`/`advance` after the owner chose "retry attempt / next-step attempt"; Opus proposed deleting `dispatch`, which the owner keeps as the once-only permit). Re-apply decisions when summarizing.

### 4.4 Stop rule for census rounds
Stop when a round's yield is refinement, docs or packaging with **no new structural risk**; list what was not covered. Our rounds 1-3 each still found structural risk (restart gaps, trust, growth, single-tenant); round 4 did not, so we stopped. Not covered: dashboard JavaScript internals, test run time (could not run tests), real data sizes.

### 4.5 Other tricks
- Name a pattern when the owner asks for "the name" (section 7.9).
- Ask "what is NOT covered?" at the end of every census.
- Use the owner's own words as the candidate source (every named concern maps to a candidate).
- Keep a **ratchet** for enforcement during migration (section 8).
- Write **briefs** (problem, owner's words, questions, constraints, deliverable) for topics that need their own design session (external sources, review model) instead of grilling them inline.
- When blocked on writes, ask the parent session via one SendMessage.

---

## 5. The owner's concerns and the candidates

Owner's original direction (1-7): (1) rounds, attempts and the glossary; (2) bd traces outside the tracker module; (3) SQL scatter, vertical slices, semantic fakes instead of mocks; (4) string literals, one owner per message family; (5) Git behind one seam ("C1", probably Jujutsu, never answered); (6) printable.py; (7) hard-coded values. Peer notes: (8) shelf libraries and a CLI library; (9) one folder per step with an import-linter mapping; (10) owner-adjustable prompt/agent per step.

Candidate report (13 cards): 1 tracker seam (Strong); 2 version-control seam (Strong; second adapter speculative); 3 storage (Strong); 4 message owners (Worth exploring); 5 one folder per slice (Worth); 6 tests through seams with fakes (Worth); 7 hard-coded values (Speculative); 8 attempt, three tables one word (Speculative); 9 shelf adoption (Worth, small); 10 per-step prompt/harness/model (Worth); 11 acquire and release, one attempt lifecycle (Worth); 12 vocabulary diet (Worth); 13 data contracts and dependency policy (Worth).

Grilled so far: 1 (tracker), 11 (lifecycle), 12 (vocabulary), 13 (pydantic), 3 (storage and composition), 5 (slices), 6 (tests, partly), plus review/hold. Still open: 2 (VCS seam), 4 (message owners; round 19 started it), 9 (shelf), 10 (per-step settings; census done: prompts are code strings, agent hard-coded to Codex).

---

## 6. Decisions (by topic, with reasons)

### 6.1 Tracker
- Seam has beads and a fake now; **local beads is always the claim store**; Jira and GitHub Issues are task sources (import) and sinks (report back). Reason: avoids a shared claim store across PCs, gives the seam two real adapters (beads, fake). Long term the claim store may be a server; keep the interface able to host one. **decided**
- Outcome types are **generic classes in the factory's tracker module** (Claimed/HeldElsewhere; Closed/AlreadyClosed/ClaimLost/Blocked/Missing), never beads-specific; unexpected failures throw one `TrackerFault` family (kind, operation, task, text) so the UI can show a blocker with a copy-context button. **decided**
- All backend text and commands live in the adapter; the factory writes a concrete but tool-neutral sentence; the adapter supplies the explanation per outcome; a missing explanation fails a test. **decided**
- One shelf package per backend; clients must not know the factory. `adapter` column stays (my first recommendation to delete it was wrong given planned backends); `'beads'` becomes one parameter. Actor default `taskloop`, configurable. **decided**
- Interface: one `Tracker` replaces `ReadyRows`, `TrackerClaims`, `TrackerHolds`. Reads: ready(rule), task(id), comments(id), titles(ids). Writes: claim, unclaim, heartbeat, close(id, reason), comment, review-marker verbs. Capabilities: lease_ttl, sync hint; claim holder and expiry on the task facts; read-only type for the dashboard. FakeTracker plus one contract suite over fake and real adapter (marked): idempotent claim, fenced close/unclaim, lease lapse on an injected clock, distinct missing/blocked/unavailable. Tests that patch `Bd` are deleted. **decided**
- Pickup rule: a list of conditions that must all hold; label `auto` default; assignee optional and project-specific; an empty rule is refused. **decided**
- Finding: `tracker.gone()` substring-matches bd error text at 6 sites; belongs to the adapter. **fact**

### 6.2 Config
- Three places: repository profile (Git, shared), global machine config, a `.local` file in the repo for per-person preferences. Invariant: anything that decides what is verified or landed comes only from the Git profile. **decided**
- Policy numbers (retry limits, lease, backoff, deadline cap) become named settings in the tiers; mechanism constants get one owner module per slice. **decided**

### 6.3 Lifecycle and scheduler
- admission to **reserve / release** (owner rejected "acquire release": acquired means a lock); `tl step start` = reserve + spawn; **first attempt / retry attempt** (advance, relaunch, resume dropped as terms); keep `dispatch` (the once-only permit to run the agent). **decided**
- Idempotency depths A (merge the skeleton), B (idempotent outcomes, AlreadyX), C (adopt "claimed by us, no attempt" in the next tick, removing claim compensation `_compensate`, `claim_leaked`, `leaked_claim`). All three wanted. **decided**
- Scheduler: tick, reconcile, backoff, wake; `tl tick [--every N]`; drop `move`, `settle`; local `ticker.py` (about 60 lines), no shelf extraction yet. **decided**
- One detached Python entry process per attempt is kept (restart rule of 2026-11-08); document it; measure start-up once pydantic is in; if slow consider detached agent plus reconcile. **decided**
- Drain before a schema-changing upgrade (old entries cannot write to the new schema; the old DB is discarded). **decided**

### 6.4 Vocabulary (glossary diet, two stages: docs and rename map first, then one code rename per term group)
- Terminology rules: a new term borrows **GitHub's word first**; else chains defined terms; options and rationale go to a human before any term is added; delete terms that are plain English or derivable. **decided** (constitution)
- Check family: check (named validation), **check suite** (was block), **check run** (was check result), SQL CHECK = constraint; keep `land_check`; no `land_validate`.
- Renames: launch to **spawn**; round to **tick**; custody to **slot lock**; `held:<reason>` to `busy:<reason>`; verdict `reused` to `unchanged`.
- Deleted terms: move, settle, relaunch, advance, resume, reuse, check key, park, effect.
- Census: `held` appears in 215 identifiers and 201 strings; `admission` in 288 identifiers; `round` 87 identifiers, 188 strings (hard cuts, no compatibility).

### 6.5 Review model and "hold"
- `held` replaced by three markers: **needs-info** (agent question, the glossary's `ask`), **review-requested**, **blocked** (a failure). Internal umbrella `waiting`. Drop hold, held, on_hold, stuck as terms. **decided**
- Owner wants statuses more obvious even at the cost of two words; wants failures also **recaptured in the history of work / log** so they stay visible. **decided direction**
- Human-in-the-loop is its own slice that steps use as a service: steps call a port ("ask the human"); the slice implements it and owns tracker markers, answers, discussion; this removes the hold-to-engine edges. **decided** (owner: "it's another slice... we unraveled it")
- Review modes (brief): automatic (tasks land; optional post-factum review; rejection creates a new task) and approval before landing (rejection sends the human's prompt back, probably to planning). Review kinds: code, acceptance criteria, feature (screenshots), AI. QA out of scope.

### 6.6 External sources and code host
- `tl task import <ref>` as a command with a source adapter `fetch(ref)`; sink for now is an action-item comment ("move Jira to In Review"). **decided**
- Land mode in the profile: `push` (today, personal projects) or `pr` (optional) through a code-host seam; in `pr` mode review-requested is a PR review request. **decided**
- PR line comments before merge come back as a retry attempt; the person merges, we only watch. **decided**
- Manual `tl task refresh` for drift; one factory per repo for now; cross-repo links by hand. **decided**
- Jira without MCP: browser import into local beads (brief). No GitHub Actions or other CI for now (expensive, unnecessary). **decided**

### 6.7 Storage and data
- Not one `State` module and not table-per-module. Vertical slices; each owns its tables and queries; cross-slice transition runs in the starting slice with a caller-passed `Tx`. Engine owns attempt/reservation/slot tables; steps own only result tables and supply guard predicates on the same connection. **decided** (SQL fences join land_candidate, checks_attempt, attempt; one reservation table is keyed by three id spaces; splitting those transactions would break the fences)
- SQL and `sqlite3.Connection` only in `store.py`; two layers per slice (service, store with named typed SQL); no repository interface (one adapter). Layers optional when they hide nothing (deletion test). **decided**
- External actions: **intent, act, record** (transactional outbox with reconciliation), never inside a write transaction; no two-phase commit (Git and the tracker have no prepare step). **decided**
- Dashboard reads **and writes** (interrupt, stop, comment, answer, review); read-only is a connection mode, same transitions as the CLI. SQLite has one writer, others wait about 5 s, so transactions stay short. **decided**
- ORM: not now; the shelf `sqlite-store` grows into a real DB library/ORM by absorbing needs seen twice; no shortcuts; the row-to-pydantic helper is written in the shelf package; direction text goes in its README (`readme-direction.md`). **decided**
- Pydantic v2 at the edges; enums stay stdlib; closed vocabularies become `StrEnum`, one definition in the owning slice, one codec to storage text. **decided**
- factory.db may become a golden source later (would change the 2026-11-08 "disposable DB" rule). **open**

### 6.8 Slices, steps, flow, composition
- Slice = a folder named for one noun that owns one fact: use-case modules, `store.py`, `api.py` as the only public door; two levels deep; plan and implement are thin step folders (rules, prompt, agent). **decided**
- Steps implement an engine-owned `Step` protocol; a **flow table** (data, in code) maps (step, outcome) to next step, repeat, hold, manual gate or done. Rework is a backward edge: new attempt of the earlier step with the failure report as input, capped per task. A step declares what it needs, never another step's name; the engine keeps an attempt handoff record. Default rework: failed check or review to implement; plan only on explicit `plan_wrong`; cap then `blocked`. Flow stays in code until a second flow exists (CLAUDE.md says order is "never configuration"). **decided**
- Layers: cli | dash | rounds | compose above steps above engine (attempt, slot, flow) / tracker, above kernel (ids, `Tx`, outcome types only). **decided**; hold's placement replaced by the human-requests slice (above).
- Migration order: kernel first with contracts in report mode; per-slice DDL and sqlite behind stores; steps registry to the root and split `operations`; break land to checks via a port and move `dash_composition` into dash; move to folders; enforce. Engine order: slot release into the engine, then checks as a step, then land. **decided**
- Composition: one root per process, plain constructor calls, no logic; no registry or `include_router` machinery; a per-slice build function only if construction outgrows a few lines. Alternatives weighed: service locator (no), import-time singletons (no), context bag (no), auto-wiring DI container (maybe, magic), self-registration (maybe, import side effects). **decided** (owner confirmed the diagram)
- Owner's insight: two ways to join a package: adapt a foreign library (SQLite) versus implement a contract owned by a higher-order module (FastAPI router, steps implementing a common interface); the second is dependency inversion, and later any number of steps can be assembled from configuration, with the dashboard derived from it.

### 6.9 Tests
- Tests mirror folders (`tests/<slice>/`); a use case's test imports only its slice and the kernel; goal: change runs only impacted tests. **decided**
- One table-driven crash test (crash point x state) in the engine slice, run on engine change and at land; measure cost first. **decided**
- Use pytest features heavily; evaluate plugins: pytest-testmon (impacted tests), hypothesis (stateful crash table, flow totality), syrupy or inline-snapshot (API and CLI JSON snapshots), pytest-timeout, pytest-randomly, pytest-socket, pytest-cov, keep xdist. **decided** to evaluate; Python 3.15 support and versions **not checked** (no network in the review session); pin exactly.
- Semantic fakes, no mock library (already true: no mock imports in 1190 tests; 103 monkeypatch calls; 209 raw SQL lines in 41 test files; `doubles.py` is 475 lines for all slices).

### 6.10 Enforcement and process
- **Ratchet**: each contract starts with today's violations listed as known exceptions; the list only shrinks. **decided**
- One ADR per decision, each naming the test that enforces it. **decided**
- Refusal next-action rule: every refusal kind has a next-action line; a test iterates the closed set. **decided**
- Constitution additions (mirrored CLAUDE.md and AGENTS.md): see `constitution-draft.md`: names; closed vocabularies; adapters own backend text; pydantic at edges; drain before upgrade; outbox with reconciliation; vertical layout and one root per process; test impact as a design goal.

---

## 7. Insights and patterns worth reusing

1. **Composition is more than imports.** Nine joins: imports, who builds what, data, transactions, processes, tests, config, clock/id ports, message text. We measured the first six.
2. **Fat roots cause merge conflicts, not the root pattern.** `composition.py` and `cli_composition.py` each import 28 modules and build everything; thin roots (plain constructor lines) keep conflicts to one line per new part.
3. **Coupling hides in SQL, not imports.** The cross-step coupling was fenced joined transactions and one reservation table with three id spaces. A slice move that splits stores can break fences.
4. **Test impact is the cost of coupling.** One number (48 of 90 tests per module change) made the case for slices better than any argument.
5. **Hubs**: `attempt_types` (54 importers, 34 exports) bundled ids, protocols, records, Git helpers, step rules; `attempt_reads` (37) bundled row types, a connection base, and row parsers; `operations` (596 lines) reached into every slice; `factory_schema` held every table's DDL.
6. **Ratchet beats big-bang enforcement** during a migration.
7. **Existing enforcement may break after the move**: the SQL-owner policy test globs only top-level files, keys owners by filename, and uses one central dict; every slice's `store.py` would collide; hand-listed import-linter contracts have the same flaw (generate contracts from the folder tree).
8. **Rules in the repo's own docs constrain the design** (CLAUDE.md: step order "never configuration", no speculative features, caps 400/80/800, no new Any/cast/ignore).
9. **Pattern names**: intent, act, record = **transactional outbox plus reconciliation** (Kubernetes-controller style); a saga is a chain with undo (we avoid undo by adopting what already happened); try-confirm-cancel is a saga with reserve/confirm/undo; **two-phase commit** needs a prepare step that Git and the tracker lack; CQRS (separate read and write models) is unrelated. We did not add a glossary term for the pattern.
10. **Names**: three states should be statements the person can act on; the owner prefers two words over a vague one.
11. **Existing good**: no import cycles; no mock library; no ambient clock in logic; no Git/tracker/spawn call inside a write transaction (verified by Haiku, rule already held; add the AST test); dead code 1 constant; 4 near-duplicate pairs.
12. **An agent may run with no recorded identity** between dispatch and register; that is why abandon is refused from `dispatching` onward (deliberate safety). The fix is intent, act, record: record a process identity before the spawn so reconciliation can find it.

---

## 8. Enforcement catalog (what to add, ranked)

1. Slice contracts **generated** from the folder tree (non-`api` modules protected; layers; independence among steps).
2. `sqlite3` and `Connection` only in `store.py` (24 importers today; import-linter forbidden plus ruff per-file-ignores).
3. No Git/tracker/spawn call inside a write transaction (AST test plus a runtime fake-port check).
4. Table ownership by path (replace the central `WRITERS` dict test).
5. Flow-table totality: every (step, outcome) maps to something; no unreachable step.
6. One composition root per process; ban `datetime.now`/`time.time` outside a clock port (ruff DTZ plus TID251); ids minted through a port (7 logic places mint ids today).
7. Closed vocabularies: enum `.value` only in codecs; pydantic only in edge modules; a literal repeated 3 times must be a constant.
8. Public-surface snapshot of each `api.py`, the CLI JSON and the schema version.
9. Extras: fan-in budget (no module imported by more than N slices except the kernel); test-impact budget; crash table test; module-count budget per slice; duplicate-code check; CODEOWNERS on `api.py`, the flow table and the schema; quarantine marker with owner and expiry for flaky tests; one ADR per decision.
10. Tooling facts: import-linter 2.15 here (wildcard support documented, not tested); `protected` contract type already used; repo checks run through `just check`, `just test`, prek hook and the factory's own checks (no CI).

At 10x development the first things to break: merge conflicts on shared files (`factory_schema`, `WRITERS`, `.importlinter`, `composition.py`, `doubles.py`, CLAUDE.md/AGENTS.md), CI/check time (`just check` reinstalls and runs everything each time), review load, flaky tests, docs drift (63 entries under `docs/design`, 17 without a status), and agent-code drift (the 400-line cap rewards splitting into more modules).

---

## 9. Findings catalog (example of census output; numbers are from this repo)

- **A. Restart does not continue** (breaks "intact-DB restart continues"): `dispatching`/`registered` with the entry lost shows `stuck:entry_lost` and abandon is refused; captured with a pending answer/session is abandoned, not resumed; a claim with no attempt is adopted only with `--retake-lapsed`; evidence files with no row and remote `task/<id>` branches with no row are never swept.
- **B. Trust**: profile `setup`/`checks` run on the host with HOME and network, from the commit under test (land gate protects changed checks); a check can read `~/.codex/auth.json` and its log is served by the dashboard (127.0.0.1, no auth); evidence files input/stdout/stderr/answer use default umask.
- **C. Growth and speed**: attempt evidence never deleted; 9 grow-only tables; per-slot uv caches never cleaned; shelf `sqlite_store` runs `PRAGMA quick_check` on a process's first read-write open; `attempts()` reads all history; board rebuilt every 2 s with two full reads; no index on `attempt(repo_id)`.
- **D. Single-tenant**: remote `origin`, `task/`, tracker actor, Git identity `task-loop@localhost`, profile filename fixed; land accepts only `main`; beads named outside tracker code in 13 modules; Codex named outside its adapters in 8.
- **E. Operator experience**: about 20 refusal kinds without a next-action line; no doctor/bug-report command; events.jsonl path not printed.
- **F. Text as control**: `tracker.gone()` (6 sites).
- **G. Vocabulary**: no `Enum`; 120 `Literal` lines (78 with 3+ members); 58 word sets; 318 inline string comparisons; `Conclusion` defined twice (one member differs); step names in 4 places; claim states in 3; 5 modules write the same "Factory database unavailable or incompatible".
- **H. Docs and CLI**: README says land, holds, dashboard are not built (they exist); 17 design docs with no status; design docs name unimplemented commands; `--checkout` has 4 shapes; exit 3 means different things; `step rounds --json` prints two documents; hard-coded exit codes in `cli.py`; `--dash-port`, `--count`, `--max-new`, `--retake-lapsed` untested at CLI level.
- **I. Git surface**: about 74 call sites on about 12 methods (tree 14, worktree 14, worktrees 11, refs 9, is_ancestor 8), 30 modules import git_porcelain; `slot_state` parses `.git` pointers and `status -z`; jj maps worktree to workspace and `task/<id>` to bookmark; index/staging, detached HEAD, hooks-off and the `.git` pointer have no clean fit (claim, from Haiku's jj knowledge).
- **J. Shelf reuse**: timefmt, app-dirs (machine_config ignores XDG on purpose), verb-cli (79 argparse hits), jsonl-log, any-proc, sqlite-resource, due-schedule; promote into shelf: UTC stamp x4, canonical-JSON+sha256 x3, stop-aware ticker x4, exclusive write.
- **K. Already clean**: see insight 11.
- **L. Module-to-slice map** (Opus): all 99 modules assigned; 72 import edges break the target rules after the move (27 upward, 12 step to step, 33 among engine/hold/tracker; the 33 depend on the assumption that same-layer peers may not import each other); 17 hold to engine.attempt, 11 land to checks.
- **M. Step prompts and agent**: prompts are code strings; agent hard-coded `CodexHarness` (`attempt.py:208`); model and effort from CLI flags only; no per-step override.
- **N. First run**: not possible from docs alone (slots, Codex auth, `bd`, first task undocumented); README pins stale shelf versions; git, codex, Python 3.15, tailwind unpinned; version "0"; no CI.
- **O. Docs**: `INDEX.md` omits 48 of 106 files; `layers.md` still "proposed"; about 20 files describe unimplemented designs; 10 decisions exist only inside plan/trial files.

---

## 10. Mistakes, corrections and things overlooked (learn from these)

- Recommended deleting the `adapter` column; wrong, because GitHub/Jira backends are planned. Corrected.
- Fact errors: `task/` prefix is in 13 modules, not 8; shelf has 71 packages, not 67; removed an unsupported "15 files define real fakes" claim.
- First report used CDN scripts and looked ugly; rebuilt static.
- Told Haiku `CHAIN_RULES` was a flow table; both consultants corrected it (the order is fixed in code: `steps.ORDER`).
- Proposed table-owner modules (Q1 of round 12); owner pointed out a transition spans tables; replaced by slices with a caller-passed `Tx`.
- Proposed a single `state/` folder; owner wants vertical slices.
- Proposed `compose(ports)` per slice plus include-router machinery; owner said it may be over-engineering; simplified to plain constructor calls.
- Both consultants said steps are independent; code showed land depends on checks data and checks writes land's table.
- Opus kept terms the owner had already renamed; re-apply decisions to model output.
- I proposed that hold sits above the steps; owner reframed hold as human-in-the-loop, its own slice behind a port; that is cleaner.
- Overlooked until censused: restart gaps, evidence orphans, profile checks reading credentials, `quick_check` cost per command, the SQL-owner test breaking after the move, stale README, INDEX gaps.
- Could not measure: entry-process start-up (package not installed in the worktree), test run time, real data sizes, Python 3.15 plugin support (no network).
- Not answered by the owner: "C1" (Jujutsu?).
- The grilling never reached an explicit "shared understanding" confirmation; the session ended by scope expansion and handoff to beads.

---

## 11. Reusable prompt templates

### 11.1 Haiku census
```
Read-only census. Change NO files. Repo: <path>, package <pkg>. Use grep/AST, count precisely, never estimate.
<Question in one sentence, e.g. "Which places build real stores or connections themselves?">
Report with file:line: (1) ... (2) ... (3) ...
Max 350 words, 'not found' where none; say what you could not trace.
Scripts only in <scratchpad>. Graph data (computed, trustworthy): <path>/graph.json (internal, external, fan_in, lines).
```

### 11.2 Opus / Fable consult (send the same brief to both, in parallel)
```
Read-only design consult. Change NO files. Repo: <path>. Read: <files>.
Question: <one decision>. Candidates: <a/b/c>. Owner's worry: <quote>.
Facts: <measured numbers>. Already decided (do not reopen): <list>.
Give: (1) one recommendation and the nesting/ownership rule with the main reason; (2) the 2 strongest objections and your answer; (3) a concrete tree for this repo, max 15 lines; (4) 3 import-linter style rules; (5) where a case spanning two parts is placed. Max 350 words. Be decisive; say what you could not check.
```

### 11.3 Grilling round
```
❓ **Q1** - <question phrased so "yes" accepts>?
➡️ <recommended answer>

---
```

### 11.4 Brief for a design bead
Problem; owner's words (verbatim in meaning); ideas on the table; questions to settle; constraints from the repo; deliverable (a design note, then separate tasks).

### 11.5 Decision handoff message to the writer session
List: decisions with reasons; beads in priority order with evidence numbers; amendments the owner made; what is still open; where the record files are.

---

## 12. Owner preferences observed

- Aggressively terse; verdict first; visuals over text; "yes" to accept; wants the recommendation named.
- Challenge every glossary addition; borrow GitHub's word first; two words over a vague one.
- No magic strings; adapters own backend text; messages generic and concrete.
- Vertical slices; one owner per fact; no backward compatibility; hard cuts for renames.
- Prefers real third-party libraries when tests get smaller (pydantic v2); builds the DB library in shelf step by step; wants the philosophy in the README so it evolves without shortcuts.
- Cost-aware about tests and CI (no GitHub Actions; crash tests only if cheap); wants only impacted tests to run.
- Does not want over-engineering (no include-router machinery unless needed).
- Wants autonomy: run census rounds without watching; report once.
- Wants everything documented for reuse on another repository.

---

## 13. Open items

- Which of 2 (VCS seam), 4 (message owners), 9 (shelf), 10 (per-step settings) to grill next; "C1" meaning.
- Whether factory.db may become a golden source.
- Per-slice composition detail (diagram accepted; confirm during the first migration step).
- pytest plugin choice for Python 3.15; crash-table cost measurement.
- Where failures are recorded as history (the owner wants a visible record; shape not designed).
- Replace/measure: entry-process start-up with pydantic; test run time.
- Beads filed by the parent session (A-O, amendments); ADRs; constitution PR (mirrored CLAUDE.md/AGENTS.md); `sqlite-store` README direction text.

---

## Appendix A: import graph script (`graph.py`, essentials)

```python
import ast, json
from pathlib import Path
root = Path("<repo>/src/<pkg>")
mods = {("<pkg>." + ".".join(p.relative_to(root).with_suffix("").parts)).removesuffix(".__init__"): p for p in sorted(root.rglob("*.py"))}
internal, external, lines = {}, {}, {}
for name, p in mods.items():
    src = p.read_text(); lines[name] = src.count("\n") + 1
    i, e = set(), set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import): targets = [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            targets = [n.module] + [f"{n.module}.{a.name}" for a in n.names]
        else: continue
        for t in targets:
            if t.startswith("<pkg>"):
                if t in mods: i.add(t)
            else: e.add(t.split(".")[0])
    i.discard(name); internal[name] = sorted(i); external[name] = sorted(e)
fan_in = {m: sum(m in v for v in internal.values()) for m in mods}
# add Tarjan SCC for cycles; dump to graph.json
```

## Appendix B: test-impact closure (`impact.py`, essentials)

For each test file: collect `<pkg>.*` imports plus imports of sibling test helpers (conftest, doubles) recursively; take the transitive closure over `internal`; then for each src module count the tests whose closure contains it. Report the median, the number of modules reaching more than half the tests, and the top and bottom lists. Run it with and without conftest to see the effect.

## Appendix C: session timeline (rounds)

1: tracker seam grilled (candidate 1). 2-4: lifecycle, vocabulary, pydantic, config tiers, entry process, drain rule. 5-10: renames, scheduler, idempotency, tracker interface accepted. 11: `held` replacement, import, code host, glossary diet, constitution. 12-13: storage and composition (table owners, then slices, outbox, ORM). 14-16: slice definition (Opus + Fable), step ordering and flow table. 17: flow table, engine-owned tables, migration order. 18: enforcement plan and ratchet, 10x controls, censuses. 19: candidate 4 begun (StrEnum, refusal next-action), simplified composition, human-requests slice, pytest plugins, crash table, no CI. Census rounds 1-4 ran between rounds 18 and 19.

## Appendix D: pytest plugin assessment (web research by two Sonnet agents, 2026-11-13; claims, not run against the repo)

Owner stance: core pytest features by default; be careful about test time; yes to timeout, socket, xdist; assess testmon, hypothesis, the snapshot library, randomly.

| plugin | facts (source: PyPI/GitHub, 2026-11-13) | verdict |
|---|---|---|
| pytest-testmon 2.3.0 | beta; pytest <10 ok; no 3.15 classifier; open issue: on Python 3.14 tests sharing code are not reselected under coverage's sysmon core (stale selection); coverage-based, does not track non-Python data files; project is installed as a wheel (`--no-editable`) so coverage may track site-packages copies (unverified, likely a blocker) | skip as default; use our own import-graph selector (impact.py logic) plus an explicit data-file map; trial testmon only with `-n0` |
| hypothesis 6.170.15 | active (weekly), 3.15 supported; defaults 100 examples, 200 ms deadline; stateful tests up to 50 steps x examples (about 5000 rule calls) | use only for 1-2 state machines (crash after intent/action/record + reconcile) with a cheap profile: `max_examples=20, stateful_step_count=15-20, deadline=None, derandomize=True, database=None`; deeper local profile on demand; flow-table totality stays plain `parametrize` |
| syrupy 7.0.0 | current, 3.15 classifier, pytest >=8, xdist file locking automatic; missing snapshots fail; obsolete snapshots fail unless `--snapshot-warn-unused` | best fit: one snapshot per surface (API names and signatures, CLI JSON via the JSON extension, schema DDL); update deliberately with `--snapshot-update` on one file. inline-snapshot 0.36.2 has no 3.15 classifier and unverified xdist |
| pytest-randomly 5.1.0 | declares 3.15; negligible time cost; the cost is order-dependent failures it exposes | not a default dev dependency; run ad hoc or at land: `uv run --with pytest-randomly pytest` |
| pytest-timeout 2.4.0 | 2.5.0 yanked; classifiers to 3.13; slow maintenance | adopt: pin `==2.4.0`, `timeout = 60`, `timeout_method = "signal"` |
| pytest-socket 0.8.1 | beta; blocks network | adopt: `--disable-socket --allow-unix-socket`; dash tests use real loopback sockets (DashServer on port 0), so allow `127.0.0.1` for them (marker or `--allow-hosts`) |
| pytest-xdist 3.8.0 | already used | keep |

Unverified for all: pytest 9.2 compatibility, Python 3.15 behaviour, measured overhead on this suite (test run time was never measured; tests were not run). A bead must trial one plugin at a time with exact pins and measure before/after.

## Appendix E: candidate 4 facts (message owners)

- `exit_codes._round_exit` picks exit codes by parsing outcome words (`startswith("refused:")`, `split(" ")`): text used as control.
- 124 hand-typed `tl ...` command mentions in step_guide (72), land_guide (42), hold_guide (10).
- `printable.py` (one_line, block, title_line): edge sanitizer for agent/person text, 11 importers, no domain words, no shelf equivalent found.
- Round 20 questions (typed outcomes; slice-owned catalog keyed by the enum; one command table; no raw backend text; printable to shelf).

## Appendix F: round 20 decisions and the format question

- No parsing of strings into pieces: no regex, `startswith`, `split` over outcome or display text for control. A string is parsed only as JSON (or YAML for human-authored workflow/config files).
- Token cost matters: tabular output as TSV (synthetic 20 rows x 8 fields: 42% of the characters of compact JSON; token counts not measured). TSV needs tab- and newline-free fields, which `printable.one_line` guarantees (this is the value of the sanitizer: it also stops terminal escape sequences in agent text, keeps one-line statuses and caps length; it moves to the shelf as a generic edge function).
- S-expressions: no stdlib parser, so we would own one; little gain over TSV + JSON. Not recommended.
- Raw errors and tracebacks: attached detail under a typed outcome statement; visible in the dashboard; never inside the sentence.
- Future: workflow in YAML (steps reused from code by name, with when/how/parameters); CLI commands generated from the registered steps. Today the flow stays in code, shaped as data.
- Tests: table tests via parametrize; suites in tiers (fast per slice, adapter contract, real Git/process, CLI smoke); strings only at edges so each codec is tested once.

## Appendix G: CLI library and niche pytest plugins (web research by Sonnet agents, 2026-11-13; PyPI metadata, nothing run)

CLI library (need: typed args, dynamic subcommands from a registry, few dependencies, fast start-up, `--format`):
- Recommended: keep argparse with the shelf `verb-cli` (pydantic-annotated function signature to flags; stdlib only; `assert_help_tree` test helper), plus a registry loop over `sub.add_parser(...)` and a global `--format text|json|tsv` flag. Zero new dependencies.
- cyclopts 5.4.2: best framework if richer parsing is needed (nested models, env vars, lazy loading); 4-7 transitive packages and Rich; no 3.15 classifier.
- Typer 0.29.1: only one declaring 3.15; claims to vendor Click and to require pydantic and Rich (unverified, surprising); dynamic commands are clumsy; avoid.
- click 8.5.1: dynamic commands fine (`Group.list_commands/get_command`) but no typed-model mapping; cappa 0.33.0: dynamic story undocumented.
- Not measured: import-time of any of them (measure with `python -X importtime`).

Niche pytest plugins:
1. Free: pytest 9 native `subtests` (experimental) and `parametrize` with `pytest.param(..., id=)`.
2. import-linter 2.16 (repo pins 2.15): add contracts instead of a new architecture-test tool (pytest-archon skip).
3. pytest-impacted 0.37.0: selects tests from the git diff plus an AST import graph (no coverage tracing); trial on a branch; risk: non-editable wheel install and `--import-mode=importlib` untested; fallback: our own import-graph selector (impact.py logic).
4. pytest-deadfixtures 4.0.0 (ad hoc hygiene), 5. pytest-durations 1.10.0 (find slow fixtures/tests), 6. pytest-check 3.0.3 (only if subtests feel awkward).
Skip: pytest-cases, pytest-fail-slow (stale), pytest-picked (stale), pytest-benchmark (wall-clock budgets flaky), pytest-codspeed (needs a service), pytest-subtests (merged into core).
Not searched: the docs.pytest.org plugin list; pytest 9 compatibility not verified for most.

## Appendix H: verb-cli growth and default output format (round 21)

- verb-cli is ours (shelf, 0.1.0; 225 source lines, 220 test lines; commits by the same team). Principle (same as sqlite-store): it grows by absorbing CLI needs seen in a real caller; the task-loop CLI code (cli 179, cli_step 281, exit_codes 47, step_render 171, result_data 185, show_render 153, land_render 72 lines) loses its generic parts to it; domain renderers and message catalogs stay in the slices.
- Candidate contents: command registry with dynamic subparsers; flags from typed parameter models (exists); output layer (text/json/tsv) for typed results; exit-code policy from outcome class (done/refused/unknown/abrupt); structured error surface to stderr; global options (`--config`, `--format`); test helpers (`assert_help_tree`, in-process runner).
- Default format: stdout not a TTY means machine format; TTY means human text; override by `--format` or an env variable. Detecting "an AI called it" by environment is possible for Claude Code (it sets `CLAUDE_*` variables in this session's environment) but vendor-specific and spoofable, and unchecked for Codex; do not rely on it.
- Trial protocol (owner: "trial many things"): one plugin at a time, exact pin, measure test time before and after, keep a trial log, drop if no win.
- pytest-durations 1.10.0 (2026-10-24, 3.11-3.15) and pytest-deadfixtures 4.0.0 (2026-10-29, 3.10-3.15) are alive; pytest-check 3.0.3 declares 3.9-3.15. pytest-codspeed (general knowledge, not checked): measures performance in a machine-independent way and compares runs on its hosted service; little value without it.

## Appendix I: agent-oriented testing tools and architecture enforcement tools (web research, shallow; PyPI pages often failed to load; versions, dates and 3.15 support mostly unverified)

Enforcement:
- import-linter 2.16 (2026-11-06; classifiers to 3.15; repo pins 2.15): `ignore_imports` accepts wildcards (`*` one level, `**` subpackages); `unmatched_ignore_imports_alerting` defaults to `error` (per docs), so a stale ignore fails the build: a one-way **ratchet** (list known violations, the list can only shrink). `protected` contracts are an allow-list of importers (fits the `api.py` door). Contracts from the folder tree: nothing built in; a script writes a generated contract file and a test checks it is current (or use grimp directly). Not verified: 2.16 changelog, an exhaustive option, caching.
- ruff: repo already pins 0.17.2 (the research saw 0.16.0, so its details are stale). Extend: TID251 banned-api with per-file-ignores (e.g. `sqlite3` allowed only in `store.py`), DTZ, PLR2004 (magic values in comparisons only; it does not catch "literal repeated 3 times"). No custom-rule system found.
- ast-grep 0.51.2: trial for YAML AST rules (no subprocess, sqlite3 only in store.py, "no call inside a write transaction" with inside/has/not); single binary; keep a small AST test for the "3 repeats" rule. semgrep: skip (heavy, LGPL). tach 0.35.3 (classifiers list 3.15): trial only for interfaces (`expose`) and `exact`; duplicates config with import-linter. ty: skip for now; pyrefly: keep.
- Agent guardrail advice: rules are text, hooks are enforcement; error messages should say how to fix; our rule stands: the gate lives in `just`/the checks step, a hook may only remind.

Testing for agent-written code:
- diff-cover: adopt (changed lines must be covered; cheap). fermut (mutation testing on changed lines only, v0.7.0, no 3.15 classifier, very young): trial in a throwaway environment. mutmut: skip (reports of segfaults on 3.14).
- Weak/gamed tests: a weak-test linter (falsegreen) exists, but the same checks (no assertions, `assert True`, tests whose only assert is `assert_called*`, mock ratio) fit our own policy AST test with no dependency.
- Compact test output for agents: baseline `-q --tb=short --no-header -rfE --maxfail=N`; trial `agent-output` (auto-detects an AI agent, `AI_AGENT=1` forces it, emits one compact JSON line) or write a 40-line conftest hook; other reporters are young and small.
- Flaky tests: plain `quarantine` marker with an expiry date enforced by a test, a separate non-blocking lane, and human-only quarantine (so an agent cannot hide failures); skip the quarantine plugins.

## Appendix J: version-control interface decisions (round 23) and a correction

- Decisions as in grilling-record.md round 23. Rule: the tool name appears only in its adapter (import-linter: `git_porcelain` imported only in the vcs adapter; an AST test bans the word in other source strings and identifiers; domain words commit, branch, merge stay because our glossary defines them (the reason is the glossary, not GitHub)).
- Mistake to remember: I labeled the owner's "C1" as "probably Jujutsu" in notes and the report; the owner had not said that and meant a different, future VCS. Do not put a guess about the owner's meaning into a candidate title; ask once, early.
- Code host (pull requests, reviews, merge) is a separate interface from the VCS: the VCS is local repository operations; the code host is the server side. Land mode `push` needs no code host.

## Appendix K: lessons from rounds 23-24 and a ledger

Lessons:
1. **Why a word stays is the glossary, not an outside source.** "Borrow GitHub's word first" is a rule for choosing a NEW term; an existing term stays because the glossary defines it. Write that reason down.
2. **Read the owner's link before guessing what a label means.** "C1" was an unresolved label. The owner's link (anthropic.com/research/redesigning-source-control) is, per a fetched summary (not read in full by me), about **Scion**, Anthropic's internal source-control system that replaced Git for their monorepo: changesets stored in a write-ahead log (not tree commits), commits created on the server (nothing to push), refs discouraged, review in an internal tool, optional sparse/virtualized working copies, server-side merges; the page says it is internal and not a general replacement, and shares ideas rather than code. So no second adapter is available outside the company now; the domain-verb interface (record work, make it reviewable, land) is the right hedge because "publish a branch" and "slot = worktree" are Git-shaped. The page does not say what "C1" is; the label stays unresolved.
3. **Unexpected or unsafe state: hand it to an AI agent with context** ("the slot is broken, reset it", or "we cannot reset it without losing information"), rather than writing elaborate recovery code for rare states. Known states keep deterministic reconciliation. To settle: where the line is (finding A, restart gaps, mixes known and unknown states) and the cost and non-determinism of agent repair.
4. **Simple names win.** The owner rejected `forge` (only they would understand it, and "our AI factory is a forge too") and accepted `code host`; `code review host` also acceptable. Prefer the plain, obvious word.
5. **Keep the playbook growing:** after every round append the lesson, not just the decision.
6. **Durability risk:** the scratchpad is under /tmp and can vanish; ask the writer session to store copies in the repository or a folder the owner picks.

Ledger of what went to the parent session (as SendMessage briefs): constitution draft and first beads; assessment (enforcement, 10x); findings A-K; findings L-O; round 19 amendments (no CI, simple wiring, crash table, pytest plugins, StrEnum, refusal next-action, human requests); playbook ready; pytest plugin assessment; round 20 decisions and CLI/pytest research; round 21 decisions and trial protocol; research supplement (enforcement and agent testing tools); round 22 (verb-cli future, default format); round 23 (version-control interface). Whether the parent filed each as beads has NOT been confirmed to me.

## Appendix L: candidate 10 and the harness lesson (round 25)

- A hard-coded vendor in the code base is a defect even when configuration only enables that vendor today: configuration limits, code does not. Check what the shelf already offers before designing: any-agent already defines the harness interface (README at the tag, `git show <tag>:packages/<pkg>/README.md` works offline in a local checkout); the leak was in the caller (`CodexHarness()`, raw Codex CLI flags in access.py) and in a raw-args field of the shelf API.
- Prompt storage: the owner prefers Python modules over text files (no resource-path I/O, encapsulated in the step); overrides come from configuration; feedback sections are typed and appended by the step.
- Structured-output schema flavors are per harness; a model library's default JSON schema may violate a vendor's strict profile; test the generated schema against the vendor profile with a snapshot.
- Measure start-up with `-X importtime` in an existing venv when a dependency's cost worries the owner: pydantic 2.14.1 imported in about 19 ms warm / 82 ms cold on Python 3.12 (one machine, models not defined).
- Unsupported state after an upgrade with no migration: report it as blocked with a generic repair prompt (topology, context) instead of writing migrations.

Pydantic verdict (Appendix L, research result): pydantic v2 at the edges with frozen, strict, extra=forbid; keep plain frozen dataclasses for hot or internal types; the strict-schema flavor is a post-pass per harness; v3 risk low if pinned; wheels for 3.15 unverified; msgspec fallback. Re-test the measured Codex schema profile against the current Codex before building the adapter.

## Appendix M: where decisions live (owner's thinking, round 26) and the decision register

- Problem: the review produced about 90 decisions; one ADR per decision (round 18) would be far too many. Owner: ADRs are meta decisions about **how we do things**, not **what we do**; what we do belongs in design documents ("a systematic thinking how a system should work").
- Structure (proposed, awaiting confirmation): `docs/design/system/<area>.md` (one per area; each states its decisions in a table, links the test or contract that enforces each, and is the single authority for the topic); ADRs only for meta decisions (docs structure, terminology rules, ratchet, no CI, trial protocol); CLAUDE.md/AGENTS.md for rules agents must follow (copied from the design docs); plans under `docs/design/<task-id>/plan.md` stay as history and update the system doc when their task lands; `docs/design/INDEX.md` lists every document with a status. This supersedes the round 18 decision "one ADR per decision". CLAUDE.md says plans belong at `docs/design/<task-id>/plan.md`: that rule stays, and the new convention needs a line in it.
- The register (`decision-register.md`) holds every decision with id, status (decided / proposed / open), and a proposed enforcing test; it is the seed of the system docs and of the index. Areas: process and enforcement; architecture; lifecycle and recovery; storage; tracker; version control and code host; steps and agents; config; CLI, messages and vocabulary; testing; open items.
- Method lesson: when decisions outgrow a record file, group them by area, give each an id and a status, and attach the enforcing test; then the document set answers "what did we decide, is it enforced, who owns the follow-up".
- Not yet grilled (findings exist, decisions do not): security (finding B), growth and retention (C), the rest of single-tenant assumptions (D), first run and doctor (E, N).

## Appendix N: docs organization for agentic repositories (Opus + Fable consults with web research, 2026-11-13)

- Both: the three-way split (system / ADR / rules) is right for **living authority** but incomplete; sort documents by **lifecycle**: living docs are edited, history docs are append-only. Add a **history tier** (task plans, trials, findings: about 90% of the files) that is never authority, and a **runbooks** tier. Many task folders are fine as long as they are not the entry point; they are reached by id.
- Layout (Fable's variant chosen as recommendation: `system/` beside `design/`, so authority is not buried among 60 task folders): `AGENTS.md`/`CLAUDE.md` (rules + decision ids + pointers, under 200 lines), `docs/INDEX.md` (generated from frontmatter), `docs/glossary.md` (current terms) and a retired-names file, `docs/system/<area>.md` (what, present tense, 11 areas, `open.md` for open items), `docs/adr/NNNN-*.md` (how we work, about 10), `docs/runbooks/` (first run, smoke, recovery), `docs/design/<task-id>/` (history, path unchanged), flat taskless files into `trials/` and `proposals/`.
- Rules: frontmatter `status`, `area`, `date`, `superseded_by` with a closed status set per tier; each decision id defined in exactly one file, others link; caps (system doc 400 lines, AGENTS.md 200); who edits (system: the landing task's agent in the same change as the code; ADR and rules: owner approval; plans: frozen after land except status marks; INDEX: generated only); on land the plan's as-built delta moves into the system doc and the plan is marked built; archiving is a status mark, never a delete or move.
- Agent discovery: AGENTS.md carries a 10-line doc map; keep rationale, decision tables, plans, glossary, history out of it; state each rule once and point to it, never copy (copies create two authorities).
- Checks in `just check` (native Python): every doc has a legal status; regenerated INDEX equals the committed one; relative links and anchors resolve; AGENTS.md and CLAUDE.md identical and within caps (no mirror test exists today; the files are identical at 111 lines each); every "enforced by" path exists; each decision id defined once.
- Migration (nothing deleted): add frontmatter everywhere (17 unmarked become `untriaged`, about 20 dead designs `withdrawn` or `superseded` in place); generate INDEX; seed system docs from the register and lift the 10 plan-only decisions; `git mv` only the flat files with links fixed; write the meta ADRs, split the glossary, change the plan rule in CLAUDE.md to "plans are history; system/ is authority".
- Prior art (fetched 2026-11-13 by the consultants): OpenSpec (live specs, per-change folders, dated archive), spec-kit, Kiro specs, Cline memory bank, Claude Code memory docs (keep CLAUDE.md under 200 lines), agents.md (nearest file wins), arc42, llms.txt. Not verified: spec-kit and Kiro exact paths; a "no mixing" rule in Diataxis; staleness linters.

## Appendix O: the owner's own standard already existed (round 28-29) and a lesson

- Discovery: the shelf package `blueprint` and its ADR 0017 ("Decisions are living ADRs; agents read a generated index") already define the knowledge layout the owner wanted: `CONTEXT.md` at the repo root is the glossary (shelf template `docs/agents/domain.md` overrides the Pocock skills' `GLOSSARY.md` convention and forbids running their setup skill over these files); `docs/adr/NNNN-slug.md` is one living file per decision topic with frontmatter (`id`, `title`, `statement` of at most 200 characters, `concerns`, `status`, `decided_by`, `updated`), rewritten in place when the decision changes with the old choice and the trigger in `## History`, never renumbered; `docs/adr/INDEX.md` is generated (`blueprint adr-index --write`), one line per decision in force, and the gate fails on a stale index; agents read only the index. Rejected there: immutable ADRs superseded by new ones (hundreds of files, reasons spread out) and agents reading every ADR. AGENTS.md carries a managed block (`<!-- blueprint:begin -->`): a read-when table of pointers to `docs/agents/{constitution,working-with-agents,gate,testing,architecture,health,issue-tracker,domain}.md`; CLAUDE.md is a symlink to AGENTS.md because Claude Code does not read AGENTS.md.
- This answers the owner's worries: ids do not drift (living ADRs keep their number); AGENTS.md holds pointers, not decisions or ids; "too many ADRs" is solved by the generated one-line index; one AGENTS.md file replaces CLAUDE.md (symlink).
- A read-only `blueprint check --repo . --summary` of the task-loop successor (repo stayed clean): knowledge 0 of 3 passing (no CONTEXT.md, ADR format, ADR index); agents 0 of 7 (CLAUDE.md is a copy of AGENTS.md, so it drifts); stack tool-pins: import-linter "2.15" not an exact version; gate.ci: no CI workflow, which conflicts with the owner's no-GitHub-Actions decision (blueprint accepts an override with a reason and an accepted ADR, its ADR 0022).
- Lesson: **before proposing a convention, search the owner's other repositories and the shelf for an existing standard** (grep for the generator, ADRs, templates). I spent two consults on a layout the owner had already standardized; the consults had no way to know. Put the pointer to the standard in the consult brief.
- Open: whether a thin `docs/system/<area>.md` is still needed beside living ADRs (mechanics, state machines, diagrams that cite ADR ids and never restate a decision).

## Appendix P: owner's rulings on the docs system (round 29)

- Blueprint is imperfect: it adds pre-commit steps and tools (for example a secret scanner over everything), which is bad taste. Adopt nothing from the shelf's blueprint beyond what we explicitly pick. I ran its read-only `check` once (repo unchanged) and read its sources; its gate opinions (CI present, tool-pin format, hooks) are not requirements for this repo.
- ADRs are for meta decisions (how we work), not for what the system does. What we decided about the system goes into **beefy but structured system docs, written for AI agents**: compressed, not thin; terse structured sections (model table, numbered rules with enforcing tests, typed outcomes, open items); reusing glossary terms; one authority per fact (sample: `sample-system-storage.md`).
- AGENTS.md: thin; pointers to files; no decision ids copied in; only very critical decisions may be cited, exactly, and then as a block generated from the source so it cannot drift; CLAUDE.md becomes a symlink (Claude Code does not read AGENTS.md; a copy drifts).
- Generated indexes are deterministic and regenerated; a tiny own generator (not blueprint) with `generate` and `check`. The check finds dangling references: a cited id or link that no longer resolves, an index that is not current, a generated block that differs from its source; ids and system-doc rows are never deleted (retire by status), so they cannot dangle.
- Open: glossary location (CONTEXT.md as in other repos, docs/glossary.md as now, or GLOSSARY.md as the Pocock skills default); generator home (shelf package vs this repo).

## Appendix Q - owner rulings, round 30 (2026-11-13)
- ADRs: living form (shelf ADR 0017). Rewritten in place, renamed or reworked, never supersession chains. History = git + a short section at the ADR bottom. Reason: a decision can be dropped then re-elected; chains make agents track state. Pristine list only.
- ADR count is a budget concern: even 20 may be too many. Index tokens per session worry the owner. OPEN, much later: hierarchical / domain / stage / point-of-view ADRs.
- ADR scope: meta decisions only. Product decisions live in system docs.
- Index generated per tier (adopted).
- System decisions in docs/system/<area>.md; plans/trials in history tier; runbooks own tier (adopted).
- Glossary stays docs/glossary.md; AGENTS.md says it is both context and glossary. No CONTEXT.md.
- CLAUDE.md: delete entirely, no symlink (owner: Claude reads AGENTS.md now). VERIFY once in a fresh session.
- Checks: a regenerator, not a separate docs test suite. Runs when docs change; reports problems.
- System docs: compressed for AI only. Owner asks for an existing standard to structure them (PRD-like). OPEN.
- Generator: own tiny shelf package (yes). Nothing from blueprint.
- Lesson: when the owner has a standard, adopt it with its reason; do not re-derive a competing one.

## Appendix R - docs format, delivery strategy, prototype (2026-11-13)
- RFC 2119 purged. Rules binary, present tense, no modal/hedge words (lint on rule/definition cells). Optional/wanted = tracker or "not designed, task X"; never a rule.
- Exceptions: scope inside the rule, exhaustive case tables, allowlisted waivers (task id, shrink-only). No exception lists.
- Decision tables beat Gherkin for completeness; table drives pytest parametrize via a small loader; a change to a cases/lifecycle table is a behaviour change (review + gate).
- Ontology (a2kay format, temporary own checker on any-frontmatter + any-markdown; a2kay adopted later): doc kinds area, lifecycle, workflow, external, persona, glossary(+terms), adr(lens work|requirements|design|code); inline YAML rows in frontmatter (6% over tables, no table parser). Owner: slightly more kinds than fewer, cut later. Trials to cut first: command, runbook, waivers, evidence.
- lifecycle = state machine of one noun (statechart); workflow = steps toward one goal across actors (BPMN-lite). Link: step.causes + step.event.
- Checks: changed-only (+ reverse refs), "skipped" no-op; --all never automatic, only if an agent decides. Defender cost ~20 ms/file: read count matters; cache only when measured.
- Prototype docscheck: 24 tests, 15 real docs, 87 ms skip / 484 ms one doc / 873 ms --all; 17 findings vs real code (rule 1 false in 14 modules; multi-writer tables; lock wait 1500 ms not 5000: my sample was wrong, I had not read the code).
- Delivery: design first (stage 0); factory builds in bounded chunks (--minutes), restart at drained boundaries; supervising AI session proposes restart, person approves; self-evolution = a follow-up task proposal, no auto gate; core (engine/storage) after drain command + version check + pinned previous-release runner. Gaps to file: drain command, version check on restart, session resume (tl-8bh9.3.4).
- Lesson: verify numbers against code before writing them in a doc (the 5 s lock).
