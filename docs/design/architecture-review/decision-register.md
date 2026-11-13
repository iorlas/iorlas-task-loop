# Decision register (architecture review of the task-loop successor, 2026-11-13)

Status: **evidence**. Historical register of owner decisions, proposals and open questions; those distinctions below
do not imply implementation. Current commands are in the [README](../../../README.md).

Status: **D** decided (owner said yes), **P** proposed (my recommendation, owner has not confirmed or only partly), **O** open (needs a decision or a design).
"Enforced by" is a proposal for the test, contract or gate that would hold the decision; "-" means nothing mechanical. Beads: the parent session files them; I have no confirmation of ids, so none are listed.
Where the decisions should live (proposal P, see section 12): `docs/design/system/<area>.md` (what the system does), ADRs only for meta decisions (how we work), CLAUDE.md/AGENTS.md for rules agents must follow.

## 1. Process, docs and enforcement (meta)
| id | decision | st | enforced by |
|---|---|---|---|
| M1 | A new term borrows GitHub's word first, else chains defined terms; options and rationale go to a human first; an existing word stays because the glossary defines it | D | constitution rule; glossary review |
| M2 | Glossary diet in two stages: docs and rename map first, then one code rename per term group (hard cuts, no compatibility) | D | - |
| M3 | Constitution additions mirrored in CLAUDE.md and AGENTS.md (names, closed vocabularies, adapters own backend text, pydantic at edges, drain before upgrade, outbox, vertical layout, test impact) | D | mirror test (files identical) |
| M4 | Enforce by ratchet: a new contract lists today's violations as known exceptions; the list only shrinks | D | import-linter `ignore_imports` with unmatched-ignore alerting |
| M5 | No GitHub Actions or other CI for now; gates run through `just check`, the prek hook and the factory's checks step | D | - |
| M6 | Trial plugins one at a time, exact pin, measure test time before and after, keep a trial log, drop if no win | D | trial log |
| M7 | Keep the playbook growing: append lessons after every round | D | - |
| M8 | Docs (owner, round 29: adopt nothing from blueprint beyond what we pick): `docs/system/<area>.md` are beefy but compressed, agent-oriented, structured, reusing glossary terms (the decisions of the register live there); ADRs only for meta decisions (living, rewritten in place, generated one-line index); AGENTS.md thin with pointers and few critical rules generated from their source, CLAUDE.md a symlink; history stays in `docs/design/<task-id>/` with status marks; a tiny own generator builds the indexes and checks dangling references | P | generator `check` in `just check` |
| M9 | Every mechanically enforceable rule names its test or contract in the design doc that states it | P | docs index test |

## 2. Architecture
| id | decision | st | enforced by |
|---|---|---|---|
| A1 | Vertical slices: a slice is a folder named for one noun owning one fact (use-case modules, `store.py`, `api.py` as the only public door), two levels deep | D | generated import-linter contracts (protected `api`) |
| A2 | plan and implement are thin step folders (rules, prompt, agent); checks and land own state | D | layout test |
| A3 | Layers: cli, dash, rounds, compose above steps above engine (attempt, slot, flow) and tracker, above the kernel | D | import-linter layers |
| A4 | Steps implement an engine-owned `Step` protocol; they never import each other | D | import-linter independence |
| A5 | A flow table (data, in code) maps (step, outcome) to next step, repeat, wait, manual gate or done; rework is a backward edge (new attempt of the earlier step with the failure report; default failed check or review goes to implement; plan only on `plan_wrong`; cap per task then `blocked`) | D | totality test over every (step, outcome) |
| A6 | The flow stays in code until a second flow exists; then YAML cites steps by name with when/how/parameters | D | - |
| A7 | The engine owns attempt, reservation and slot tables; steps own result tables and give guard predicates on the same connection | D | table-ownership test by path |
| A8 | Migration order: kernel and contracts in report mode, per-slice DDL and sqlite behind stores, steps registry to the root and split `operations`, break land to checks through a port, move folders; engine: slot release, then checks as a step, then land | D | ratchet shrinks |
| A9 | One composition root per process, plain constructor calls, no logic; no registry or `include_router` machinery; a per-slice build function only when construction outgrows a few lines | D | root-only imports of concrete adapters |
| A10 | The shared kernel holds only ids, `Tx` and outcome types; the rest moves to its one user | D | fan-in budget |
| A11 | Tests mirror folders; a use case's test imports only its slice and the kernel | D | import-linter on tests |
| A12 | Human requests are their own slice behind a port that steps call; the three request kinds are needs-info, review-requested, blocked | D | - |
| A13 | Layer order inside the human-requests slice and where status is assembled (compose) | P | import-linter |

