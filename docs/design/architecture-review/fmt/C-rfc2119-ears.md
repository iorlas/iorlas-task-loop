Status: **evidence**. Historical architecture-review format/opinion specimen; its proposals are not adopted system authority.

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
