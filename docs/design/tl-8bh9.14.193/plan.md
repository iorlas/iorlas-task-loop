# Depth

Large: the task requires a schema version change; the version bump, DDL guard test, and incompatible-database refusal form one cohesive schema-safety change. No owner decision is missing and no dependency is explicitly unlanded. Evidence budget: 20 model calls total.

## Size

Estimate: 9 changed files, including tests and this artifact; 3 new files (this plan, the store module and its schema tests); 3 independent behaviours; 55 model calls for one implement attempt.

1. **Versioned database replacement.** Acceptance: increment the current factory schema version from 25 to 26; an existing v25 database is refused before scheduling or writes, while a freshly initialized v26 database supports normal reads. Upgrades require draining under matching code before deliberate discard; there is no migration or automatic discard.
2. **DDL/version regression guard.** Acceptance: changing the effective `SCHEMA.ddl` at the pinned version makes a focused test fail. The committed expected SHA-256 digest is keyed by the schema version, so a new version needs its own explicit reviewed digest. Test the effective DDL, including interpolated enum values, rather than just the source text or table names.
3. **Incomplete same-version database refusal.** Acceptance: a database recording the current version but lacking `merge_operation`, or another required table, is refused as incompatible with a one-line explanation naming the missing table. CLI reads and rounds return `refused:schema`; rounds reach no lock, handler, scheduling, or retry/backoff. Direct drain opening also refuses before reconciliation or writes. Database contents, unfinished work and evidence remain intact.

The behaviours belong together: the guard prevents recurrence, the version bump establishes the replacement boundary, and structural validation handles misleading same-version metadata. No split or owner decision is required.

## Current evidence

At source commit `45ae179af556c39da55aa2a8e61e9babd716a5e0`, `factory_schema.SCHEMA.version` is already 25 and its DDL contains `merge_operation`. The reproduction's v21 describes the historical failure; implementing this task must advance the current version rather than restore 21 or reuse 25.

The pinned sqlite-store read-only opener checks `PRAGMA user_version` but does not check required tables. Its extra schema checks run only on writable opens and turn ordinary SQLite errors into an unavailable connection, so they do not supply the required typed refusal. No shelf change is needed: required factory tables and their diagnosis belong to the factory.

`cli_composition._open_ro` already translates `SchemaError` through `factory_schema.refusal`; `operations.require_database` turns it into `refused:schema`. `open_reads`, start/next/land and existing-database adoption share that guard. Dashboard board/task reads use `open_reads`. Rounds validate before acquiring their lock and again through `open_next`; `_transient` only converts a database-open failure to `unavailable:store`. `open_drain` has an independent read-only gate and a second version check on its existing-file writer. The current refusal explanation hides the underlying error when the version is readable, which would conceal a missing-table diagnosis.

No existing task plan or unfinished commit belonging to this task was found. The supplied glossary definitions suffice; no glossary additions are needed.

## Implementation

1. Advance `SCHEMA.version` to 26 and document that every DDL change requires a version bump, in addition to incompatible changes in persisted-state interpretation. Keep `steps={}`. Add a new `tests/steps/test_factory_schema.py` with a reviewed version-to-DDL-digest pin and a test comparing the digest of the exact UTF-8 effective DDL against the entry for `SCHEMA.version`. Changing whitespace conservatively also requires review. Do not compute the expected digest from the current DDL during the test, or silently replace the existing version's pin. No history reader or extra database metadata is needed.
2. Add new `src/taskloop/factory_store.py` as the shared owner of structural validation and the guarded read-only opener. Derive required table names from the existing `SCHEMA.ddl` by executing it in an isolated in-memory SQLite connection and querying its schema; cache only this immutable code-derived set. Compare it with the opened database's table metadata on every guarded open. This avoids a second hand-maintained table list, SQL text parsing, and workflow decisions based on SQLite error messages. Sort missing names for deterministic output. Raise `SchemaError` with a concise incompatibility diagnosis when required tables are absent; ordinary connection/read failures retain the existing unavailable handling. Always close the in-memory connection and close an opened database connection if validation fails.
3. Move the small guarded opener out of `cli_composition` into the new store module, retaining its version-error explanation and `None` result for an unreadable/missing database. Point `_read_only` at it. This keeps the CLI module bounded and applies the same operation to CLI, dashboard reads, rounds and existing-database adoption without adding guards to each use case. All structural inspection stays read-only.
4. Use the same guarded opener in `drain/composition.open_drain`. Validate required tables again on its `mode=rw` writer before constructing drain/reconciliation ports, retaining the existing version-race check and connection cleanup. Avoid double-rendering refusal messages: keep one rendering boundary for each failure path. Extend `factory_schema.refusal` so a readable, matching recorded version includes the structural error and explicitly says the database is incompatible. Keep the diagnosis on one line, retain the existing preservation/drain/discard guidance, and preserve version-mismatch wording relied on by current tests. No new outcome vocabulary is needed.
5. Extend existing CLI/restart/drain tests as described below. Preserve successful creation and compatible restart, and preserve the distinction between incompatibility and transient inability to open the database. The implementation changes the four source files above, the new schema test, `test_schema_words.py`, `test_factory_restart.py`, `test_drain.py`, and this plan: nine files total. Lower-level stores and entry/launcher protocols need no changes; the application opening gates reject incompatibility before those consumers run.

