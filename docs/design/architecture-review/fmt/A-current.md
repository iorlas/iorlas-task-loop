Status: **evidence**. Historical architecture-review format/opinion specimen; its proposals are not adopted system authority.

## Model
| thing | owner | tables | writes | reads |
|---|---|---|---|---|
| engine | engine/attempt, engine/slot | attempt, reservation, slot, execution, verification, slot_release | engine use cases only | engine, status |
| step result | the step's own store | checks_attempt, check_result, land_candidate, setup_run, published_branch | that step only | that step, status |
| human requests | human_requests/store | request rows | human_requests only | dashboard history |
## Rules
1. SQL and sqlite3.Connection exist only in store.py of a slice. Others call typed use cases. [test: sqlite-only-in-store]
2. Each table has one writing slice. [test: table-ownership]
3. A transition across slices runs in the starting slice, inside one caller-passed Tx; the callee never opens a transaction. [test: no-nested-tx]
4. A write transaction contains no Git, tracker, spawn, file or network call and no sleep. Pattern: record intent, act, record result. [test: no-external-in-tx]
5. Guarded writes (UPDATE ... WHERE precondition) carry the safety of reservation and release; explicit SQL in the store.
6. One writer at a time: transactions are short; wait up to 5 s, then StoreBusy.
7. Rows enter and leave as pydantic models (frozen, strict, extra=forbid); no tuple indexing in callers.
8. factory.db is disposable: deliberate discard re-derives work from Git plus the tracker; intact DB after crash continues unfinished work. No backup, restore or file fallback.
9. A schema-changing upgrade drains running attempts first; old DB is discarded.
10. The dashboard uses the same use cases as the CLI; read-only is a connection mode.
11. sqlite-store (shelf) grows by absorbing needs seen twice.
## Outcomes
StoreBusy, StoreUnavailable, SchemaMismatch(found, expected), Corrupt -> catalog entry in owning slice; raw sqlite text as detail only.