## 3. Attempt lifecycle, scheduler and recovery
| id | decision | st | enforced by |
|---|---|---|---|
| L1 | admission becomes reserve; its release is release; `tl step start` = reserve + spawn | D | rename map |
| L2 | first attempt / retry attempt (advance, relaunch, resume dropped); keep `dispatch` as the once-only permit | D | - |
| L3 | Idempotency A (one routine), B (AlreadyX outcomes), C (adopt "claimed by us, no attempt") | D | contract tests |
| L4 | External actions: intent, act, record (transactional outbox with reconciliation); never inside a write transaction; no two-phase commit | D | AST test plus runtime fake-port check |
| L5 | Scheduler terms: tick, reconcile, backoff, wake; `tl tick [--every N]`; drop move and settle | D | - |
| L6 | One detached entry process per attempt is kept and documented; measure its start-up with pydantic in | D | start-up measure |
| L7 | A schema-changing upgrade drains running attempts first; the old database is discarded | D | - |
| L8 | Restart must continue unfinished work: record a process identity before the spawn so reconciliation can find it (finding A) | P | crash table test |
| L9 | Unexpected or unsafe state: `blocked` with context and a generic copyable repair prompt, optionally a repair agent; known states keep deterministic reconciliation | D | - |
| L10 | Crash test: one table-driven test (crash point x state) in the engine slice, run on engine change and at land; measure cost first | D | the test |
| L11 | Known state = the typed state machine names it and a recorded identity proves the next step is safe; anything else is blocked with a repair prompt | D | - |

## 4. Storage
| id | decision | st | enforced by |
|---|---|---|---|
| S1 | SQL and `sqlite3.Connection` only in `store.py`; two layers per slice (service, store with named typed SQL); no repository interface | D | import-linter plus ruff per-file banned-api |
| S2 | A cross-slice transition runs in the starting slice with a caller-passed `Tx` | D | - |
| S3 | The dashboard reads and writes through the same transitions; read-only is a connection mode; transactions stay short (one writer) | D | - |
| S4 | `sqlite-store` grows into a real DB library/ORM by absorbing needs seen twice; the row-to-model helper is written in the shelf; direction text in its README | D | README |
| S5 | factory.db stays disposable (2026-11-08 rule); revisit a golden source only when a second machine or a server tracker exists | D | - |
| S6 | Fix growth and speed: attempts evidence retention, grow-only tables, `quick_check` per open, `attempts()` scans, board rebuild every 2 s, missing index on `attempt(repo_id)` | P | perf tests |
| S7 | Pydantic v2 at the edges (frozen, strict, extra=forbid; lax per field for database and YAML); plain frozen dataclasses for hot types; msgspec is the fallback; measure on 3.15 | D (fit pending measure) | - |

## 5. Tracker
| id | decision | st | enforced by |
|---|---|---|---|
| T1 | Local beads is always the claim store; Jira and GitHub Issues are sources and sinks | D | - |
| T2 | One `Tracker` module replaces ReadyRows, TrackerClaims, TrackerHolds; read-only type for the dashboard | D | - |
| T3 | Generic outcome classes; unexpected failures raise `TrackerFault`; backend text only in the adapter, which supplies the explanation | D | contract suite over fake and real adapter; no `bd` outside the adapter |
| T4 | `adapter` column stays; actor default `taskloop`, configurable | D | - |
| T5 | Pickup rule: all listed conditions hold; label `auto` default; assignee optional; an empty rule is refused | D | - |
| T6 | `tl task import <ref>` with a source adapter; sink is an action-item comment; manual `tl task refresh`; one factory per repo | D | - |
| T7 | `tracker.gone()` text matching moves into the adapter | D | AST test (no text parsing for control) |

