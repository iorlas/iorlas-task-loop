# Stage packages: how the factory is built as isolated pieces (strategy, spiked)

Status: proposed for the owner's yes. Bead: tl-e5t0 (ARCHVERT). It settles the strategy that [architecture-vertical.md](architecture-vertical.md)
and [stage-isolation.md](stage-isolation.md) left open, and answers the owner's rules of 2026-11-07: a folder per package with everything in it,
uv workspaces, no copy and paste (inherit rules, test kit, pins), prompts inside their stages, no `host: Any`, and a design that works on other
repositories. The goal is isolation of tests, functionality and data; reuse and distribution are a by-product, not the goal.

## 0. The rules, in ten lines

1. A **stage is a package**: one folder holding its code, its prompts, its tests, its contracts and its data schema. Nothing of a stage lives
   outside its folder.
2. A package is a **uv workspace member** with its own `pyproject.toml`. What it imports, it declares. Undeclared is an error, not a warning.
3. Shared things are **packages too**, and a stage inherits them by declaring them: `kernel` (types and ports every stage speaks), `testkit`
   (fixtures, layer guards), `rules` (lint, type and import-rule bases). No file is copied between packages.
4. **Stages never import stages.** They meet in the `compose` root (the engine wiring) and in `kernel` contracts. A cycle is a design error.
5. A stage's constructor takes **small ports and values**, never a host: no `Any`-typed parameter, no engine, no `run`-wide state object.
6. A round **returns** what it decided (a `RoundResult`); the caller applies it. A stage assigns nothing on another stage's object.
7. A stage's **prompts are its own** (`<stage>/prompts/*.md`, package data). `domain/prompts` stops being a bucket.
8. A stage owns its **data** (its tables or checkpoint part). Others read through its port. The launch check refuses a missing part.
9. A package's tests run **alone, in a fresh environment built from its declared dependencies**. Passing there is the proof of isolation.
10. The gate runs the tests of **the packages a change reaches** (reverse dependency closure over the declared graph) and each package's rules.

## 1. What the spikes showed (toy workspace, uv 0.13, ruff 0.17, import-linter, pyrefly 1.4; all reproducible with the script in section 8)

| question | result | so |
|---|---|---|
| Does a package run its tests in an environment of only its own declared dependencies? | yes: `uv run --isolated --package P --group dev pytest packages/P`, 0.7 s warm. | the isolation test is free and exact |
| Does that catch an undeclared import (stage `land` imports stage `gate` without declaring it)? | yes: `ModuleNotFoundError` in `land` alone; `gate` passes. | no custom rule is needed for undeclared imports |
| Does a shared test kit reach every package without copying? | yes: `testkit` registers a `pytest11` entry point (fixtures, a layer marker, later the CPU and no-sleep guards); each package lists `testkit` in its `dev` group and gets them. | the layer guards of tests/conftest.py become one package |
| Do prompts survive as package data, installed non-editable? | yes: `files("tlgate").joinpath("prompts/review.md")` worked under `--no-editable`. | prompts move into stages with no loader change |
| Can a dependency pin live once? | yes: root `[tool.uv] constraint-dependencies = ["msgspec==0.19.0"]`; packages say `msgspec`, the one lock pins it. | one pin, many members, no PEP 723 copy drift |
| Do lint rules inherit? | yes: root `ruff.base.toml`; `ruff.stage.toml` does `extend = "ruff.base.toml"` and adds ANN401 and TID251; a stage's `ruff.toml` is one line `extend = "../../ruff.stage.toml"`. Result: ANN401 fires on `host: Any` in a stage and not in the kernel. | the host ban is a rule set a stage inherits, and a new stage cannot forget it |
| Can the "stages never import stages" rule be one contract? | yes: one import-linter `independence` contract over the stage list reported `land -> gate` with its line. | one contract, a list that grows with the stages |
| Can `dev/affected.py` (an AST import graph over the whole tree) be replaced? | yes for packages: reverse closure over `[project].dependencies` gave `kernel -> all`, `gate -> gate only` in 20 lines, reading no source. | see section 5 |

Not spiked, and said so: pyrefly per package (it runs from the root with `project-includes`; the per-package split is a config line, to confirm in
the first real PR), a git-URL source for `testkit` from a second repository (uv supports it; the first outside user proves it).

