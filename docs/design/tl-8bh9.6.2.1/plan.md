# Read one task in its configured backlog

Task: tl-8bh9.6.2.1, bounded child of TASK-CONTRACT tl-8bh9.6.2. Prepared 2026-11-09.
This is a proposed implementation plan, not a delivery receipt. Source starts only after the prerequisites below.

## Minimum usable behavior

One application operation reads a task in an explicitly configured tracker/backlog binding and returns scoped
identity, title, requirements, acceptance and dependencies without rewriting their meaning. Equal task IDs in
different backlogs remain distinct. Empty requirements are valid inspection data, not an admission decision.
Missing task, malformed reply and unavailable tracker remain distinct results/refusals.

Proposed CLI: `tl task show TASK_ID --backlog BACKLOG --tracker-root PATH [--json]`. Both binding arguments are
required; Beads is the sole implemented adapter. They configure this invocation without a new profile format or
registration database. The adapter validates nonempty binding inputs and addresses the supplied tracker root
explicitly. It must not default to the caller's current directory. A supplied logical backlog key is explicit
configuration, not a claim that Beads exposes a globally canonical database identity. If backend validation cannot
establish a stronger guarantee, report that limit rather than inventing one.

Do not derive namespace from Git origin, task-ID prefix, current directory, path hash or guessed forge identity.
Later registration can persist this binding through its owning operation. No cross-machine exclusion is claimed.
Success goes to stdout; operational refusal is nonzero with useful stderr. JSON mode produces structured task
output or a structured error on stderr, consistent with repo inspection. Invalid syntax remains an argparse error.
Public names/output use task, task tracker and backlog; backend-specific record names stay inside the adapter.

## Existing shelf owners inspected

Source inspected in `/home/iorlas/Workspaces/wt/shelf-git-porcelain-66/packages/`:

| Owner | Existing implementation | Fit for this read |
|---|---|---|
| `task-spec/src/task_spec/model.py` | Frozen `Task` with purpose, structured acceptance, trust/status and task-linter fields | No raw description/acceptance, dependencies or scope; interpreting raw tracker text as its structured fields would lose meaning |
| `task-spec/src/task_spec/ports.py` | `TaskStore.get/all/save`; separate attention port | No read-only adapter; requiring save/all would add behavior this slice does not use |
| `task-spec/src/task_spec/testing.py` | Semantic `InMemoryTaskStore` and `task_store_contract` | Useful for that model, but lacks the actual backend read shape and typed fault behavior needed here |
| `beads-client/src/beads_client/client.py` | `Bd(actor, cwd=...).show(id)` returns a frozen record or `None`; `BdError` carries typed failures | Already performs the required read and preserves title, raw requirements/acceptance and dependencies |
| `beads-client/src/beads_client/records.py` | Backend records and dependency normalization | Present malformed consumed fields/dependencies can silently become empty or be dropped; show does not require exactly one matching returned ID |
| `beads-client/src/beads_client/testing.py` | `Script` queues CLI replies and records argv | Transport fixture, not the owning semantic read fake factory tests require |

No `TaskPort` or `FakeTaskService` was found in current shelf source. The shelf parent `shelf-9zhu` anticipates a
broader task-spec adapter; that does not require this read to implement that unfinished model/write contract.

## Alternatives and recommendation

Expanding task-spec would require changing its task model, introducing scope/dependency/raw-text shapes, factoring
its port, changing its in-memory store and shared contracts, then writing the Beads adapter. It would also require
resolving how raw prose relates to structured purpose/acceptance and trust defaults. Those are multiple public
consumer surfaces for a read that currently needs none of its write, linter or attention behavior. The inspected
shelf has no existing adapter to reuse. DEEP/STABLE/WINS therefore fails for adopting TaskStore in this slice.

Recommend the smaller path: reuse `Bd.show` and its records/errors; add only an owning read protocol and semantic
fake in beads-client; map the backend record once into one factory inspection result. This changes no task-spec
model/port/test and needs no implementation of save/all. The protocol contains only the existing show operation;
it is not a general TaskPort, tracker platform or second task store. New names below are proposed, not existing APIs.

The library addition is approximately one small protocol, one in-memory read fake, and a focused read-contract
suite plus narrow validation fixes. The factory addition is one small result/projection module, an adapter/composition
boundary and a CLI route. Actual size follows implementation; no package/framework or protocol hierarchy is justified.

## Owning-library prerequisite

Owning prerequisite: shelf-ryf2. Prepare this separately tracked/reviewed beads-client change before factory adoption:

- Export a structural read protocol, proposed `TaskReadClient`, with only
  `show(task_id: str) -> Bead | None`. Existing `Bd` satisfies it directly. Its backend record vocabulary stays in
  the library and factory adapter; no general domain or write API is introduced.
