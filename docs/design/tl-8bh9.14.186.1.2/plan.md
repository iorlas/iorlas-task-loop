# Depth

Small: one cohesive behaviour, deterministic public signature extraction; aliases,
chained re-exports, submodules, cycles, declaration forms and pin changes are
semantic coverage of that behaviour. No owner decision is missing. Dependency
tl-8bh9.14.186.1.1 is reported landed and its source adapter is present. Evidence
budget: 6 model calls total, distinct from the implementation estimate below.

## Size

- Estimated changed files: 6, including this plan, four new source modules and
  one new test file. No generated documentation artifact in this part.
- Independent behaviours: 1. Acceptance: extraction from committed package
  sources produces stable public names, declaration signatures and defining
  locations across aliases, chained re-exports, exported submodules, cycles and
  declaration forms; changing a selected commit changes its affected signatures
  without reading checkout or installed-package definitions. The semantic fixture
  suite checks expected records and explained failures, and both required gates pass.
- Estimated model calls for one implement attempt: 48, including focused
  verification, repairs and the final required gates. No schema change, shelf
  change, CLI wiring or documentation-generation work is needed.

## Evidence and boundary

The task's plan did not exist at the supplied source commit. The worktree was
clean, and its recent history contains the landed part 1, with no task-specific
saved work found. `source.py` already supplies sorted tree entries and immutable
regular-file reads. `identities.py` supplies the six reconciled package identities
and their pinned commits. A targeted source/test search found only those modules
and their tests as current digest integration points; no extractor caller exists.

The pinned package roots use explicit `__all__`, absolute package imports and
exported submodules. Representative definitions include generic classes and PEP
695 aliases in any-agent, an annotated `TypeAlias` in sqlite-store, and classes
declared directly in process-lock's package root. These require source analysis,
not importing the selected libraries or inspecting their installed versions.

Use the supplied glossary meanings for task, plan, attempt and worktree. No
missing domain term or new glossary entry is needed. Part 3 owns the later
documentation and generation entry point; this task exposes a callable extraction
operation for that future consumer, without inventing a CLI now.

## Read list

Shelf paths below identify existing source files in the read-only shelf
repository. Read their objects with `git show <sha>:<repository-relative-path>`
at the stated pin, never from its mutable checkout. The implementation consumes
other reachable package modules as source data through `CommittedSource`; it
does not need an agent survey of every shelf implementation file.

- `src/taskloop/shelf_digest/source.py:9-82` — existing source outcomes, entry listing, immutable reads and opening a selected commit.
- `src/taskloop/shelf_digest/identities.py:28-42` — identity producer's package and collection records.
- `src/taskloop/shelf_digest/identities.py:196-230` — existing validation and extraction operation to compose with, without duplicating it.
- `src/taskloop/shelf_digest/__init__.py:1-1` — existing feature boundary; direct module imports need no root re-export.
- `tests/steps/test_shelf_digest_source.py:16-41` — semantic Tree fixtures and regular-file/read-failure contracts.
- `tests/steps/test_shelf_digest_identities.py:26-79` — commit-indexed fake repository and manifest fixture pattern for pin-change tests.
- `pyproject.toml:41-50` — size limits and focused test import configuration.
- `uv.lock:15-25` — any-agent and beads-client immutable pins.
- `uv.lock:45-48` — git-porcelain immutable pin.
- `uv.lock:114-117` — process-lock immutable pin.
- `uv.lock:213-221` — sqlite-store and stream-proc immutable pins.
- `tests/rules/test_policy.py:17-55` — source/function caps and prohibited import/type escapes; no policy relaxation.
- `/home/iorlas/Workspaces/shelf/packages/any-agent/src/any_agent/__init__.py:8-63` — export and submodule examples at `14bb4512c383c174d8db580d66d1c270aa656dee`.
- `/home/iorlas/Workspaces/shelf/packages/any-agent/src/any_agent/answer.py:14-34` — generic classes and PEP 695 alias at the same any-agent pin.
- `/home/iorlas/Workspaces/shelf/packages/git-porcelain/src/git_porcelain/__init__.py:20-65` — package re-export example at `c6384f0bf870a430b7bffe826f9f42b6138d7d44`.
- `/home/iorlas/Workspaces/shelf/packages/beads-client/src/beads_client/__init__.py:3-25` — exported constants, types and functions at `af5189bc5a04dd1b068a62575a95c4fd99771369`.
- `/home/iorlas/Workspaces/shelf/packages/process-lock/src/process_lock/__init__.py:36-65` — root declarations and annotated fields at `d3d611ca15e07bacbf39727d14174f06bdc59e2a`.
- `/home/iorlas/Workspaces/shelf/packages/process-lock/src/process_lock/__init__.py:104-160` — public methods and context-manager declarations at the same process-lock pin.
- `/home/iorlas/Workspaces/shelf/packages/process-lock/src/process_lock/__init__.py:231-231` — explicit root exports at the same process-lock pin.
- `/home/iorlas/Workspaces/shelf/packages/sqlite-store/src/sqlite_store/__init__.py:3-27` — exported alias and function names at `18d3164893f95dc82e391a7226652d286d9c4663`.
- `/home/iorlas/Workspaces/shelf/packages/sqlite-store/src/sqlite_store/cas.py:5-26` — legacy alias declaration and parameter forms at the same sqlite-store pin.
- `/home/iorlas/Workspaces/shelf/packages/stream-proc/src/stream_proc/__init__.py:20-59` — root export graph at `14bb4512c383c174d8db580d66d1c270aa656dee`.