## 2. Layout

```
packages/
  kernel/    contracts, ports, ids, RoundResult, RunFacts. Imports nothing of ours. Every stage depends on it.
  testkit/   pytest plugin: fixtures (clock, workdir, gitsim, procsim), layer guards, the ratchet helpers. No stage code.
  rules/     ruff.base.toml, ruff.stage.toml, the import-linter contract generator, the gate rule tests (caps, placement). Data and tests only.
  plan/ write/ review/ look/ land/ ...    one stage each
     pyproject.toml   name, dependencies (kernel, msgspec, ...), dev group (testkit)
     ruff.toml        one line: extend = "../../packages/rules/ruff.stage.toml"
     src/<stage>/     code, prompts/, schema.py (its data), ports.py (what it needs from others)
     tests/           unit (memory + fakes), real/ (its adapter, once), nothing wider
  compose/   the engine: wires stages by their ports. The only package that imports several stages.
  cli/ dash/ delegate/   already their own pieces
```

The skill still starts from `skills/task-loop/tl.py`; the workspace changes where code lives, not how a session runs it. Decided by the
owner (2026-11-07): **plan, write, review and look are four packages**. They share `StageState` today, but that state
is a value the loop passes (kernel), not a reason to share a folder. The hand-off work (ROUNDRESULT) lands first.

## 3. Inheritance, so nothing is copied

| thing | lives in | a stage gets it by |
|---|---|---|
| lint set, line length, complexity | `rules/ruff.base.toml` | `extend` chain, one line in the stage's `ruff.toml` |
| host and `Any` ban | `rules/ruff.stage.toml` (ANN401) plus the contract in section 4 | the same chain; a stage cannot opt out without a visible `noqa` that the ratchet counts |
| test layers, CPU limit, no `time.sleep`, fakes | `testkit` plugin | `testkit` in the `dev` group |
| ports and fakes of git, process, clock | `kernel` ports; `testkit` fakes; one contract suite in `testkit` runs against both | declaring both |
| dependency pins | root `constraint-dependencies` | packages list names only |
| python version, workspace members | root | automatic |
| import rules (layers, independence, banned modules) | `rules` generates `.importlinter` from the member list and each package's declared layer | `just rules` |