- Add a semantic in-memory read fake in `beads_client.testing`, proposed `FakeTaskReadClient`. Tests seed frozen
  backend records directly and request explicit typed read failures. Separate instances represent separate configured
  backlogs. Unknown task returns `None`; malformed/unavailable cases raise the same supported `BdError` kinds as
  the real client. Fake seeding is a test utility, not a new production mutation operation.
- Run the same focused read behavior contract against the fake and real client with controlled transport fixtures.
  Keep recorded JSON, argv checks, malformed protocol cases and invocation failures in the owning library tests.
- Tighten owning single-task validation for fields consumed here: title, description, acceptance text and dependency
  entries. Missing optional values may use documented empty defaults; wrong-typed present values must not silently
  erase requirements. Reject multiple rows, mismatched requested/returned IDs and dependencies without valid target
  IDs/relationship values. Preserve all legitimate relationship kinds, including parent-child.
- Reuse the existing runner, records and typed `BdError` classification. There is no second CLI launcher, new
  namespace discovery mechanism, task-spec dependency or new suppression. Retain other existing client behavior;
  assess any validation change's existing callers in the owning package.

This prerequisite supplies the missing semantic test seam and truthful reads, not conditional mutations or discussion
identity. Release it normally; recorded library tests can use Script, but factory tests cannot use scripted CLI replies.

## Factory operation and adapter

Proposed minimum factory shapes, defined only for this inspection consumer:

- A configured binding contains the explicit backlog key and tracker root; adapter identity is Beads. Validate at
  construction/composition. No backend-global ID is guessed from that configuration.
- A scoped task reference pairs adapter/backlog scope with task ID. A dependency projection preserves its scoped
  target reference, relationship kind and supplied title/status. The target is in the configured backlog unless the
  backend explicitly reports another scope; unknown cross-backlog relationships are not invented.
- One frozen `TaskInspection` contains the task reference, title, raw requirements text, raw acceptance text and
  immutable dependency projections. Do not add task-spec's unrelated trust/linter/ask fields or parse Markdown.

The factory's tracker adapter receives the configured binding and shared `TaskReadClient`. The application operation
`inspect_task(adapter, task_id) -> TaskInspection` reads once and maps the owning backend record exactly once.
Authoritative absence becomes a typed missing-task refusal carrying the requested reference. Backend malformed and
unavailable kinds remain distinct; preserve diagnostic detail instead of replacing every error with absence.
The adapter is the only factory module naming backend records. CLI/future callers consume the application result,
not backend JSON. No competing factory TaskPort or fake is needed. CLI owns presentation; composition supplies
`Bd(actor, cwd=explicit_root)` in production and the owning semantic fake in tests.

Evolve CLI dispatch so task reads cannot run repo inspection accidentally. Do not read Git identity or another tracker
to fill gaps. Factory source and tests have no subprocess/raw process calls, private tracker-file reader, JSON roundtrip
for in-process calls, baseline import, fallback implementation or hand-edited installed dependency.

No factory.db fields are needed. Do not add registry, coordinator, reservation, attempt, session, claim or pending-action
rows. There is no enabling execution binding, scheduling, claim/update/close, discussion replay or eligibility decision.
Parent TASK-CONTRACT stays open; tl-r2g4 still gates its conditional-mutation work.

## Admission and validation

Begin successor code only after REPO-INSPECT tl-sqd3.18.1 has an independently reviewed, validated local checkpoint with
its portable released Git dependency, and the beads-client prerequisite/fake has a tested, independently reviewed API.
Co-development may use an explicitly temporary uncommitted candidate-wheel override while publication is pending;
final consumer validation/checkpoint requires the actual portable release pin and matching lock.
A source checkpoint is sufficient for sequential implementation on the successor branch; it does not close either task
or claim factory delivery before its authorized merge. Candidate wheels/local shelf overrides can
establish evidence, but cannot satisfy committed dependency pins or final locked gates. No task-spec dependency is
proposed for this slice. No library source or temporary local-path pin is copied into factory.

Focused factory tests use the owning semantic fake and the real application/CLI surfaces:

1. Equal IDs in two explicit backlog bindings produce different references and the correct distinct requirements;
   changing current directory or origin cannot select a different scope.
2. Title, raw description/acceptance and all dependency relationships survive unchanged. Empty text and no dependencies
   are valid success and do not infer approval or eligibility.
3. Successful absence, malformed reply, unavailable backend and invalid binding remain distinct. Invalid binding
   never falls back; errors never become empty tasks. Inspection performs only its one task read.
4. Text/JSON modes render the same result. Operational errors are nonzero with empty success stdout and correct
   structured error kinds in JSON mode. Omitted binding arguments are rejected.
5. The noneditable installed successor matches current source and exact portable dependencies. Existing repo inspection
   behavior remains green; no baseline/editable/PYTHONPATH substitution supplies missing code.

Run focused new scenarios first, then required `just check` and `just test` after reading the justfile. Obtain independent
acceptance/code review and an executable smoke. Wire validation and semantic fake contracts remain in shelf. No full/live
test run is authorized. This planning pass changed only this plan; it records no source implementation or completed gates.
