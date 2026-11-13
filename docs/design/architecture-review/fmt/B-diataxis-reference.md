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
