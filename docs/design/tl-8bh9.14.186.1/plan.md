# Depth

Medium: package identities, public signatures and documented limits are three independently testable extraction behaviours. No owner decision is missing and no dependency is explicitly unlanded. Evidence budget: 12 model calls total. The supplied glossary definitions apply; no missing term or new glossary term is needed.

## Size

Estimated changed files: 11, comprising eight new source files, two new test files and this plan; no generated artifact or dependency changes. Estimated independent behaviours: 3. Estimated model calls for one implement attempt: 75, including focused tests and the required gates.

1. Package identities: fixtures with six lock entries produce exactly their names, versions, repository URLs, subdirectories, requested tags and resolved commits; mismatched pinned manifests and missing commits produce an explained failure.
2. Public signatures: fixtures resolve aliased and chained re-exports and public submodules to declarations, preserve parameter kinds, annotations and defaults, and reflect a changed signature at a changed pinned commit without accepting dirty working-tree changes.
3. Documented limits: fixtures preserve exact documentation containing timeouts, platform restrictions and behavioural qualifications with source locations; changing that text at a changed pinned commit changes the result. Reordered file enumeration and repeated generation produce identical output bytes.

All three belong to this producer. Dependencies: none. The parent discussion explicitly assigned artifact bounding and attempt-input integration to later tasks and observation to the parent. Its tokenizer question is resolved: no new dependency. This task does not need a tokenizer or token approximation.

## Evidence and boundary

The checkout is at cdf44d72c72c276378e97b9b36b66020d25bc6c2, initially clean, with no existing task plan and no Task-Loop-Wip trailer among the 30 recent commits inspected. `pyproject.toml` and `uv.lock` identify six shelf distributions. Any-agent and stream-proc share 14bb4512c383c174d8db580d66d1c270aa656dee; other distributions have their own pinned commits. Installed-module reflection would lose this distinction and must not supply source facts.

`GitViews.checkouts`, `Repo.tree`, `Tree.files` and `Tree.read` already provide bounded reads of committed objects; `GitProfileFiles` shows regular-file validation. Package roots use re-exports and literal `__all__`, and public modules include nested packages. Limits appear in README prose and docstrings, not just numeric constants: examples include process-lock's never-break rule, sqlite-store's platform restriction and beads-client's non-atomic verbs.

Produce a typed, deterministic extraction library and an executable module that writes its result to stdout. This is the generation foundation consumed by the next task, not the final `docs/shelf-digest.json`. Do not change factory dispatch, prompts, database state, source pins or shelf code. No tracker operation, remote publication or source acquisition is part of generation. A caller supplies a local shelf repository containing the pinned objects; absent objects fail with an explanation rather than fetching or falling back to another revision.

## Implementation

Create `src/taskloop/shelf_digest/` with these new files:

- `models.py`: pydantic v2 models for validated lock/manifests and the extraction result, identities, declarations and documentation with commit, path and line provenance. Closed declaration/error vocabularies use stdlib enums and one serialization boundary. Include explanatory failures rather than partial successful output.
- `pins.py`: parse supplied project/lock bytes with `tomllib`, validate their six shelf sources and direct versions, decode Git URL query fields structurally, require full resolved commit IDs and validate package-relative paths. Derive identities from input rather than hard-coding today's versions. Preserve stream-proc's distinct distribution version and shared any-agent commit.
- `source.py`: adapt the existing owning shelf Git API to a narrow read-only source port. Resolve each full commit once and read its manifest, package sources and declared README from that immutable tree. Validate regular files and package boundaries; reject traversal, symlinks, missing objects and unreadable listed blobs. The adapter contains backend types/errors and supplies generic explanations. Do not walk installed packages or mutable source files; cache only within one generation.
- `public.py`: parse Python with `ast`, never import or execute the inspected source. Discover package modules from the pinned manifest's source roots. Resolve absolute/relative imports, aliases and chained package-local re-exports using a cycle-aware symbol graph. Honour statically declared `__all__`; where absent, use locally declared non-underscore names and explicit public re-exports, excluding incidental external imports. Include public submodule paths, not only root exports. Resolve literal star exports through their source module; report unresolvable exported declarations and unsupported dynamic export construction with provenance instead of inventing a signature.
- `documentation.py`: extract the complete declared README and docstrings of exported modules/declarations, keeping headings, paragraphs, lists, fenced examples and source spans. Preserve all this documentation as evidence for documented limits, so no keyword filter or invented paraphrase can drop a qualification. Keep these records distinct from signatures and literal values; the later bounded-artifact task can select facts from them. Do not claim every paragraph is a limit or infer guarantees from implementation alone.
- `generate.py`: one application operation composes identity validation, static signature extraction and documentation extraction. Return the typed complete result; establish canonical ordering by package identity, public qualified name, then source location, and stable UTF-8 JSON serialization with a final newline. Output excludes local paths, clock values and installed runtime versions.
- `__init__.py`: expose that operation and its input/result types for the next task's consumer.
- `__main__.py`: a small composition root accepts explicit task-project/lock file paths and a shelf repository path, constructs a bounded hardened Git view, calls the same operation and writes canonical output to stdout. No new console-script entry or main CLI command. Errors go to stderr with a nonzero exit status and no successful partial JSON.

