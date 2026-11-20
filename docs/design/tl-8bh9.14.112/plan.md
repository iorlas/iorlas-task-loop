# Canonical command conclusions and an ID port

Task: `tl-8bh9.14.112`. Prepared 2026-11-14 against `99655d38`.
Status: implemented; validation and handoff recorded below.

## Accepted scope

Implement only the ID port and the canonical command conclusions, within **90
changed files total**, including tests and this plan. The coordinator's final
2026-11-14 scope decision supersedes the original architecture census. Step and
claim vocabularies belong to separate follow-up tasks; do not begin either
migration or file tasks from this sandbox. Record their handoff below.

Use the existing `pydantic==2.14.3` at validation edges. It is already pinned in
`pyproject.toml` and `uv.lock`; Python 3.15 installation/import was confirmed by
PR 765. Add, install or update no dependency. Keep those manifests unchanged.

The broad Literal/set/comparison migration, other result vocabularies, and the
repeated database-unavailable message are outside this bounded implementation.
Preserve existing behavior, storage words, public output, transactional fences,
reconciliation, and held-task behavior. Introduce no glossary terms or workflow.

The plan step changed only this document. The implementation is recorded in
As built below.

## Current evidence and retained work

- The task plan did not exist, and the managed task worktree was clean.
- `check_store.Conclusion` defines seven command conclusions; the independent
  `setup_store.Conclusion` omits `undefined`. Both also repeat their strings in
  `CONCLUSIONS`. `checks` and `environment` consume the respective definitions.
- `setup_run` and `check_result` SQL constraints repeat those allowed values.
  Aggregate `checks_attempt` conclusions (`Outcome`) and drain's `Conclusion`
  represent different operations and remain owned by their existing slices.
- Command-result consumers include checks, setup, release/reconciliation, land,
  failed-check repeats, and CLI/dashboard data and rendering. Follow the actual
  `SetupRow` and `ResultRow` import closure when changing those types.
- Direct ID minting currently occurs in eight modules: `admit`, `admit_chain`,
  `check_admit`, `check_repeat/repair`, `repeat`, `land_check`, `agents/launch`,
  and `drain/store` (two admission classes share `admit_chain`). The original
  census predates some of these changes.
- Attempt, candidate and drain-action IDs use `uuid4().hex`; dispatch tokens
  use `secrets.token_hex(16)`. Ordinary repeat feedback uses `token_hex(8)`;
  failed-check feedback uses `token_hex(16)`. Agent launch supplies a hyphenated
  UUID session string. Keep every representation and entropy source.
- Branch history contains no saved WIP for this task. The WIP trailer within
  `78696b90` belongs to the already integrated per-step agent settings task
  `.160`; its current settings/launch behavior must be retained. The earlier
  86-file attempt described in the task is context, not an implementation
  result available on this branch.

Required context read: `AGENTS.md`, the successor foundation plan
`docs/design/tl-8bh9.8.7/plan.md`, `docs/glossary.md`, and `justfile`.

## Canonical command conclusions

1. Introduce one small, dependency-light module for a stdlib `StrEnum` named
   `CommandConclusion`. Its seven members retain, in current check-store order,
   `passed`, `failed`, `timed_out`, `lingering`, `dirty`, `undefined`, and
   `interrupted`. Delete both old Literal definitions and their enumerated
   string lists. Consumers import the canonical type directly; add no aliases
   or compatibility readers.
2. Give this vocabulary one edge codec. Use pydantic v2 validation for stored
   values, with explicit optional handling for unfinished commands. Reject
   unknown words and invalid input types; preserve the owning store's existing
   `StoreUnavailable` explanation on malformed rows. Serialize through this
   codec to the same string values at SQL, JSON and display boundaries. Keep
   pydantic out of application decisions; do not JSON-roundtrip in-process
   values or migrate unrelated row models.
3. Apply `CommandConclusion` to setup and individual check rows, sink protocols,
   writer inputs, execution judgments, and their consumers. Decisions and
   policy subsets use enum members, with strings confined to storage and
   presentation. Keep aggregate checks-attempt outcomes separate. Where a
   read model or text formatter carries a command conclusion, retain the enum
   until its output boundary, including failed-check feedback and land reads.
4. Preserve these context-specific rules; a common vocabulary does not merge
   the operations' policies:

   | Context | Rule to retain |
   | --- | --- |
   | Setup | `undefined` is invalid; the other six members are accepted. |
   | Setup failure count | Count failed, timed out, lingering and dirty; interruption does not count as setup's fault. |
   | Setup unsettled process | An unfinished, lingering or timed-out setup retains its process for liveness checks. |
   | Individual check unsettled process | Also retain an interrupted check's process. |
   | Check block | Passed, failed, timed out and undefined are terminal; lingering and dirty stop the block. Preserve interruption/relaunch behavior. |
   | Check writes | The dedicated undefined operation alone writes undefined; ordinary finish rejects it. |