## Verification

- In the new schema test file, check the version/digest pin, successful structural validation of a fresh database, and refusal of current-version fixtures missing different required tables. Include a DDL mutation at the same version that fails the pinned digest comparison. Keep tests focused on the contract rather than every helper.
- Extend `test_schema_words.py` with current-version missing-table fixtures for the existing command matrix, including `step list` and existing-database adoption. Assert `refused:schema`, a one-line explanation naming the table, and preservation of database contents and artifact absence.
- Extend `test_factory_restart.py` for both human and JSON rounds output. Refuse missing tables before any lock, handler or round is reached; also exercise `one_round` so the refusal remains `refused:schema` through `_transient` rather than becoming retryable `unavailable:store`. Preserve surviving slot/reservation rows and retained evidence, including uncheckpointed state where relevant. Reuse the existing missing/unreadable/transient failure coverage.
- Extend `test_drain.py` to prove that a same-version incomplete database returns `Conclusion.REFUSED` with the missing-table explanation before reconciliation or drain writes. A fresh complete database still opens normally.
- Run focused tests through the installed successor environment if needed, using the permitted isolated pytest invocation after `just install`. Do not use live services or a historical factory runtime to manufacture fixtures; local SQLite fixtures suffice.
- After all implementation edits and focused verification, run the required gates once each, last: `just check 2>&1 | tail -60`, then `just test 2>&1 | tail -40`. Both must pass. This planning attempt does not run implementation gates.

## Read list

- `src/taskloop/factory_schema.py:28-79` — schema version, DDL construction and the missing-table reproduction target; the sole DDL producer.
- `src/taskloop/factory_schema.py:79-261` — remaining effective DDL whose tables and interpolated constraints the validation and digest must cover.
- `src/taskloop/factory_schema.py:346-376` — version check and refusal wording that currently omits same-version structural errors.
- `src/taskloop/cli_composition.py:93-142` — guarded opener, connection lifetime, read and start callers; integrate the new store module here.
- `src/taskloop/cli_composition.py:159-226` — next/round construction and the transient-failure conversion that must preserve schema refusals.
- `src/taskloop/cli_composition.py:255-305` — rounds guard ordering, lock, drain and handler boundaries.
- `src/taskloop/cli_composition.py:350-368` — existing-database adoption uses the same guard while absent databases may be initialized.
- `src/taskloop/cli_composition.py:371-398` — land's caller of the shared read-only gate.
- `src/taskloop/drain/composition.py:10-24` — schema/store imports to update for the shared opening operation.
- `src/taskloop/drain/composition.py:50-92` — direct drain reader/writer validation, refusal translation and cleanup.
- `src/taskloop/operations.py:276-283` — existing `SchemaError` to `refused:schema` translation; retain its contract.
- `src/taskloop/dash_composition.py:36-56` — dashboard consumers already share `open_reads`; no separate validation is needed.
- `src/taskloop/rounds.py:103-134` — whole-round schema refusals stop before the backoff path.
- `src/taskloop/composition.py:195-205` — database creation caller after the adoption guard, preserving ownership of initialization.
- `tests/steps/test_schema_words.py:23-97` — command matrix, existing version/refusal fixtures and adoption preservation assertions.
- `tests/cli/test_factory_restart.py:19-144` — restart output, early refusal, retained state/evidence and transient-open contracts to extend.
- `tests/steps/test_drain.py:1-50` — drain imports, database fixture and direct opening pattern for the new refusal coverage.
- `tests/rules/test_policy.py:13-60` — enforced file/function caps and forbidden escapes; keep the new modules bounded.
- `tests/rules/test_policy.py:64-81` — schema and drain table ownership that the change must preserve.
- `tests/rules/test_policy.py:125-151` — SQL write ownership enforcement; derive table metadata without duplicating DDL literals outside its owner.
