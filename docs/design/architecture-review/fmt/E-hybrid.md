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
