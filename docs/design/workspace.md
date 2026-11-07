# Workspace spike: one leaf stage as a uv-workspace member (bead tl-e5t0.65, ARCHVERT-WORKSPACE)

Status: spike done, **GO** with the order in section 6. Evidence: branch `spike/workspace-artifacts` (commit a771b842, pushed, **not merged**; it is a rehearsal and the first real carve can start from it). Strategy lives in [stage-packages.md](stage-packages.md); this note is the measured answer to its WORKSPACE row.

## 1. What was already true

`packages/kernel` (import root `tlkernel`) and `packages/testkit` (`tltestkit`) are members; `src/tlpaths.py` puts every `packages/*/src` on `sys.path` (imported first by `taskloop`); `dev/packages.py` picks packages by the declared graph; `just test-packages` runs each in `uv run --isolated`. So (a) and (c) below were confirmed, not built. The spike is the first stage moved, which is what shows what is still kernel-shaped.

## 2. The leaf: `app/artifacts` (why)

Candidates measured by their outward imports (`taskloop.*` other than themselves): artifacts **0**, look 8 (adapters, domain, artifacts), report 8, track 6, prune 7, release 8. A stage package may import only `tlkernel` and third parties (anything of `taskloop` would be a cycle), so a leaf is honest only if it imports nothing of the tree. artifacts is the only one: 7 files, 426 lines, 4 test files, 302 lines; imports `tlkernel` (artifact, paths, wire), stdlib and the vendored `atomic_io`. `release` and `gate` (checks) are **not** leaves: they import `taskloop.adapters.*`, `stores.real` and `domain.*`.

## 3. What was done (spike diff: 40 files, +257 -139; 13 files are the package)