Represent functions and methods from their AST signatures: positional-only, keyword-only, variadic parameters, defaults, return annotations, async, overloads and relevant decorators. Preserve public class bases, declared constructors, annotated fields/defaults and public methods, including protocol methods and properties. For dataclasses record their fields and decorator options rather than guessing a runtime-generated constructor. Represent aliases, type aliases and exported constants with source expressions and their origins. Follow package-local bases for public inherited declarations with a visited set; retain external bases as references without crawling external distributions. Static expressions are rendered consistently using AST facilities; documentation retains its original wording. Unsupported constructs must be explained, never silently omitted.

The module's explicit input files are read once; all shelf content is read at lock commits. Do not hard-code UV cache locations. No subprocess, direct process control, runtime import of target packages, new third-party dependency, speculative store or factory schema change is needed.

## Tests and completion

Create `tests/steps/test_shelf_digest.py` for the three behavioural contracts using inline semantic fixture packages and the shelf `FakeRepo`, with expected facts asserted directly. Cover a root export aliased from another module, a chained relative re-export, nested public submodules, literal star exports, export cycles, async/overloaded methods, dataclass fields, external bases and an unsupported dynamic export. Avoid a test for each private helper.

Create `tests/cli/test_shelf_digest.py` for the executable module's composition/output contract using injected read/output boundaries, without spawning a process. Verify explained failures and no successful partial output. Put fixture construction in these two files; do not add a shared bootstrap or import unrelated factory slices in the tests.

Identity tests include all six identities and mismatches in version, subdirectory and object availability. Source-change tests create two committed fixture trees, change an exported signature and a documented restriction, update the corresponding lock commit and assert both changed facts. Leave dirty content and an unrelated revision in the fake repository and prove neither affects output for the original pin. Compare canonical bytes across repeat runs and reversed source enumeration. Documentation assertions check timeout meaning and adjacent qualifications, never just a document hash. Keep a real-pin extraction smoke check read-only and offline, using the explicitly supplied shelf repository; if a supported real source construct is missed, extend the targeted fixture and parser rather than accepting partial output.

After implementation, run `just install`, focused pytest for the two new test files under the installed declared environment, then the supplied gates `just check` and `just test`. Run no whole-suite/live commands beyond the supplied focused gates. If exercising the executable manually, use `uv run --frozen --no-sync python -I -m taskloop.shelf_digest` with its explicit input arguments. Do not add a PYTHONPATH or editable baseline install. Retain the existing 400 source-line, 80 function-line and 800 test-line caps without Any, cast or ignore escapes.

This planning attempt changes documentation only and does not run implementation gates. Completion of this task means this producer and its semantic tests pass both supplied gates; token bounding, committing the final digest, stale-artifact checks, prompt guidance and later-attempt observation remain outside its acceptance.

## Read list