5. Derive the two SQL allowed-value lists from the enum and setup's exclusion
   policy rather than repeating their strings. Preserve the exact existing
   list ordering and resulting constraints. This change needs no schema version
   bump: accepted stored values and their meaning stay identical. Compare the
   generated constraints with the current DDL; introduce no migration or DB
   discard requirement. Existing SQL predicates referring to a particular
   command conclusion must use its canonical encoded value.

## ID port

1. Add a narrow typed port for a fresh hexadecimal ID, a fresh session UUID
   string, and a cryptographic hexadecimal token with an explicit byte count.
   Keep it independent of trackers, SQLite and the vocabulary codec. Existing
   `AttemptKey` construction and reservation-generation calculation stay with
   their owning operations.
2. Implement the port in one native adapter using stdlib `uuid4` and `secrets`.
   Only that adapter may mint these values in production source. Construct and
   pass it from the existing process composition roots; application operations
   and stores receive it explicitly, without hidden production defaults.
3. Route all current minting through the port, including fresh admission,
   advance/repeat admission, failed-check repair, both land-candidate paths,
   feedback delimiters, agent launch, and drain-action authorization. Update
   nested `DrainStore` construction as well as top-level composition. Do not
   change any drain vocabulary or behavior while injecting its ID source.
4. Mint once when the existing operation creates a new identity. Reconciliation
   of persisted work keeps its recorded identity; relaunch never substitutes
   a new attempt ID or token. Maintain fresh session creation at the existing
   agent-launch boundary. Preserve transaction/outbox ordering and claim,
   reservation and generation fences.
5. Use a small deterministic semantic fake in affected test fixtures. Tests
   supply IDs through the port rather than monkeypatching randomness in each
   module. Do not rewrite unrelated tests or existing shelf fakes.

## Implementation boundary and sequence

Start with the canonical type/codec and the ID port/adapter. Thread the port
through existing composition and the eight minting modules, then migrate command
conclusion producers, stores and their real consumers. Update only impacted
tests/fixtures and the narrow architecture contracts. No broad formatting,
package relocation, new service layer or unrelated vocabulary conversion.

Track the complete changed-file set during implementation. The previous
86-file result is a sizing reference, not permission to exceed 90 on this newer
base. Reserve room for the plan and meaningful tests. If these two authorized
parts cannot fit, report the concrete boundary with evidence; do not start
step/claim work or silently trim necessary callers/tests.

Respect 400 source lines per file, 80 per function and 800 per test file. Use
existing owning Git/process/agent/lock APIs and pytest functions. Add no `Any`,
casts, ignore escapes, subprocess usage or baseline imports.

## Acceptance and focused verification

- There is one command-conclusion enum and one codec. Setup rejects undefined;
  malformed persisted values retain their typed failure and useful explanation.
  In-memory rows/results contain enum members, so tests must verify their types
  rather than depending on `StrEnum` equality with strings.
- Focused behavior tests preserve setup failure accounting, setup reuse,
  interrupted/unsettled process handling, check-block stopping/terminal rules,
  undefined writes, release safety and land/failed-check consumption. SQL and
  JSON/text still contain the exact existing words, including `None` for an
  unfinished command. Test representative externally visible serialization.
- Deterministic ID tests exercise admission, advance/repeat, failed-check
  repair, both land paths, feedback, agent session launch and drain actions.
  Assert that the supplied IDs reach their stored/evidence/session uses and
  that reconciliation reuses the existing key. Preserve token lengths and
  UUID formatting without adding statistical randomness tests.
- Extend an existing policy test, or add a focused architecture contract, so
  production `uuid`/`secrets` minting belongs solely to the adapter. Guard the
  single command-conclusion definition without banning unrelated Literals or
  converting other vocabularies. No test per private helper.

Use the already provisioned, installed successor package on Python 3.15 with
`uv run --frozen --no-sync python -I -m pytest -q` and explicit affected test
files. Start with `test_admit.py`, `test_admit_chain.py`, `test_check_admit.py`,
`test_repeat.py`, `test_check_repeat.py`, `test_agent_launch.py`,
`test_environment.py`, `test_check_store.py`, `test_checks.py`, relevant
release/land/drain tests, and the affected rule tests. Select any additional
in-process CLI/dashboard-read tests by the changed import closure. Do not run
socket-dependent dashboard-server tests or whole-suite/live/real tests.

