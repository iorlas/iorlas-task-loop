# System doc format: round 2

Marks: **[K]** = I know (read in the code or mechanical), **[B]** = I believe.

## 0. The shelf linter: what I found

**[K]** I searched `~/Workspaces/shelf` (main checkout only: `packages/`, `docs/`, `tools/`, `skills/`, `justfile`). There is no schema-driven front-matter markdown linter there. The design notes say the validator is `a2kay validate`, not yet shipped (`openspec/changes/blueprint-skill/design.md:468`). I did not search the `shelf-wt-*` worktrees or a2kay.

| piece | what it already does | missing for us |
|---|---|---|
| `packages/any-frontmatter` | reads and writes YAML frontmatter, one `FrontmatterError`, layout-independent content hash (`version_of_file`) | no schema, no validation |
| `packages/any-markdown` | parses `[[wikilinks]]` by CommonMark grammar (code excluded), `[[target\|label]]`, sections by heading slug | no target resolution, no table parsing |
| `packages/blueprint/src/blueprint/adr.py` | ADR check: hard-coded required fields, status enum, date pattern, generated `INDEX.md` with a stale check | not schema-driven; hand-rolled line parser; ADR only |
| `tools/changed.py` + `lint-changed` recipe | files changed against the merge-base matching globs; prints "skipped" and exits 0 when none; runs everything if a config file changed | marked shelf-only, consumers copy it; no reverse references |

So: reuse the two parsers and the changed-files pattern. The schema per kind, the id index, reference resolution and table checks are new code.

## 1. Gherkin versus decision table

| | decision table (state x event -> result) | Gherkin |
|---|---|---|
| completeness | **[K]** checkable: declared states x declared events = the cells that must exist | **[K]** none; a scenario is one example, and a missing one is invisible |
| overlap / contradiction | checkable: two rows matching one cell | not checkable |
| order of steps | weak | good |
| many dimensions | blows up; needs "any" rows, which need an overlap check | stays readable |
| cost | one row per case | 4 to 6 lines per case |

- **[K]** For completeness the table is strictly better. Not strictly better overall: it does not express order.
- **[B]** Order does not need Gherkin either. A workflow is a numbered step list (the sequence) plus one table (the cases). Gherkin, if used at all, belongs in tests, and this repo's tests are pytest functions.
- **[K]** The table is only as complete as the declared state list. The checker proves "no cell missing", not "no state forgotten".

## 2. Kinds, folders, schemas, references

**Kinds** (five documents, three row kinds):

| kind | declared by | holds |
|---|---|---|
| `area` | a file | owns table, rules, cases, outcomes |
| `workflow` | a file | actors, numbered steps, state x event table |
| `persona` | a file | a human or agent role and what it reaches |
| `external` | a file | a system outside the factory: facts it owns, the port, failures |
| `term` | a heading in `docs/glossary.md` | a definition (one file per term is too many files) |
| `rule`, `outcome`, `check` | a table row (`rule`, `outcome`) or a test marker / import-linter contract (`check`) | |

`step/...` is not a new kind **[B]**: a step is a glossary term and its code is an area. Add it only if steps get their own docs.

**Folders**: `docs/system/{area,workflow,persona,external}/<slug>.md`. This is a convention for globbing only. The checker reads `id` from frontmatter and never derives anything from the path.

**Ids**: `kind/slug`. Row ids are `rule/<area>.<n>`, `outcome/<Name>`.

**Reference syntax**: `[[kind/slug]]` in body text and table cells; bare `kind/slug` in frontmatter lists.

- **[K]** `any-markdown` already parses this form, and a2kay uses the same form, which is the seam.
- No labels inside tables (the `|` breaks the row).
- Resolution: build `id -> file` from all frontmatter ids, glossary headings, typed table rows and test markers. A reference whose id is not in that map fails. `task/<id>` is checked by pattern only, because the tracker is another owner and the checker does no IO beyond files.

**Frontmatter per kind** (pydantic models, `extra=forbid`; exporting JSON Schema later costs nothing):