- `pyproject.toml:5-50` — six dependencies, source declarations, package layout and pytest configuration.
- `uv.lock:14-87` — any-agent, beads-client and git-porcelain identities and the project's direct requirements.
- `uv.lock:114-117` — process-lock's resolved identity.
- `uv.lock:213-221` — sqlite-store and stream-proc resolved identities.
- `src/taskloop/git_views.py:25-57` — existing bounded, hardened Git view producer used by the executable composition root.
- `src/taskloop/git_views.py:101-147` — immutable tree reads and regular-file/error handling to follow in the new adapter.
- `src/taskloop/input_context.py:43-83` — current downstream input boundary; consult to keep attempt integration outside this task.
- `tests/rules/test_isolation.py:45-94` — six-source identity contract and shared any-agent/stream-proc commit assertion.
- `tests/rules/test_policy.py:13-60` — enforced source/test caps and prohibited escape mechanisms.
- `tests/steps/test_code_map.py:17-38` — semantic committed-tree fixture pattern and dirty-tree exclusion.
- `/home/iorlas/.cache/uv/git-v1/checkouts/14281b3f77872805/c6384f0/packages/git-porcelain/src/git_porcelain/api_results.py:218-244` — owning public Tree listing/read signatures.
- `/home/iorlas/.cache/uv/git-v1/checkouts/14281b3f77872805/14bb451/packages/any-agent/pyproject.toml:1-18` — pinned package manifest and declared source/readme layout.
- `/home/iorlas/.cache/uv/git-v1/checkouts/14281b3f77872805/14bb451/packages/any-agent/src/any_agent/__init__.py:8-63` — public symbols and exported submodules.
- `/home/iorlas/.cache/uv/git-v1/checkouts/14281b3f77872805/14bb451/packages/stream-proc/src/stream_proc/__init__.py:20-59` — another package's explicit re-exports.
- `/home/iorlas/.cache/uv/git-v1/checkouts/14281b3f77872805/c6384f0/packages/git-porcelain/src/git_porcelain/__init__.py:20-65` — re-exported protocol/result classes whose declarations live elsewhere.
- `/home/iorlas/.cache/uv/git-v1/checkouts/14281b3f77872805/af5189b/packages/beads-client/src/beads_client/__init__.py:3-25` — exported constants, classes and protocols.
- `/home/iorlas/.cache/uv/git-v1/checkouts/14281b3f77872805/d3d611c/packages/process-lock/src/process_lock/__init__.py:36-55` — locally declared dataclass fields and defaults.
- `/home/iorlas/.cache/uv/git-v1/checkouts/14281b3f77872805/d3d611c/packages/process-lock/src/process_lock/__init__.py:231-231` — explicit exports in the single-module package.
- `/home/iorlas/.cache/uv/git-v1/checkouts/14281b3f77872805/18d3164/packages/sqlite-store/src/sqlite_store/__init__.py:3-27` — re-export paths for storage declarations.
- `/home/iorlas/.cache/uv/git-v1/checkouts/14281b3f77872805/14bb451/packages/any-agent/README.md:25-41` — behavioural rules with qualifications that must survive extraction.
- `/home/iorlas/.cache/uv/git-v1/checkouts/14281b3f77872805/14bb451/packages/stream-proc/README.md:1-18` — platform and timeout documentation.
- `/home/iorlas/.cache/uv/git-v1/checkouts/14281b3f77872805/c6384f0/packages/git-porcelain/README.md:88-112` — public surface and FakeRepo usage.
- `/home/iorlas/.cache/uv/git-v1/checkouts/14281b3f77872805/af5189b/packages/beads-client/README.md:28-46` — non-atomic operations and tested-version qualification.
- `/home/iorlas/.cache/uv/git-v1/checkouts/14281b3f77872805/d3d611c/packages/process-lock/README.md:30-45` — timeout semantics and never-break restriction.
- `/home/iorlas/.cache/uv/git-v1/checkouts/14281b3f77872805/18d3164/packages/sqlite-store/README.md:1-8` — platform/import limitation.

The absolute shelf paths above identify existing read-only evidence in this host's UV cache, not required runtime locations. Obtain the same files through their full lock commits in the caller-supplied repository. The remaining manifests, exported declaration modules and docstrings are enumerated generation inputs, not a request for manual source hunting: use targeted symbol searches only when fixtures or pinned extraction reveal a missed construct. Existing integration points are the manifests/lock, Git view producer, Tree API and semantic fixture pattern listed above. All edited implementation/test files are new and named in the implementation narrative; existing source callers need no edit in this task.
