# Header
Task: tl-8bh9.14.186.2.2
Base: 06d1561b5b2b93364a1e051594457f16ff8309ae
Depth: medium
Reason: facts, freshness, bound. No missing decision or explicitly unlanded dependency.
Evidence budget: 12 model calls.
Size: 11 changed files, 3 independent behaviours, 60 implement model calls.

## Outcome and non-goals
Produce a compact digest with verifiable mandatory facts and explained failure before output for invalid evidence or overflow. Reuse delivered identity reconciliation and immutable installed-source capture. Add fact selection, evidence validation and bounded rendering; fix the conditional-export obstacle in pinned-source extraction. CLI source selection and committing docs/shelf-digest.json belong to the following task.

## Settled decisions
- Reuse committed manifests and authorized installed capture; retain six identities.
- Keep exhaustive extraction internally; serialize selected facts with shared identity/source references.
- Resolve stream_proc.proctable platform branches statically when public signatures agree; retain branch ranges and reject incompatible definitions.
- Establish facts from declarations, documentation and bounded body AST checks, not phrase matching.
- Evidence identifies package, path, range and SHA-256 of cited bytes; validate against the same immutable sources.
- Use a conservative deterministic token upper bound: one token per emitted UTF-8 byte, including JSON overhead and final LF, with a ceiling of 2,500. Compact references and remove optional material first; never drop mandatory facts or identity information.
- Canonical compact JSON has stable ordering and one final LF. Failures remain explained and output buffered.

## Open decisions
- None.

## Change map
- `src/taskloop/shelf_digest/exports.py` — `PackageExports._statement`, `_parse`, `resolve`: support equivalent platform branches.
- `src/taskloop/shelf_digest/generate.py` — `Digest`, `_extract`, both `generate_*digest` producers: collect and validate facts; propagate failures.
- `src/taskloop/shelf_digest/facts.py` (new) — fact/evidence records and collection; integrates with `_extract`, `SourceOpener`, canonical declarations.
- `src/taskloop/shelf_digest/validation.py` (new) — fact/evidence validation; `_extract` calls it before success.
- `src/taskloop/shelf_digest/render.py` — `_Digest`, `render_digest`: compact pydantic JSON and complete-output ceiling.
- `tests/steps/shelf_digest_fixtures.py` — `complete_case`, `installed_case`: realistic source contracts.
- `tests/steps/test_shelf_digest_signatures.py` — `extract`: equivalent/incompatible platform branches.
- `tests/steps/test_shelf_digest_generate.py` — generation and rendering callers: facts, source parity, compact output.
- `tests/steps/test_shelf_digest_bounded.py` (new) — integrate `_extract`, validation and rendering: semantic, stale and boundary cases.
- `tests/cli/test_shelf_digest_cli.py` — `wired`, success/failure cases: adapted fixtures and buffered-output assertions.
- `docs/design/tl-8bh9.14.186.2.2/plan.md` — contract and read list.
- `src/taskloop/shelf_digest/cli.py` — consult `main`, production caller of `generate_digest` and `render_digest`.
- `src/taskloop/shelf_digest/signatures.py` — consult `_collect`, `_signature`, `extract_signatures`, consumers of `PackageExports`.
- `src/taskloop/shelf_digest/documentation.py` — consult `_package_docs`, `extract_documentation`, internal evidence producers.
- `src/taskloop/shelf_digest/installed.py` — consult `capture_installed_sources`, called by `generate_installed_digest` and installed-source tests.
- `tests/steps/test_shelf_digest_installed.py` — consult direct capture callers; preserve adapter responsibilities.

## Read list
- `src/taskloop/shelf_digest/generate.py:15-60` — both producers, shared extraction and result.
- `src/taskloop/shelf_digest/render.py:12-66` — current JSON models and serializer.
- `src/taskloop/shelf_digest/exports.py:58-224` — parsing, branch gap, linking and resolution.
- `src/taskloop/shelf_digest/signatures.py:12-64` — declaration ranges and export consumers.
- `src/taskloop/shelf_digest/declarations.py:1-80` — canonical declarations and branch comparison.
- `src/taskloop/shelf_digest/models.py:10-49` — existing signature and failure types.
- `src/taskloop/shelf_digest/documentation.py:100-145` — immutable document extraction and source ordering.
- `src/taskloop/shelf_digest/source.py:28-65` — source protocol and snapshots.
- `src/taskloop/shelf_digest/identities.py:14-42` — package identity ownership and six-package set.
- `src/taskloop/shelf_digest/installed.py:135-190` — snapshot assembly and failure propagation.
- `src/taskloop/shelf_digest/cli.py:15-33` — buffered production consumer and exception boundary.
- `tests/steps/shelf_digest_fixtures.py:33-120` — committed and installed fake producers to extend.
- `tests/steps/test_shelf_digest_generate.py:19-136` — generation/render callers.
- `tests/steps/test_shelf_digest_signatures.py:33-106` — static extraction helper and export contracts.
- `tests/steps/test_shelf_digest_installed.py:18-95` — direct capture callers and source failures.
- `tests/cli/test_shelf_digest_cli.py:16-111` — CLI fixtures, consumers and empty-output failure contract.

## Contract
Intent: collect required facts using reconciled identities and `SourceOpener`. Add immutable fact/evidence records and a required-fact enum; failures carry a reason enum and explanation. Serialized records use pydantic v2. No database change.

Effect: read pinned snapshots; verify opener commit, package membership, safe path, range, cited-byte hash and fact-specific AST/declaration predicates. Missing, stale or contradictory evidence fails the operation. A valid hash alone cannot validate an assertion. Rendering performs no IO.

Result: extend `Digest` with validated facts/evidence and both producers' failure union. `render_digest` emits deterministic reference tables; overflow raises an explained `ValueError`, handled by `cli.main` before stdout. Reordering preserves bytes; no partial result succeeds.

Facts distinguish `any_agent.run`'s wall-clock timeout (zero disables it) from its injected monotonic watchdog and suspend-gap adjustment. Retain registration before execution, started-hook ordering and callback-failure child cleanup; inspect captured registered-spawn cleanup before encoding it. Retain `Summary` fields/role, `RunOutcome.summary`, `Supervisor.finish` summary/live completion and killed-zero-exit correction, and `TurnDone.usage`'s optional token fields. Retain checkout-local `exclude`, and `park` detach/clean, ignored-file preservation and tracked-file collision refusal.

## Work packages
1. Facts: `exports.py`, new `facts.py`, `generate.py`, fixtures and signature/generation tests close acceptance 1. Exercise actual pinned capture and semantic fixtures; inspect remaining cited bodies through the authorized adapter. Full installed extraction must succeed.
2. Freshness: new `validation.py` and bounded tests close acceptance 2. Mutate commit, package, path, range, bytes and semantic predicates independently; unchanged snapshots pass.
3. Bound: `render.py`, bounded/generation/CLI tests close acceptance 3. Cover multibyte text, escaping, metadata overhead, reordered records, exact ceiling/overflow and huge optional material with retained mandatory facts. Run `just check 2>&1 | tail -60` then `just test 2>&1 | tail -40` once each, last.

## Acceptance behaviours
1. Both generation paths preserve required contracts with declarations and semantic evidence, including installed platform branches, without executing shelf code.
2. Unchanged evidence validates; stale, missing, contradictory or misattributed evidence fails with an explanation before output.
3. Complete JSON is deterministic and within the conservative 2,500-token byte bound, preserving mandatory facts and six identities; impossible bounds fail before output.