| kind | fields |
|---|---|
| all | `id` (must start with the kind) |
| area | `read_when`, `owns` (path globs, each must match a file), `touches` (area, external) |
| workflow | `actors` (persona), `areas`, `externals`, `states`, `events` |
| persona | `nature` (human or agent), `reaches` (area, external) |
| external | `owns_facts`, `port` (code path, must exist), `used_by` (area) |

**Body**: fixed headings per kind, each a typed table (`Owns`, `Rules`, `Cases <name>`, `Outcomes`, `Not designed`). `Not designed` rows are `what | task`, and are never rules.

## 3. Mini example set

Content is illustrative; facts beyond CLAUDE.md and the storage sample are **[B]**.

```markdown
---
id: persona/owner
nature: human
reaches: [area/dashboard, external/tracker]
---
# owner
| can | through |
|---|---|
| answer a human request | [[area/dashboard]] |
| write the main checkout | directly; no agent does |
| deliberately discard factory.db | by hand; see [[rule/storage.8]] |
```

```markdown
---
id: external/tracker
owns_facts: [requirements, dependencies, questions, linked answers, discussion]
port: src/taskloop/tracker/port.py
used_by: [area/engine, area/human-requests]
---
# tracker
| id | applies to | holds |
|---|---|---|
| 1 | every task state change | goes through a typed tracker operation; a comment changes no state |
| 2 | every tracker call | happens outside a write transaction ([[rule/storage.4]]) |
```

```markdown
---
id: workflow/factory-start
actors: [persona/owner]
areas: [area/storage, area/engine, area/human-requests]
externals: [external/tracker]
states: [absent, intact, mismatched, corrupt]
events: [start]
---
# factory-start
## Steps
1. Open factory.db ([[rule/storage.8]]).
2. Act on the state below.
## Cases
| state | start |
|---|---|
| absent | create; re-derive work from Git and [[external/tracker]] |
| intact | reconcile liveness; continue unfinished attempts |
| mismatched | stop with [[outcome/SchemaMismatch]]; blocked, repair prompt |
| corrupt | stop with [[outcome/Corrupt]]; blocked, repair prompt |
```

The storage doc (section 5) links back to all three.

## 4. Incremental checking

**[B]** Do it in two layers, and build the second only when measured.

- **Outer gate (do now).** A `just` recipe copies the shelf pattern: list files changed against the merge-base under `docs/system/*`, `docs/glossary.md`, `tests/rules/*` and the checker's own source. Empty list: print "skipped" and exit before Python starts. That is the no-op.
- **Inner pass.** When anything changed, parse all system docs in memory. For under about 100 small files I expect well under a second; not measured.
- **Cache (only if the inner pass is measured slow).** One derived, gitignored JSON file: per path a content hash, declared ids, outgoing refs and last problems, plus a hash of the checker source. On a run, re-parse only paths whose hash differs, compute the set of ids added or removed, and re-check the changed docs plus the docs that reference an id in that set (a reverse lookup in the cached refs). Docs that reference an unchanged id are not re-read. A missing cache or a different checker hash means a full build with the same result, so it owns no state.
- `check-all` in CI always runs full and ignores the cache.

## 5. Storage: what to restore

| dropped item | decision | reason |
|---|---|---|
| request-row columns | not restored | one owner per fact: they belong in `area/human-requests`; storage links to it |
| "transactions are short" | not restored | no number, so no test; rule 4 (no external call, no sleep) is the enforceable form |
| rule 5's reason | restored as a prohibition | "no read-then-write" stops an agent refactoring the guard away |
| rule 11's shelf README pointer | not restored | the target is in another repo and cannot be resolved; the gate is self-contained |
| status, date | not restored | Git owns the date; a doc in `docs/system` is in force, and unfinished parts sit in `Not designed` |

