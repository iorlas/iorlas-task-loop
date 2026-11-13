# Resolve the storage documentation findings

Task: `tl-8bh9.14.129`. Prepared 2026-11-13. Status: proposed; no implementation is authorized before the
owner's yes. This plan follows the owner delivery strategy relayed by architecture-review session
`local_16bd6c79`, and Appendices Q and R of the [playbook](../architecture-review/architecture-review-playbook.md).
The [prototype report](../architecture-review/docscheck-proto/REPORT.md) is evidence, not an installed gate.

## Result and boundary

Make every reported storage finding either corrected or covered by an explicit, shrink-only waiver linked to
a real remediation task. Correct the false limit and the misleading enforcement claim. Keep the target SQL
ownership rules; expose their current violations rather than weakening the rules to describe the violations.
Use waivers for the current runtime ownership gaps in this delivery. Consolidating storage is separate bounded
work, subject to the owner's core-change prerequisites: drain command, restart version check and a pinned
previous-release runner. This task does not refactor the engine or change its schema or execution behavior.

Only this plan is written in the planning step. The implementation steps below begin after the owner accepts
the plan. No tracker claims or task state are changed by preparing it. Local `bd show` could not resolve this
task or the supplied session-resume task, and storage/drain searches returned no tasks in this slot's tracker
snapshot. Use the supplied task as requirements; verify or file remediation tasks in the owning tracker during
implementation. Do not fabricate IDs, mutate a competing tracker, or treat pattern-valid links as proof of tasks.

## Current evidence

The source still has the report's fourteen SQL-issuing modules outside `*_store.py`:

| Modules | Finding |
|---|---|
| `admit.py`, `admit_chain.py`, `admit_rows.py` | Admission SQL outside stores |
| `attempt_entry.py`, `attempt_loads.py`, `attempt_reads.py` | Entry/read SQL outside stores |
| `check_admit.py`, `composition.py`, `land.py`, `land_check.py`, `launch.py` | Other SQL outside stores |
| `publish.py`, `slot_release.py`, `slots.py` | Publication/release/slot SQL outside stores |

The prototype's probe explicitly exempts `factory_schema.py`. Its schema SQL is distinct from per-table data
writes; the exemption must be stated in the rule's scope. That module also reads schema metadata, including
the newer mismatch diagnosis. Record that scope explicitly rather than implying all SQL there is DDL.
The current text scan counts thirteen calls in `attempt_reads.py`, versus twelve in the historical report.
Recompute findings and keys against the implementation revision; historical counts and message hashes are not
a current allowlist. Connection types and access also escape store modules; a SQL-call scan alone does not prove
the full rule that callers hold no SQLite connections.

`tests/rules/test_policy.py::WRITERS` currently assigns data writes as follows:

| Table | Writing modules, across all data-write verbs |
|---|---|
| `attempt` | `admit_rows.py`, `attempt_store.py` |
| `slot` | `admit_rows.py`, `slots.py` |
| `reservation` | `admit_rows.py`, `admit_chain.py`, `slot_release.py` |

`test_every_sql_write_has_its_one_owner` checks `(verb, table) -> module`; it does not require one module across
verbs. The prototype's writer probe reads that policy dictionary, not an independent inventory of source writes.
Its task references are accepted by pattern, and unused waivers are detected only on full checks. Neither
mechanism alone establishes real task ownership or a continuously shrinking allowlist.

`attempt_store.REGISTRATION_BUSY_MS` is **1500**. `composition._registration` applies it through
`PRAGMA busy_timeout` to the registration connection; its docstring says other writers retain the library's
5-second wait. The specimen's global 5000-ms limit attached to this registration constant is false. Correct the
value and its scope together; do not change the runtime timeout to match the sample.

The four existing waivers name three unresolved proposed symbols (`StoreBusy`, `SchemaMismatch`, `Corrupt`)
and the reservation writers. `StoreUnavailable` exists in `attempt_reads.py`; SQLite errors are currently
mapped there. `factory_schema.refusal` explains schema incompatibility in words and preserves the database.
There is no implemented corruption repair-agent path or drain command.

## Delivery steps after approval

### 1. Establish real owners and the exact baseline

In the owning task tracker, inspect existing tasks and reuse one only when its requirements cover the actual
remediation. Otherwise file bounded tasks through the tracker actor for SQL/connection containment, each of
the three table ownership consolidations, and the proposed storage-error behavior. A containment task can own
several module findings when its scope lists them explicitly. Link prerequisites for core changes; verify the
restart version-check work against the current code and `tl-8bh9.14.127` rather than assuming it is absent.
Drain and the previous-release runner remain separate prerequisite work, not additions to this implementation.

Resolve **all** `tl-unfiled-*` links in the storage specimen and waiver document. Besides the four waiver rows,
the storage specimen contains retention and history-growth placeholders: find or file those tasks as well.
Retain their descriptions as open work, with no retention deletion or performance redesign here. Record actual
returned IDs in the documents; do not insert example IDs or use this completed documentation task as the owner
of deferred runtime work. If the owning tracker is unavailable, leave implementation incomplete until those
links can be verified. Do not close remediation tasks while their waivers remain.

Inventory the checked-out source recursively, including reads, transaction/PRAGMA calls and connection exposure,
and separately inventory table data writes. Compare with the report and classify every difference before freezing
the initial waiver set. Keep schema initialization/metadata scope explicit. No wildcard module, table or finding
waiver is accepted. Newly discovered gaps receive their own disposition, never silent suppression.