## 6. Version control and code host
| id | decision | st | enforced by |
|---|---|---|---|
| V1 | Git only for now; the interface is in domain verbs (record work, make it reviewable, land, read state); a second system (Anthropic's Scion is internal) is not now | D | - |
| V2 | All Git mechanics move into `git-porcelain` (typed worktree state, `.git` pointer, trailers via Git's structured output, hardened env, composite operations); task-loop parses no Git output | D | AST test (no parsing of VCS output) |
| V3 | One `vcs` slice owns branch name, trailer names, squash fields, identity, remote; every other module asks it | D | - |
| V4 | Remote, branch prefix, identity from the config tiers (defaults origin, `task/`, `task-loop@localhost`); land accepts any profile target | D | - |
| V5 | The tool name appears only in its adapter; commit, branch, merge stay because the glossary defines them | D | import-linter on `git_porcelain` plus AST test on the word |
| V6 | Code host (pull requests, reviews, merge) is a separate interface from the VCS; adapters GitHub, a fake, none; the person merges | D | - |
| V7 | Land mode `push` or `pr` in the profile; PR comments come back as a retry attempt | D | - |
| V8 | The `git-porcelain` fake is the test surface; real-Git tests move into git-porcelain as its contract suite | D | - |

## 7. Steps, agents and workflow
| id | decision | st | enforced by |
|---|---|---|---|
| G1 | No hard-coded harness: any-agent's `Harness` protocol is used; config enables only Codex now; selection and priority from config | D | AST test (no harness class named outside its adapter) |
| G2 | A typed access policy replaces raw Codex CLI flags; harness adapters translate it (upgrade any-agent too) | P | - |
| G3 | Per-step agent entries (harness, model, effort, enabled, priority) in the config tiers; CLI flags override per run | D | - |
| G4 | Prompts are Python modules in the step's folder (typed templates), overridable through configuration; feedback sections typed and appended by the step; snapshot-tested | D | snapshot tests |
| G5 | Answer schemas come from pydantic models; the JSON-schema flavor is per harness (post-pass); re-test the Codex strict profile first | D (profile to re-test) | schema snapshot per harness |
| G6 | Each step has a parameter model (prompt name, agent, model, effort, caps) feeding CLI flags and the YAML | D | - |
| G7 | After an upgrade a dropped step type or schema is reported as `blocked` with a repair prompt; no migration | D | - |

## 8. Config
| id | decision | st | enforced by |
|---|---|---|---|
| C1 | Three tiers: repository profile (Git, shared), global machine config, `.local` file in the repo; anything that decides what is verified or landed comes only from the Git profile | D | test |
| C2 | Policy numbers (retry limits, lease, backoff, deadline cap) become named settings; mechanism constants get one owner module per slice | D | repeated-literal test |

## 9. CLI, output, messages and vocabulary
| id | decision | st | enforced by |
|---|---|---|---|
| U1 | verb-cli (shelf) is the CLI library and grows: registry with dynamic subparsers, flags from typed models, output layer, exit-code policy from outcome class, structured error surface, `--format`/`--config`, test helpers; rename to `any-cli` (no consumer outside the shelf found); no Typer, click, cappa | D | - |
| U2 | Output formats: JSON for nested, TSV for tables, text for humans; YAML only for human-authored files; default adapts (not a terminal means machine format chosen by shape; `--format` overrides) | D | - |
| U3 | Outcomes are typed values; no parsing of strings into pieces (no regex, startswith, split) except as JSON or YAML | D | AST test |
| U4 | Each slice owns a message catalog keyed by its outcome enum (sentence and next action); the three guide modules merge into catalogs | D | completeness test over the enum |
| U5 | One command table in the CLI; messages build commands from it | D | parser test |
| U6 | Raw errors and tracebacks are attached as detail under a typed statement; never inside the sentence; failures are also recorded as history (rows) and a log line | D | - |
| U7 | Closed vocabularies are `StrEnum`, one definition in the owning slice, one codec to storage text | D | AST test (enum `.value` only in codecs) |
| U8 | `printable.py` moves to the shelf as the one edge function for agent and person text | D | - |

## 10. Testing
| id | decision | st | enforced by |
|---|---|---|---|
| X1 | Core pytest features by default: `parametrize` with `pytest.param(id=)` and pytest 9 `subtests`; table tests welcome; strings only at edges so each codec is tested once | D | - |
| X2 | Suites in tiers: fast per slice, marked adapter contracts, marked real Git/process, CLI smoke | D | markers |
| X3 | Plugins: timeout (pin 2.4.0), socket, xdist yes; hypothesis only for 1-2 state machines with a cheap profile; syrupy for API, CLI JSON, schema snapshots; randomly ad hoc; trial pytest-impacted, pytest-check, durations, deadfixtures | D | trial log |
| X4 | Semantic fakes, no mock library; weak-test checks in our policy AST test | D | AST test |
| X5 | Trial diff-cover (changed lines covered) and fermut (mutation on changed lines) | P | - |

## 11. Open or unresolved
| id | item |
|---|---|
| O1 | Whether factory.db may become a golden source (S5) |
| O2 | Name of verb-cli (`any-cli`); no consumer outside the shelf found |
| O3 | Where the line between known and repair-agent states sits (L11) |
| O4 | Security: profile checks run on the host with HOME and network from the commit under test; logs served by the dashboard without auth; default umask on evidence files (finding B) |
| O5 | Growth: retention of attempt evidence and grow-only tables; cache cleanup (finding C) |
| O6 | Single-tenant assumptions beyond Git (tracker actor, profile filename) (finding D) |
| O7 | First-run documentation and a doctor command (findings E, N) |
| O8 | Pydantic start-up on 3.15 and cp315 wheels; a2kay once moved away from pydantic for load time (reason not found in commit messages) |

## 12. Where these should live (proposal)
- `docs/design/system/<area>.md`, one per area above (architecture, lifecycle and recovery, storage, tracker, vcs and code host, human requests, steps and agents, config, cli and messages, testing and enforcement, security and lifecycle): each states the decisions of its table, links the enforcing test, and is the single authority for its topic. A plan under `docs/design/<task-id>/plan.md` is history; when its task lands it updates the system doc.
- ADRs: only meta decisions (docs structure, terminology rules, ratchet, no CI, trial protocol).
- CLAUDE.md/AGENTS.md: rules agents must follow, copied from the design docs.
- `docs/design/INDEX.md` lists every document with a status.
