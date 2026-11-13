---
# Status: evidence; historical format specimen, not current system authority
read_when: before touching SQL, a store module, a transaction, factory.db or a row type
owns: ["src/taskloop/*_store.py", "src/taskloop/factory_schema.py"]
touches: [area/engine, external/tracker, external/git]
terms: [term/slice, term/store, term/Tx, term/reservation, term/slot, term/attempt, term/slot-release]
rules:
  - {id: 1, applies_to: "every module outside a slice's store module", holds: "issues no SQL and holds no sqlite connection; it calls typed use cases", probe: sql-outside-store}
  - {id: 2, applies_to: "every table", holds: "has exactly one writing module, derived from the path of the module that writes it", check: check/test_every_sql_write_has_its_one_owner, probe: one-writer-per-table}
  - {id: 3, applies_to: "a transition that crosses slices", holds: "runs in the starting slice inside one caller-passed [[term/Tx]]; the callee opens no transaction"}
  - {id: 4, applies_to: "an open write transaction", holds: "calls no Git, tracker, spawn, file or network and does not sleep; external work records intent, acts, then records its result"}
  - {id: 5, applies_to: "every [[term/reservation]] write and every [[term/slot-release]] write", holds: "is one guarded UPDATE with its precondition in the WHERE clause; no read precedes it"}
  - {id: 6, applies_to: "a write waiting for the single writer lock", holds: "yields to the cases in table lock after the writer-lock-wait limit"}
  - {id: 7, applies_to: "every row crossing a store boundary", holds: "is a frozen strict model mapped in the store module; callers index no tuple"}
  - {id: 8, applies_to: "factory.db at start", holds: "behaves as the cases in table start say; no backup, restore, file fallback or silent recovery exists"}
  - {id: 9, applies_to: "an upgrade that changes the schema", holds: "drains running attempts first, then discards the old factory.db; no old entry process writes the new schema"}
  - {id: 10, applies_to: "the dashboard", holds: "calls the same use cases as the CLI; read-only is a connection mode and not a second module"}
case_tables:
  - {name: lock, states: [acquired-in-time, timed-out]}
  - {name: start, states: [absent, intact, mismatched, corrupt]}
cases:
  - {table: lock, state: acquired-in-time, effect: "the write proceeds"}
  - {table: lock, state: timed-out, outcome: outcome/StoreBusy, effect: "nothing is written and the caller receives the outcome"}
  - {table: start, state: absent, effect: "opens empty; [[workflow/factory-start]] re-derives work from Git and the tracker"}
  - {table: start, state: intact, effect: "opens; unfinished attempts continue after liveness reconciliation"}
  - {table: start, state: mismatched, outcome: outcome/SchemaMismatch, effect: "fails fast with the message that factory.db is mismatched; nothing is written; [[runbook/factory-db-corrupt]] applies"}
  - {table: start, state: corrupt, outcome: outcome/Corrupt, effect: "fails fast with the message that factory.db is corrupt; nothing is written; a repair agent receives a blocked task with a repair prompt"}
outcomes:
  - {name: StoreBusy, handled_in: area/storage, source: "src/taskloop/attempt_store.py::StoreBusy"}
  - {name: StoreUnavailable, handled_in: area/storage, source: "src/taskloop/attempt_reads.py::StoreUnavailable"}
  - {name: SchemaMismatch, carries: [found, expected], handled_in: workflow/factory-start, source: "src/taskloop/factory_schema.py::SchemaMismatch"}
  - {name: Corrupt, handled_in: workflow/factory-start, source: "src/taskloop/factory_schema.py::Corrupt"}
limits:
  - {name: writer-lock-wait, source: "src/taskloop/attempt_store.py::REGISTRATION_BUSY_MS", value: 5000}
operations:
  - {name: refuse an incompatible schema, source: "src/taskloop/factory_schema.py::refusal", outcomes: [outcome/SchemaMismatch]}
evidence:
  - {artifact: "entry log of one attempt", path: "entry.log under the attempt's artifact folder", writer: area/engine, reader: [area/engine, persona/owner]}
not_designed:
  - {what: "retention of attempt evidence and grow-only tables: deletion only by a person-run operation", task: task/tl-unfiled-retention}
  - {what: "history growth: quick_check on first open, attempts() scanning all history, board rebuild every 2 s; measure first", task: task/tl-unfiled-history-growth}
---
