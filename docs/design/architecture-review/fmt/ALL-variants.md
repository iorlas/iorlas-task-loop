

=================== A-current ===================
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


=================== B-diataxis-reference ===================
# storage — reference
## Entities
- Store: per-slice module `store.py`; sole holder of sqlite3.Connection.
- Tx: caller-passed transaction handle; callee never opens one.
- factory.db: disposable local execution state.
## Ownership
- engine: attempt, reservation, slot, execution, verification, slot_release.
- step: own result tables only (checks_attempt, check_result, land_candidate, setup_run, published_branch).
- human_requests: request rows.
## Operations
- guarded_update(table, where=precondition) -> rows_changed | StoreBusy
- cross_slice_transition(Tx) -> runs in starting slice
- upgrade(schema) -> drain attempts, discard DB
## Constraints
- Transaction: no Git, tracker, spawn, file, network, sleep. Busy wait 5 s.
- Rows: frozen strict pydantic models.
- Readers: dashboard and CLI share use cases; read-only connection mode.
## Failure
StoreBusy | StoreUnavailable | SchemaMismatch(found, expected) | Corrupt: catalog entry per owning slice.


=================== C-rfc2119-ears ===================
# storage
R1 SQL and sqlite3.Connection MUST appear only in a slice's store.py. [sqlite-only-in-store]
R2 Each table MUST have exactly one writing slice. [table-ownership]
R3 WHEN a transition crosses slices, it MUST run in the starting slice inside one caller-passed Tx; the callee MUST NOT open a transaction. [no-nested-tx]
R4 WHILE a write transaction is open, it MUST NOT call Git, tracker, spawn, file, network or sleep; it MUST record intent, then act, then record result. [no-external-in-tx]
R5 Reservation and release MUST use guarded writes (UPDATE ... WHERE precondition), explicit in the store.
R6 IF the writer lock is not acquired within 5 s THEN the store MUST return StoreBusy.
R7 Rows MUST cross the store boundary as frozen strict pydantic models; callers MUST NOT index tuples.
R8 IF factory.db is deliberately discarded THEN work MUST be re-derived from Git and the tracker; IF intact after crash THEN unfinished work MUST continue. There MUST NOT be backup, restore or file fallback.
R9 A schema-changing upgrade MUST drain running attempts first and discard the old DB.
R10 Dashboard and CLI MUST share use cases; read-only MUST be a connection mode.
R11 sqlite-store SHOULD absorb needs seen twice.


=================== D-graph ===================
# storage
engine      -owns->       attempt reservation slot execution verification slot_release
step        -owns->       own result table(s)
human_requests -owns->    request rows
slice.store -only-holds-> sqlite3.Connection           [sqlite-only-in-store]
table       -has-one->    writing slice                [table-ownership]
step        -never-writes-> engine tables
txn         -never-calls-> git tracker spawn file network sleep   [no-external-in-tx]
txn         -pattern->    intent, act, result
cross-slice -runs-in->    starting slice, one Tx       [no-nested-tx]
store       -returns->    pydantic model (frozen strict)
store       -fails-with-> StoreBusy StoreUnavailable SchemaMismatch Corrupt -> owning slice catalog
factory.db  -is->         disposable -> rederive(Git, tracker); crash -> resume
upgrade     -drains->     attempts -> discard DB
dashboard   -uses->       same use cases as CLI; read-only conn
sqlite-store(shelf) -absorbs-> need seen twice


=================== E-hybrid ===================
---
area: storage
read_when: SQL, store, Tx, factory.db, row type
uses: slice store Tx attempt reservation slot step
touches: engine step human_requests dashboard
tests: sqlite-only-in-store table-ownership no-nested-tx no-external-in-tx
---
# storage
## Edges
engine -owns-> attempt reservation slot execution verification slot_release
step -owns-> own result tables | -never-writes-> engine tables
human_requests -owns-> request rows
## Rules
R1 sqlite3 MUST appear only in slice store.py. [sqlite-only-in-store]
R2 Table MUST have one writing slice. [table-ownership]
R3 Cross-slice transition MUST run in the starting slice in one caller Tx; callee MUST NOT open one. [no-nested-tx]
R4 Open write txn MUST NOT call git tracker spawn file network sleep; MUST do intent, act, result. [no-external-in-tx]
R5 Reservation/release MUST be guarded UPDATEs.
R6 Lock wait 5 s MUST yield StoreBusy.
R7 Rows MUST be frozen strict models.
R8 factory.db MUST be disposable; crash MUST resume; no backup/fallback.
R9 Upgrade MUST drain attempts, discard DB.
R10 dashboard MUST share CLI use cases; read-only = connection mode.
## Outcomes
StoreBusy StoreUnavailable SchemaMismatch(found,expected) Corrupt -> catalog (owning slice)