```markdown
---
id: area/storage
read_when: SQL, a store module, a transaction, factory.db, a row type
owns: [src/taskloop/*/store.py]
touches: [area/engine, area/human-requests, area/dashboard, external/tracker]
---
# storage
## Owns
| owner | tables | readers |
|---|---|---|
| [[area/engine]] | attempt reservation slot execution verification slot_release | engine, status |
| each [[term/step]], its own store | checks_attempt check_result land_candidate setup_run published_branch | that step, status |
| [[area/human-requests]] | request rows | [[area/dashboard]] |

## Rules
| id | applies to | holds | check |
|---|---|---|---|
| 1 | every module outside a [[term/slice]]'s store.py | contains no SQL and no sqlite3.Connection; it calls typed use cases | [[check/sqlite-only-in-store]] |
| 2 | every table | has exactly one writing slice, derived from the writing module's path; an engine table has no step-specific column; a step writes no engine table | [[check/table-ownership]] |
| 3 | a transition that crosses slices | runs in the starting slice inside one caller-passed [[term/Tx]]; the callee opens no transaction | [[check/no-nested-tx]] |
| 4 | an open write transaction | contains no Git, [[external/tracker]], spawn, file or network call and no sleep; external work is: record intent (tx), act, record result (tx) | [[check/no-external-in-tx]] |
| 5 | every [[term/reserve]] and [[term/release]] write | is one guarded write (UPDATE ... WHERE precondition), explicit SQL in the store, named for the rule; no read-then-write | none |
| 6 | a write waiting for the single writer lock | Cases lock | none |
| 7 | every row crossing the store boundary | is a pydantic model (frozen, strict, extra=forbid) mapped in store.py by the shelf helper; callers index no tuple | none |
| 8 | factory.db at start | Cases start; no backup, restore, file fallback or silent recovery exists | none |
| 9 | an upgrade that changes the schema | drains running [[term/attempt]]s first, then discards the old DB; an old entry process writes nothing to the new schema | none |
| 10 | [[area/dashboard]] | calls the same use cases as the CLI; read-only is a connection mode, not a second module | none |
| 11 | every helper in sqlite-store (shelf) | is used by two or more slices | none |

## Cases lock
| lock acquired | result |
|---|---|
| within 5 s | the write proceeds |
| not within 5 s | [[outcome/StoreBusy]] |

## Cases start
| factory.db | result |
|---|---|
| absent or deliberately discarded | opens empty; [[workflow/factory-start]] re-derives work |
| intact | opens; unfinished work continues |
| mismatched | [[outcome/SchemaMismatch]], message "factory.db is mismatched"; nothing is written |
| corrupt | [[outcome/Corrupt]], message "factory.db is corrupt"; nothing is written |

## Outcomes
| id | carries | handled in |
|---|---|---|
| StoreBusy | | the calling slice's catalog |
| StoreUnavailable | | the calling slice's catalog |
| SchemaMismatch | found, expected | [[workflow/factory-start]]: blocked, repair prompt |
| Corrupt | | [[workflow/factory-start]]: blocked, repair prompt |
Raw sqlite text is detail only.

## Not designed
| what | task |
|---|---|
| StoreUnavailable at start | needs a task id |
| retention of attempt evidence and grow-only tables (deletion only by a person-run operation) | needs a task id |
| history growth: measure first | needs a task id |
```

**[B]** One reading I chose: a mismatch at start means an upgrade skipped rule 9, so it fails fast and is not discarded automatically.

## 6. Banned-word lint

Worth it. With typed tables it is the same thing as a schema pattern: one regex on the `holds` cell of changed docs, inside the pass that already runs, at no extra cost.
Limit it to modal and hedge words (must, should, may, could, usually, prefer, ideally, where possible).

## 7. Top 3 new risks

1. **A reference proves existence, not correct use.** `[[term/slice]]` in a rule passes even if the rule misuses the term, and two docs can both state the start behaviour (storage cases and the workflow) without the checker noticing. One-owner-per-fact stays a review matter.
2. **Kind and schema growth.** Five kinds are cheap; each new kind is a schema, fixed headings and table checks. Since the shelf has no generic linter, this is new code, and the pull is to build a small a2kay. Cap it: a new kind needs two real docs waiting for it.
3. **Stale green from the gate.** The outer gate's glob list is itself a fact: a renamed test folder or a rule marker in a file outside the globs is skipped silently, and a cache bug passes wrongly. Only the full CI run catches both, so a rename of an id also needs a tool, or it breaks many docs at once.