### 2. Correct the storage specimens and descriptions

Use the existing prototype storage and waiver documents as the bounded correction surface:
`docs/design/architecture-review/docscheck-proto/docs/system/area/storage.md` and `docs/waivers.md` beneath the
same prototype root. Keep them labelled as specimens. Update the obsolete 5-second claim in
`docs/design/architecture-review/sample-system-storage.md` to distinguish registration from other writes.
Do not adopt the entire ontology, create a parallel authoritative system-doc tree, or install the prototype
runner as part of this task. Other historical format trials remain historical.

- Set the constant-backed registration wait to 1500 ms and scope the lock cases to registration. Describe any
  other wait only after verifying the owning library's configured value; never infer a global bound from this
  constant. Retain the existing runtime behavior.
- State rule 1's schema/metadata scope explicitly and expose the remaining SQL and connection violations with
  their exact waivers. Add module paths to the specimen's ownership coverage so changes to offending callers
  reach the relevant checks; its current `*_store.py` glob misses them.
- Keep one data-writing module per table as the target rule, distinct from schema creation. Describe the current
  test accurately as verb-level enforcement; link the new table-level ratchet when implemented.
- Keep proposed error behavior visibly proposed and task-linked. Preserve missing-symbol findings as named
  waivers until implemented or deliberately removed from the target design. Do not alias the three proposed
  symbols to unrelated current symbols just to make resolution pass, or present the repair-agent flow as built.
- Preserve intact-DB continuation after liveness reconciliation, schema-upgrade drain-before-discard, and
  `tl-8bh9.3.4` as deferred harness-session resume. Restart continuation does not prove session resume or
  relaunch of every phase. Match mismatch/recovery wording to current `factory_schema.refusal`: stopping rounds
  alone does not prove entries stopped; discard is deliberate, loses local progress, and follows verified drain.
  No invented drain command, automatic discard, backup/restore, compatibility reader or history reconstruction.

Preserve the report's original measured results. Add a dated correction/delivery section pointing to the new
inventory and validation rather than rewriting its historical 17-active/4-waived result as a fresh measurement.

### 3. Enforce the waiver boundary without changing runtime storage

Extend the focused policy coverage in `tests/rules/`, splitting out a small storage policy module to respect
file caps. Retain the existing verb/table guard and add an independent table-to-set-of-writing-modules check
derived from source. Exclude schema creation from data-writer counts explicitly. Do not derive observed writer
sets from `WRITERS`, since an edited policy map must not be able to conceal a second writer.

Use one machine-readable allowlist for these storage deviations, consumed by the focused policy checks and the
prototype's storage probes. Keep it with the bounded storage evidence under this task's design directory.
Each entry identifies the rule/finding, exact affected path or table, observed deviation, removal condition,
explanation and verified remediation task ID. Store SQL-site and connection-exposure scope precisely enough
that adding SQL inside an already waived module also fails. For multi-writer tables record the complete writer
set, not just its size. Do not duplicate independent allowlists in tests and docs.

The owner-approved initial set is the ceiling. Subsequent changes only remove entries or narrow their covered
sites/writers; a rename or changed finding key needs explicit mapping proving the scope shrank or stayed equal.
No automatic rebasing to newly observed findings. Reject new sites, a new writer even in an already waived table,
unexplained key changes, duplicate/blank/placeholder task links, and stale waivers after a violation disappears.
Use exact-scope equality to force removal or narrowing when source improves. Reconcile task existence/status
through the owning tracker during delivery; normal static checks stay offline and never scrape tracker output.

Keep the prototype's diagnostic keys/report format where possible. Recompute its finding keys after scoped
documentation changes and retain the task mapping. Apply unused-waiver detection only after checking its owning
scope completely, so an unrelated changed-only invocation does not incorrectly declare another waiver stale.
This is a storage correction and ratchet, not productionization of the archived checker or its environment.

## Verification and acceptance

Add meaningful pytest policy cases proving detection of a second module using a different verb on the same
table, a new writer in a waived table, SQL added inside an already waived module, connection exposure, and a
removed violation with a stale waiver. Also cover an unchanged allowed deviation, narrower coverage, the explicit
schema/metadata scope, duplicate/placeholder task links, and changed-only waiver scoping. Reuse existing source
inspection patterns and temporary source fixtures; import no application composition or baseline bootstrap.

Verify the corrected 1500-ms value against its constant and registration configuration, and inspect every task
link through the owning tracker. Run the focused storage policy tests with the declared installed Python 3.15+
environment after `just install`, using `uv run --frozen --no-sync python -I -m pytest ...`. Run the required
repository gates `just check` and `just test` as defined by the justfile; do not add whole-suite/live runs.
If the prototype can be exercised in a supported isolated environment, run focused specimen checks with the
repository path explicit and check the entire storage waiver scope for staleness. Its archived `run.sh` hard-codes
another checkout and Python 3.12/PYTHONPATH; do not use it to supply or validate successor runtime code. Record
unavailable checker verification honestly rather than reporting its historical run as current validation.

Acceptance requires a disposition for all seventeen reported active findings and all four existing waivers:
the limit is corrected; fourteen SQL-module findings, three multi-writer tables and three unresolved proposed
symbols are fixed or exactly waived with verified real task IDs. The misleading table-ownership test claim is
corrected and the ratchet detects growth. All storage/waiver placeholders are gone, including the two open-work
links. The documentation distinguishes current behavior from target behavior and records actual verification.
No runtime storage, schema, timeout, task execution, session-resume or upgrade behavior changes in this delivery.
