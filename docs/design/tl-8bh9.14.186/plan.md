# Depth
Depth: medium; three linked behaviours: generate a pinned shelf digest, supply it with agent guidance, and verify alignment and reduced source hunting. No owner decision is missing and no dependency is explicitly unlanded. Evidence budget: 12 model calls total.

## Size
Estimate: 14 changed files, including tests, generated data, this plan and observation evidence; 3 independent behaviours; 85 model calls for one implement attempt. No factory database schema change.

1. Generate the digest. Acceptance: deterministic generation resolves all six shelf packages from the selected repository's uv.lock, reads their exact commits, supplies public names, compact one-line signatures and source-backed limits, and produces a complete block of at most 2,500 tokens including guidance.
2. Supply the digest. Acceptance: both plan and implement inputs contain it exactly once, including after preparation selects a newer source and during repeats; the block states shelf is read-only, gives the pinned Git read command, and directs necessary shelf changes to needs_owner with a proposal for the supervisor.
3. Verify provenance and effect. Acceptance: focused tests detect a changed lock pin and stale generated data; evidence for eight later real attempts records zero searches of .venv, ~/.cache/uv or ~/Projects for shelf source. Record failures honestly; synthetic runs cannot satisfy this observation.

## Design
InputContext supplies both step renderers. Admission reads its selected commit; Attempts._context refreshes the block at the prepared head. Extend this shared path. Plan slots still require neither setup nor an installed shelf package.

Generate and commit docs/shelf-digest.json (new) through a native Python factory module entry point when pins change. Inputs: target repository revision and explicit read-only shelf path. Parse uv.lock with tomllib and pydantic v2 edge models for URL, subdirectory, tag and full commit. Discover imports, including public submodule imports, through AST; never execute shelf code.

New shelf_digest_generate.py owns generation; new shelf_digest_source.py adapts GitViews/GitProfileFiles tree/blob reads. Missing source produces an explained failure naming package and revision. No directory discovery, fetch, checkout, installation, shelf writes, write transaction or subprocess escape.

Resolve public re-exports and render compact AST signatures preserving parameters, defaults and result types. Prioritize public APIs imported/called by the repository; include source paths. Compact repeated types and remove examples before reducing API coverage. Never invent facts or silently truncate signatures, packages, provenance or limits. Required content that cannot fit produces an explained failure for owner resolution.

Extract limits from pinned documentation/docstrings with source locations and hashes. Retain both required facts: capture refuses unresolved index entries (real_capture.py:40-45); writable integrity checks are cached per Store instance (store.py:174-183). No hand-maintained API summaries or unconditional-check claim.

Store package/tag/commit identities, source hashes, generated text, encoding and token count. Pin a tokenizer and explicit encoding; count the heading and guidance too. This dependency replaces a handwritten encoding and its tests; update dependency isolation accordingly. No timestamps, host-specific paths or word/character estimates.

New shelf_digest.py validates/renders. InputContext.read reads lock and artifact from the same selected commit through InputFiles and compares full relevant identities. Repositories without shelf imports need no digest. Shelf imports with missing lock/artifact, malformed, stale or oversized data raise explained InputError before dispatch. Runtime needs no shelf checkout. Regenerate with pin/import changes; contract tests reject stale data.

Render SHELF DIGEST inside the existing block. Guidance: shelf is read-only; read using `git -C ~/Workspaces/shelf show <commit>:<path>` with the listed commit; never hunt .venv, ~/.cache/uv or ~/Projects. A required shelf change means stop and answer needs_owner with a shelf proposal for supervisor routing. Missing necessary facts receive explained needs_owner. Align plan_step's existing .186 restriction to permit this pinned read. Implement receives identical guidance through InputContext. No new glossary term or stage.

## Change map
- input_context.py and plan_step.py: supply digest and align guidance.
- New src/taskloop/shelf_digest.py, shelf_digest_generate.py, shelf_digest_source.py: validate/render, generate, read source through InputFiles and GitViews/GitProfileFiles.
- New docs/shelf-digest.json: generated six-package artifact.
- pyproject.toml, uv.lock, tests/rules/test_isolation.py: tokenizer pin and isolation.
- tests/steps/test_input_context.py; new tests/steps/test_shelf_digest.py and test_shelf_digest_generate.py: semantic contracts.
- This plan; new docs/design/tl-8bh9.14.186/measurement.md: eight-attempt evidence.

## Read list
- src/taskloop/input_context.py:28-83 — context value, committed-input producer and shared renderer.
- src/taskloop/input_context.py:113-123 — replacement boundary used on dispatch and repeats.
- src/taskloop/plan_step.py:152-177 — plan caller and existing shelf restriction to align.
- src/taskloop/implement_step.py:120-134 — implement caller receiving the shared block.
- src/taskloop/admit_chain.py:238-259 — admission producer and input failure handling.
- src/taskloop/attempt.py:193-214 — prepared-head refresh and setup-independent plan dispatch.
- src/taskloop/git_views.py:25-66 — owning Git view and bounded reader construction.
- src/taskloop/git_views.py:101-147 — existing tree/blob adapter reused for source reads.
- src/taskloop/profile.py:94-110 — committed-file result types and port.
- pyproject.toml:5-50 — dependency declarations, packaging and test import configuration.
- uv.lock:15-25 — any-agent and beads-client pinned sources.
- uv.lock:46-48 — git-porcelain pin.
- uv.lock:115-117 — process-lock pin.
- uv.lock:214-221 — sqlite-store and stream-proc pins.
- tests/steps/test_input_context.py:37-89 — semantic file fake and both renderer contracts.
- tests/steps/test_input_context.py:136-240 — committed selection, dispatch failure, moved-head refresh and repeat contracts.
- tests/rules/test_isolation.py:45-90 — locked dependency and installed-origin contract.
- src/taskloop/agents/launch.py:9-15 — public submodule imports that import discovery must include.
- src/taskloop/evidence_files.py:1-25 — owning evidence reader boundary for later observation.
- src/taskloop/plan_content.py:70-86 — plan depth, size and Change map validation.

External inputs: read-only __init__.py/README.md blobs and referenced definitions at each lock commit. Limit evidence paths appear in Design. No installed-source search.

## Verification
Test re-exports, submodule imports, changed signatures/docstrings and deterministic generation with semantic Git fixtures. Compare six identities against the actual lock. Pin mutation invalidates; regeneration changes content. Check malformed/unreadable inputs, overflow, token cap, limits and guidance.

Extend context tests for both steps, absent shelf imports, dirty-tree isolation, moved source and repeats. Tests need no installed shelf source. Preserve size/type rules.

Implementation: just install, focused digest/context tests, then required just check and just test with supported focused selection. No agent whole-suite/live tests; this plan runs no implementation gates.

Observe eight later normal attempts through owning evidence readers. Record identifiers, step, commit, digest provenance and prohibited searches. Pinned reads are allowed. No transcript-derived control state or artificial live attempts. If eight are unavailable, record the remaining observation without claiming success.