Rule of thumb: if two packages need the same text, it is a base file or a package. A copy of a rule in two stages is a defect that a rule test
finds (the stage `ruff.toml` may contain only `extend` and package-local `per-file-ignores`, none for tests: same as today's gate rule).

## 4. Banning the host

Three layers, each cheap, each mutation-tested when it lands (HOSTBAN, tl-e5t0.61):

1. **Types**: ANN401 (inherited): no `Any` annotation, so `host: Any` cannot be written in a stage.
2. **Imports**: a forbidden contract: no stage imports `compose` (the engine class lives there). A typed `Engine` parameter is as bad as `Any`.
3. **Names**: a rule test over each stage's constructors: a parameter named `host`, `e`, `eng`, `engine` or typed as a class that has more than
   N public attributes fails. A stage takes ports (`Clock`, `Git`, `Store`) and values (`RunFacts`).

During the move, each stage's remaining hosts are listed in the bead and shrink by PR; the type-escape ratchet already refuses net-new `Any`.

## 5. Tests and selection

- **Per package, in isolation**: `uv run --isolated --package P --group dev pytest packages/P`. A package's tests may import only P, `kernel`
  and `testkit`. A test that needs two stages belongs to `compose` (the wiring test) or to e2e (at most 10).
- **Which packages**: the reverse closure of the changed packages over the declared graph (spike F). A kernel change reaches every package; a
  leaf stage change reaches itself and `compose`. This replaces the AST selection **per package**; `dev/affected.py` stays for the monolith until
  the last stage moves, then it is deleted (it cannot be wrong about a graph the manifest states). Files outside a package (root config, `rules`)
  select everything, as `tests/rules` does today.
- **Cheaper still, later**: key each package's result by a hash of its folder plus its dependencies' hashes; an unchanged key is not run. It is
  the same closure, made cacheable, and it is what a second repository needs most (CI-free "the factory is the CI").
- **The budget** (120 s CPU, layers, ratchets) stays; `testkit` carries the guards, so a new package inherits them instead of copying
  `conftest.py`.
- The tests that tangle today (the engine as the base of every test, measured: a change to `engine.py` selects 179 tests) move to fakes of the
  ports, as the checks tests already did (192 to 179, checks files 25 to 1). The engine is tested only by `compose`.

## 6. Data and prompts

- **Prompts**: each stage owns its prompt texts and the code that builds them (`src/<stage>/prompts/`). A prompt shared by two stages is a sign
  of a missing contract: the shared part goes to `kernel` as a named fragment with one owner, never as a copy. PROMPTS (tl-e5t0.62) moves them
  stage by stage, with a golden test per prompt so a move cannot change a byte.
- **Data**: each stage owns its record types and its part of the checkpoint (per [stage-isolation.md](stage-isolation.md) section 3: part
  registry, launch check, CloseIntent; checkpoint format last). No file fallback: factory.db is the state.
- **Schema versions** live with the stage; the kernel only routes them. A stage changing its part cannot break another stage's tests.

## 7. Plug and play (the long term, designed now, built later)

A stage is a package that exports one thing: a `Stage` object (name, the ports it needs, the ports it provides, its prompts, its data part,
its entry function). `compose` reads a profile (`.task-loop.json`, a new key ships one release after the reader) that lists the stages to use,
checks that every needed port is provided, and wires them. "Use this set of stages from those packages" is then a list in a file, and the launch
check says which port is missing. This needs no new mechanism beyond sections 2 to 4; it needs the `Stage` contract, which the first real
spike (WORKSPACE, tl-e5t0.65) writes down from one leaf stage.

For other repositories: `kernel`, `testkit` and `rules` are the only things a second repository must take; they are plain workspace packages and can
be consumed as git sources. The stages stay in this repository until a second user exists. Nothing here needs publishing to a registry.

## 8. Decisions and order of work

| decision | status |
|---|---|
| Stage = workspace member with everything inside; `src/taskloop/<stage>` is not the home | decided by the owner |
| Inheritance by `extend`, entry-point plugin and `constraint-dependencies`; no copies | decided here, spiked |
| Host ban in three layers (types, imports, names) | decided here |
| Prompts and data move into their stages | decided by the owner |
| Selection by package graph; `dev/affected.py` retired when the last stage moves | decided here |
| plan/write/review/look: four packages | decided by the owner |
| `kernel` split (what is a contract, what is a port) | WORKSPACE spike, then one bead per move |

Order (each PR small, reversible, hot code accepted): ROUNDRESULT (.60, in progress: returns replace field writes) -> WORKSPACE (.65: root
`pyproject`, `kernel`, `testkit`, `rules` and one leaf stage moved, the numbers measured) -> HOSTBAN (.61) -> PROMPTS (.62) -> DOCTORENV (.64:
`tl doctor` checks bd, uv, the toolchain pins) -> TESTISO (.66: per-package runs and selection) -> the remaining stages one by one (B-WRITE, B-PLAN,
B-LAND, C-*) -> D-DB (after #219 and #232).

Spike script: the toy workspace is rebuilt by the steps in this section's tables; it is 4 members, 60 lines, and every row of section 1 is one
command (`uv run --isolated --package`, `ruff check`, `lint-imports`, a 20-line closure script). It is not committed; WORKSPACE redoes it on the
real tree and commits the result.

## Adding a member: the checklist

Use folder `packages/<stage>`, project `tl<stage>`, and import root `tl<stage>`.
Each member still needs entries in:

- `ruff.toml` `src`.
- `pyrefly.toml` `search-path`.
- `.importlinter` `root_packages` and its package contract.
- The converted-stages contract when the stage is converted.
- The carve's own narrowed ConfigDir imports (tl-1nbh, ARCHVERT-PATHS-B): take a typed per-stage dir (or a Path) from the composition root
  instead of importing `tlkernel.paths.ConfigDir`, so editing `tlkernel/paths.py` stops selecting half the suite; acceptance: `dev/reach.py`
  shows the stage's tests no longer reached through `paths.py`.

The rules and mutation tools' Python paths, affected-test scan roots and visibility, production architecture trees, and package selection now discover `packages/*/src` or member manifests automatically. `just test-pkg <stage>` detects a member manifest and runs its isolated environment.

Dash is carved into `packages/dash` (`tldash`), with isolated package tests.
