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