Additional targeted searches may locate a missed caller or a changed declaration;
keep any resulting implementation reads bounded and relevant.

## Implementation

1. Add new `src/taskloop/shelf_digest/models.py` for typed extraction results,
   public declaration kinds and explained failure reasons. Use stdlib enums for
   closed vocabularies and frozen records for in-process values. If a structured
   interchange boundary is introduced, use pydantic v2 there. Each signature
   retains the public qualified name separately from its defining module/name,
   package identity, selected commit, source path and declaration line range.
   Success is a complete ordered collection; a failure carries context and no
   misleading partial success. Preserve existing read failures and their causes.

2. Add new `src/taskloop/shelf_digest/declarations.py` for native Python AST
   declaration extraction and canonical signature text. Preserve function and
   async-function names, type parameters, positional-only and keyword-only
   separators, parameter defaults/annotations, variadic parameters and return
   annotations. Preserve overload declarations and signature-relevant decorators.
   For classes, retain bases, type parameters, decorators, declared fields,
   public methods, constructors and protocol methods such as context managers;
   do not synthesize inherited methods or execute dataclass/pydantic decorators.
   Include assignment aliases, annotated declarations, constants, PEP 695 aliases
   and annotated `TypeAlias` forms. Use stable AST formatting for expressions,
   excluding executable bodies and docstrings from signature text; declaration
   order remains meaningful for overloads and fields.

3. Add new `src/taskloop/shelf_digest/exports.py` to index module paths from the
   selected tree and resolve the public export graph. Use literal `__all__` when
   present; for fixture modules without it, use non-private locally declared
   names and explicit package-local re-exports, excluding incidental external
   imports. Support static list/tuple export lists and their literal composition;
   explain unsupported dynamic export construction instead of guessing.
   Resolve relative and absolute package imports, `as` aliases, assignment aliases,
   chained re-exports, package initializers and explicitly exported submodules.
   Follow star re-exports only through statically known exports. Traverse exported
   submodules rather than indiscriminately publishing every file in the package.
   Cache parsed modules and resolved bindings per selected source. Detect cycles
   using qualified bindings: resolvable cycles retain their declarations once,
   while an alias cycle without a definition returns an explained failure and
   terminates. Never silently discard an unresolved explicitly public name.

4. Add new `src/taskloop/shelf_digest/signatures.py` with one public extraction
   operation accepting the existing package identities and shelf repository port.
   Open each package at its identity's exact commit through `open_source`, locate
   its `src/<import-name>` package using that package's subdirectory and Python
   distribution-name normalization, then compose the index, resolver and
   declaration extraction. Validate the expected package root exists. Sort
   packages and public qualified names independently of tree/list enumeration,
   preserve distinct public aliases to one definition, and deduplicate repeated
   visits. Keep read, decode, parse, missing-binding and unsupported-export
   failures explained with package, commit and path context. No fetch, filesystem
   fallback, runtime import, subprocess, global mutable cache or JSON roundtrip.
   The existing identity/source modules are the producers; new modules and tests
   are the only callers in this part. No existing CLI or factory path changes.

5. Add new `tests/steps/test_shelf_digest_signatures.py` with pytest functions and
   semantic committed-source fixtures. Keep helpers local to this test unless a
   real second consumer warrants sharing. Keep the source modules under 400
   lines, functions under 80 and the test file under 800; split by the responsibilities
   above instead of adding escapes or changing policy.

## Verification

Assert independently authored expected records/signatures, rather than snapshots
derived by the extractor or tests of private helpers:

- Aliased exports and a multi-hop relative/absolute re-export retain public names
  while pointing to the correct defining declaration.
- Explicitly exported nested submodules expose their declared API; unrelated and
  private modules stay absent. Star export fixtures honor the target export list.
- A cycle with reachable declarations completes without duplicates; an unresolved
  alias cycle fails with a useful explanation instead of hanging or losing names.
- Function parameter forms, async and overload declarations, class fields/methods,
  root declarations, constants and both type-alias forms retain their semantics.
- Reordered tree enumeration and repeated extraction produce equal ordered output;
  selected commits with changed parameter/return/alias declarations change exactly
  the relevant signature content and provenance. Unrelated body/docstring edits
  leave signature text stable. Fixture checkout/installed values cannot affect it.
- Missing roots/objects, unreadable regular files, malformed Python, unresolved
  exports and unsupported dynamic exports produce explained typed failures.
  Include an executable import side effect in source data to prove it is not run.

After installing the package, use focused verification as needed:
`uv run --frozen --no-sync python -I -m pytest -q tests/steps/test_shelf_digest_signatures.py --tb=short | tail -40`.
Use semantic Git fakes; no live tests or baseline environment imports.

The implement attempt runs these two required gates once each, last, after all
edits and focused verification, preserving their actual exit status:

```sh
just check 2>&1 | tail -60
just test 2>&1 | tail -40
```

This planning attempt does not run implementation gates. Completion requires the
semantic fixture suite and both gates to pass, with no shelf edits or expansion
into the separately assigned documentation/generation task.
