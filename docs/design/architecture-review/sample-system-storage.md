---
area: storage
status: current
date: 2026-11-13
read_when: before touching SQL, a store module, a transaction, factory.db, or a row type
owns: src/taskloop/*/store.py, factory.db schema fragments, sqlite-store (shelf)
enforced_by: tests/rules/test_storage_policy.py, .importlinter (contract sqlite-only-in-store)
terms: slice, store, Tx, reserve, release, attempt, reservation, slot (glossary)
---
# storage

## Model
| thing | owner | tables | writes | reads |
|---|---|---|---|---|
| engine | engine/attempt, engine/slot | attempt, reservation, slot, execution, verification, slot_release | engine use cases only | engine, status |
| step result | the step's own store | checks_attempt, check_result, land_candidate, setup_run, published_branch | that step only | that step, status |
| human requests | human_requests/store | request rows (kind, facts, raw detail) | human_requests only | dashboard history |
Engine tables never hold step-specific columns; a step table never writes an engine table.

## Rules
1. SQL and `sqlite3.Connection` exist only in `store.py` of a slice. Others call typed use cases. [test: sqlite-only-in-store]
2. Each table has one writing slice. Table ownership is derived from the path of the module that writes it. [test: table-ownership]
3. A transition across slices runs in the starting slice, inside one caller-passed `Tx`; the callee never opens a transaction. [test: no-nested-tx]
4. A write transaction contains no Git, tracker, spawn, file or network call and no sleep. Pattern: record intent (tx), act, record result (tx). [test: no-external-in-tx]
5. Guarded writes (`UPDATE ... WHERE precondition`) carry the safety of reservation and release; they stay explicit SQL in the store, named for the rule.
6. One writer at a time (SQLite): transactions are short; waits up to 5 s, then a typed `StoreBusy` outcome.
7. Rows enter and leave as pydantic models (frozen, strict, extra=forbid); `store.py` maps row to model through the shelf helper; no tuple indexing in callers.
8. factory.db is disposable: a deliberate discard re-derives work from Git plus the tracker; an intact DB after a crash continues unfinished work. No backup, restore or file fallback.
9. A schema-changing upgrade drains running attempts first; old entry processes cannot write the new schema; the old DB is discarded.
10. The dashboard uses the same use cases as the CLI; read-only is a connection mode, not a second module.
11. `sqlite-store` (shelf) grows by absorbing needs seen twice (row mapping, `Tx`, guarded update); direction in its README.

## Outcomes (typed)
`StoreBusy`, `StoreUnavailable`, `SchemaMismatch(found, expected)`, `Corrupt` -> each has a catalog entry (sentence + next action) in the owning slice; raw sqlite text is attached as detail only.

## Open
- retention of attempt evidence and grow-only tables: deletion only by an explicit person-run operation, never by age.
- history growth: `quick_check` on first open, `attempts()` scans all history, board rebuild every 2 s: measure before designing.
- golden source: only when a second machine or a server tracker exists.