Package `packages/artifacts`: `pyproject.toml` (name `tlartifacts`, dependency `tlkernel`, dev group `pytest`, `tltestkit`), `ruff.toml` (extends the kernel's, adds ANN401), `src/tlartifacts/` (git mv, history kept), `tests/`. Consumers (`look/shots`, `run/ask_flow`, `write/show_check`, `cli/factory`, 6 tests) changed `taskloop.app.artifacts` to `tlartifacts`: a pure rename.

## 4. Findings, per question

| # | question | result |
|---|---|---|
| a | kernel its own member, no cycle | yes. `tlartifacts -> tlkernel` only; new import-linter contract `package-artifacts-imports-only-the-kernel` (forbids taskloop, tldash, delegate); `tlartifacts` is also in the converted-stages (no host) contract. 21 contracts kept, 0 broken. |
| b | naming | **folder `packages/<stage>`, project `tl<stage>`, import root `tl<stage>`** (`tlkernel`, `tltestkit`, `tlartifacts`). One rule, no clash with `taskloop.app.<stage>` words, greppable. The folder is the short name: `uv run --package tl<stage>`, `just test-pkg <stage>`. |
| c | tl.py puts member src on sys.path | yes, `src/tlpaths.py` globs `packages/*/src`; nothing to add per package. `tl.py --help` and `import taskloop.cli.factory` resolve `tlartifacts` from the checkout. |
| d | tools cover `packages/*/{src,tests}` | **not for free**: each of these hard-coded `packages/kernel/src` and had to become a glob: `justfile` rules PYTHONPATH, `dev/affected.py` ROOTS/VISIBLE, `tests/rules/arch_rules.py` production trees, `dev/hostban_mutation.py`, plus root `ruff.toml` `src`, `pyrefly.toml` `search-path`, `.importlinter` `root_packages` (those three are one line per member; list them or derive them). pyrefly needed `project-includes = packages` (already there). |
| e | `uv run --isolated --package PKG` runs its tests and fails an undeclared sibling | yes. 33 tests pass alone (0.15 s test time, 0.84 s wall with the environment). A seeded `from taskloop.app.look import shots` in a package test failed `ModuleNotFoundError: No module named 'taskloop'`. The very first run also failed on `atomic_io` (see bugs). |

### Bugs and gaps the spike found (each is a line item of the order below)

1. **`dev/packages.py` skipped a changed package silently.** It returned project names (`tlartifacts`) for changed paths but folder names for the "reach all" case; `just test-packages` then looked for `packages/tlartifacts/tests`, found nothing and skipped. The toy tests used one name for both and hid it. Fixed in the spike with a test (project name differs from folder).
2. **The dev group was not in the graph.** A `tltestkit` change reached no package. Fixed: dev-group names count as declared (`testkit -> artifacts`).
3. **The "collect only classes the module defines" rule lived in `tests/conftest.py`.** The package run collected `ArtifactSlot` (imported) as a test class. It moved to `tltestkit.plugin` (entry point `pytest11`), which also applies to the root run; the root conftest copy can then go.
4. **`support.case`, `support.tmpdir`, `support.spawn` (tests/support) are not in testkit.** The package tests had to drop `Case` and use `tmp_path`; the test that used `look.shots` (a sibling stage) moved to `tests/look/test_pictures_keep.py`. Rule for the carve: a test that imports a sibling belongs to the sibling or to `tests/e2e`. TESTISO (.66) is exactly this check; the spike did it by hand for 4 files.
5. **Vendored shelf (`atomic_io`) cannot be declared**: it is a directory under `skills/task-loop/_vendor` with no manifest. Spike answer: the package's pytest config has `pythonpath = ["../../skills/task-loop/_vendor"]`, which is the one undeclared path, stated in its `pyproject.toml`. Decision needed before many carves (section 7).
6. **Ratchets assume `taskloop.app.<stage>`.** `tests/rules/host_ban.py` (converted list only grows) read the moved stage as "left the list"; `converted()` now maps `tl<stage>` to `<stage>` and `code_dir()/ruff_file()` find the package. `arch_invariants.SLICE_IMPORTS`, the layers contract (`track | doctor | artifacts`) and `test_dash_state_paths` named the old path and were edited. Each carve edits these four places; PATHS and K1 shrink that list.

## 5. Measured effect

| | before (main) | spike |
|---|---|---|
| test files `dev/affected.py` picks for a change to `keep.py` | 188 | 185 root files **plus** the package's 1 isolated run |
| why almost no gain | `look`, `write`, `run`, `cli` still import artifacts, and `run` is imported by nearly everything | the reach shrinks only when consumers reach a stage through its api |
| isolated run of the package | n/a | 33 tests, 0.84 s wall, own env |
| `just check` | green | green: ruff, pyrefly 0 errors, 21 contracts kept |
| `just test` | green | green after fixing 1 ratchet failure (host_ban): 2908 passed, 2 skipped, 3 min 28 s. The spike edits root config, so the selection was the whole tree (2490 root tests); the numbers are not a per-carve cost |

Honest reading: the **selection gain is nil for a leaf that the shell still imports**. The gain of the workspace is isolation (a stage's tests cannot import a sibling, proven) and, later, a closed reach once consumers go through ports. The gate cost of a carve is small only after the mechanics PR (WS-MECH) makes the tools glob.

## 6. Go, and the order

**GO**, as a sequence of pure-move PRs behind one mechanics PR. Rule for all: a carve is a `git mv` plus renames, no logic change; one carve per PR; the layout lock needs `Layout-allow:` in each.

| step | bead | content | parallel with | collides with |
|---|---|---|---|---|
| 0 | S1a (.11) + T1 (.22) + K1 (.10) as **WS-MECH** | take from the spike: globs in justfile, affected.py, arch_rules, hostban_mutation; `dev/packages.py` fixes (bugs 1, 2) and its tests; `tltestkit.plugin` (3); `host_ban` resolver (6); kernel named as a lint layer; derive ruff `src`, pyrefly `search-path`, `root_packages` from the member list or one line each. No stage moves. | nothing (merge first, small) | touches `.importlinter`, `justfile`, `dev/`: any open PR editing those rebases (C-PIPELINE will edit `.importlinter` and `arch_invariants`) |
| 1 | **artifacts** (E1 part, from the spike branch) | rebase the spike commit onto WS-MECH | 2, 3, 4 | C-PIPELINE touches `run/ask_flow.py` (one import line). The spike has no other overlap |
| 2 | S1b (.12) `tldash` into packages/ | a move of an existing top-level package | 1, 3 | none known (dash is read-only on state) |
| 3 | PATHS (.25) | split `paths.py`; **blocked** until #219/#232 land; the stage-owned path helpers (`artifacts/paths.py` etc.) already moved with their stage | after the first 2 carves | every carve (bug 6 list), so do it before the big carves, not after |
| 4 | TESTISO (.66) | test-to-package map and the sibling-import check across all of `tests/`; makes bug 4 a gate rule | 1, 2 | none |
| 5 | S3 carves, **after their outward imports are settled**: slots (.17), asks (.18), then gate (.16), release (.19), track, doctor, report | each imports `taskloop.adapters/stores/domain` today (section 2): first move the shared pieces (`adapters.ident`, `bd`, `stores.real`, `domain.checks.*`) into kernel or into the owning stage, or behind a port. One PR per stage move, one per port. | 2 at a time (shared files: `.importlinter`, `uv.lock`; conflicts are mechanical) | **C-PIPELINE (.39)**: it moves `run/{stages,closer,steps,budget,blocked,waits,reload,reflect}`; gate/slots/asks/release are imported from there, so carve them **after** .39 lands, or the import rewrite conflicts in every moved file |
| 6 | S3-land (.20), E1 rest: plan, write, review, look | `Any` hosts first (HOSTBAN .61, ROUNDRESULT .60); look needs artifacts done | after 5 | C-PIPELINE (same reason) |
| 7 | S1c (.13) delegate into packages/ | `src/delegate` moves | alone | **B3 (pix-deleg-iso)** edits `src/delegate`; run S1c only after B3 lands |
| 8 | T-BUDGET (.55) | per-package closure and import-time ratchet; `closure_ratchet` reads the member list | last, after 5 | none; its numbers are meaningful only once stages left the tree |

R6 done: the pipeline is `packages/pipeline` (`tlpipeline`), with isolated package tests.

Status: step 0 (WS-MECH) merged; step 1 (artifacts) is the workspace member `packages/artifacts` (`tlartifacts`), with isolated package tests. P5a moves gate code to `packages/gate` (`tlgate`), with `checks/step.py` left as shell glue and tests retained in `tests/checks`.

Parallel now: step 0 first (this week, one PR); then 1, 2 and 4 together. Hold 5 and 6 until C-PIPELINE lands; hold 7 until B3 lands.

TESTISO (step 4) is done: member tests may import only their own package, declared runtime and dev dependencies, pytest and the standard library. `tests/rules/package_tests.py` checks every member test import (lazy and TYPE_CHECKING too); `tests/rules/test_package_tests.py` runs it in the gate and proves an undeclared sibling fails.

For a converted stage, `tests/<slice>/` is its integration layer on the shell host: it imports the package plus the shell. Package-pure tests live in `packages/<stage>/tests/`; the rules fail a package-pure file left in the mapped shell slice (`tests/checks/` for gate). This changes neither the caps nor the test kinds.

## 7. Decisions asked of the owner

1. Vendored shelf deps (`atomic_io`, others) in a package: accept `pythonpath = ["../../skills/task-loop/_vendor"]` per package (the spike), or give each vendored dir a manifest so it is declared. Recommendation: accept for now, revisit when a second package needs one.
2. Names: `packages/<stage>` + `tl<stage>` (section 4b). Recommendation: yes.
3. Confirm step 5 starts with port/adapters moves, since most stages are not leaves; the carve counts in the epic (one M each) understate this.

P5a gate code carve: `packages/gate` (`tlgate`) owns check execution and
`domain/`; `taskloop.app.checks.step` remains shell glue. Tests stay in
`tests/checks` for the later test carve. No facade or behavior change.

Gate carve review notes: the HOSTBAN identity remains `checks` for its monotone
list, with its code and Ruff config resolved to `packages/gate`; both shell glue
and the member stay in the no-host import contract. The slice import policy maps
`tlgate` application modules to the existing `checks` policy, while its `domain`
retains the domain effect guard. Schema-part discovery includes workspace sources.
The closure ratchet now measures `tlgate` as `gate` as well as the shell glue,
and includes its sources in every consumer closure. The initial member requires
`Ratchet-allow: closure +150 gate member: 115 local files and 35 external roots`
and `Layout-allow: node gate workspace member` on the eventual commit.

Unresolved policy conflict: the specified gate Ruff config extends kernel, whose
threading ban rejects existing imports in attempts, base, host, lanes, linux,
resources and round. Resolving this requires a lint-layer decision; the pure move
keeps both the imports and requested config.

S1 slots code carve: `packages/slots` (`tlslots`) owns slot orchestration, liveness and slot environment rules. Tests remain in `tests/slots`; machine effects are supplied through `Effects`, bound by `app/wire/slotfx.py`.

E1 slice 1: `packages/work` (`tlwork`) owns review application code and review, work and prompts domain rules. Tests remain in their original slice directories. Link checking receives the network adapter through the `Links` Protocol from run/host.py. The carve is rerunnable with `dev/carve_work.py --root DIR`.

Dash is carved into `packages/dash` (`tldash`), with isolated package tests.

E1 slice 2: `tlwork.plan` owns plan application and domain code. Shared bead IDs, bead matchers and owner metadata keys live in `tlkernel`; plan receives the existing `TreeProbe` protocol. Tests remain in their original directories.