The repository gates are `just check` and `just test`. The current recipes
depend on `install`, and `just test` selects whole test directories. In this
offline attempt, the explicit no-install and focused-test instructions take
precedence: run available lint/type/import checks against the provisioned
environment and the focused pytest commands without syncing dependencies.
Record exact commands and results, and report unrun aggregate gates accurately;
do not modify the justfile or chase the known socket restriction.

## As built

Implemented in **90 files**, including this plan and two new source modules.
No test files were added. No dependency, manifest, lockfile, schema version,
step vocabulary or claim vocabulary was changed.

- `command_conclusion.py` contains the single seven-member `CommandConclusion`,
  its pydantic edge decoder and scalar encoder, and setup's derived allowed
  subset. It has no factory dependencies. Setup/check rows and command judgments
  retain enum members; the consumers encode them at SQL, JSON and text edges.
  Aggregate checks-attempt and drain conclusions retain their existing meanings.
- `ids.py` contains the small `Ids` protocol and the sole native minting adapter.
  Admissions, repeat feedback, failed-check repair, both land candidate paths,
  agent sessions and drain authorizations receive the port explicitly. Process
  composition supplies the adapter; there are no production defaults. The
  original UUID representations and 8-/16-byte token requests are retained.
- Drain's pending-action query is one owning reader shared by registration fences
  and `DrainStore`. Read-only callers no longer construct a drain writer merely
  to read pending actions. ID injection follows the external-action use cases
  rather than every read-only store; transactional fences and outbox records
  remain intact.
- The failed-check evidence model uses the canonical enum and still accepts only
  a failed command. Land summaries keep command enums until rendering. Hold's
  text-only presentation fields are encoded when constructed.
- Deterministic tests cover fresh/advance/check/repeat admission, feedback token
  byte counts, failed-check repair and restart reuse, both candidate paths,
  harness sessions and drain action adoption. Enum identity, invalid input types,
  malformed stored values, setup's exclusion/failure policy, ordinary-finish
  exclusion, JSON scalar output and the sole minting adapter are covered.
- The gates exposed a pre-existing dashboard-read assertion of the removed
  `Run.summary`; it now asserts the existing `Run.access` field.

Validation (Python 3.15, provisioned offline environment):

- `just check`: passed lint, types (0 errors), and all 9 import contracts.
- `just test`: passed, 3,461 tests. The active task explicitly requires both
  `.task-loop.json` commands, superseding this plan's earlier focused-only gate
  instruction. Their `install` recipe rebuilt only the current project from
  local files; no dependency was added, upgraded or fetched.
- `uv run --frozen --no-sync python -I -m pytest -q` with
  `tests/steps/test_admit.py`, `test_admit_chain.py`, `test_check_admit.py`,
  `test_agent_launch.py`, `test_check_store.py`, `test_setup_store.py`,
  `test_drain.py`, `test_repeat.py`, `test_check_repeat.py` and
  `test_land_summary.py`: passed, 462 tests. Earlier focused runs found test
  assumptions about evidence-directory hashing, pre-refusal minting, and land
  outbox action IDs; those assertions were corrected to preserve existing
  behavior.
- `uv tool run "ruff@$(just pin ruff)" check src tests --fix` and
  `uv tool run "pyrefly@$(just pin pipx:pyrefly)" check`: passed after migration
  fixes; the same checks also pass through `just check`.
- An isolated Python comparison of `SCHEMA.ddl` with the schema source read by
  `git show HEAD:src/taskloop/factory_schema.py` confirmed byte-identical DDL
  and unchanged schema version 20. `git diff --check` passed.

The tracked real-test callers were updated for the explicit port signature.
No separate live/real or dashboard-server test command was invoked; the required
`just test` selection was run unchanged and passed.
No Git write, tracker mutation or dependency operation was performed beyond
rebuilding the current project through the required gates.

Separate follow-up tasks, recorded here per the final scope decision; no Beads
operations are attempted in this sandbox:

- **Step vocabulary migration:** consolidate the repeated step names and their
  consumers under one typed definition and edge codec. Preserve the existing
  distinction between agent steps, checks and land, and the sequencing rules.
- **Claim vocabulary migration:** consolidate repeated claim-state definitions
  and codecs while preserving tracker-adapter boundaries, lease handling,
  admission fences and reconciliation. An ID-port edit in a claim path does
  not authorize this migration.

The original broader census and repeated database-unavailable explanation
remain outside this task; this plan makes no claim that they are resolved.

Commit-safety retry: explicitly set `tests/steps/test_verifier.py` to mode
`0644`. Audited all 90 changed/new paths: each is a plain, non-executable file
within the size limit, with no symlink component or forbidden path. Reran
`just check` (passed, all 9 import contracts) and `just test` (3,461 passed).
No test files were added during this retry; all 90 implementation paths are
included again in the handoff.
