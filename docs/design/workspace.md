# Workspace spike: which stage moves first, and what the kernel has to hold (tl-e5t0.65)

Status: measured, not yet moved. It turns [stage-packages.md](stage-packages.md) section 8 into a first PR list. Method: an AST scan of every
import in `src/taskloop` (script in this PR's description, 40 lines), grouped by app slice; the tests of the pilot read the same way.

## 1. Slices by what they import (non-stage dependencies are "below": contracts, domain, adapters, stores)

| slice | LOC | imports other app slices | below |
|---|---|---|---|
| artifacts | 414 | none | contracts |
| track | 444 | none | contracts |
| doctor | 285 | none | contracts, adapters |
| asks | 1038 | none | contracts, domain |
| **review** | 807 | none | contracts, domain, adapters |
| slots | 1260 | none | contracts, domain, adapters, stores |
| checks | 2142 | none | contracts, domain, adapters, stores |
| look | 766 | artifacts | + stores |
| plan | 1326 | asks | no stores |
| write | 1136 | artifacts, asks, checks | contracts, domain |
| land | 3624 | asks, checks, slots | all |
| run | 6769 | 14 slices | all (the composition root) |

Reading: seven slices are leaves already. `run` is the only slice that imports the stages, which is the shape stage-packages.md wants
(`compose` is the only package that imports several stages). The three "work" stages that Denis named import one or two leaves each, so they move
after `asks`, `artifacts` and `checks`, which become packages first.

## 2. The pilot: review

Chosen because it has no app dependency, 807 LOC, its host is already a typed `ReviewHost` (B-REVIEW), and its state is `ReviewLive`. Its
whole outward need is:

- contracts: `wire.Open`, `gitport.Git`, `stop.Stop`, `slots.SlotGitError`, `plancheck`, `config.EngineConfig`, `ids`, `checks`, `asked`, `answers`
- domain: `review/*` (it owns these: findings, ledger, matchers, skip, switch, kinds, visual), `followups`, `checks.planref`, `asks.specs`,
  `plan.matchers`, `matchers.clip`, `prompts.common`
- adapters: `links`

That is the kernel's first cut: the contracts above plus the two or three domain helpers shared with other stages (`matchers.clip`,
`followups`, `prompts.common` fragments). `domain/review/*` moves INTO the package; it is review's alone.

Its tests (`tests/review`, 12 files) import `app.wire`, `app.run` and `support.engine_case` in a handful of files: those files test the engine
with review, not review. They go to `compose` (the wiring test) or are rewritten on `FakeReviewHost`, as the checks tests were (192 to 179 selected).

## 3. First PR list (each small and reversible)

1. WORKSPACE-1: root `pyproject` becomes a workspace (`members = ["packages/*"]`), `packages/testkit` (the layer guards from tests/conftest.py as a
   pytest plugin) and `packages/rules` (ruff base files, the generated import-linter contracts). Nothing else moves. Proof: `just test` unchanged.
2. WORKSPACE-2: `packages/kernel` = the contracts above plus `ids`, `wire`; the old `tlkernel` stays a thin re-export for one release.
3. WORKSPACE-3: `packages/review` = `app/review` + `domain/review` + its prompts and tests; its `pyproject` declares kernel and testkit only;
   `uv run --isolated --package review pytest packages/review` must pass alone.
4. Then in order: asks, artifacts, checks, slots (leaves), look, plan, write, land; `compose` is what remains in `run`.

Each step has one measurable gate: the package's isolated run passes, `just test` selection for a change inside it shrinks to its own tests.

## 4. The stage contract (what a package exports, for plug and play)

```python
class Stage(Protocol):
    name: str
    needs: tuple[type, ...]       # the ports it takes (Git, Clock, Store, ...)
    provides: tuple[type, ...]    # the ports it offers other stages
    data: type | None             # its part of the checkpoint
    def build(self, ports: Ports) -> object: ...   # constructor injection, no host
```

`compose` checks `needs` against the other stages' `provides` on launch and wires them; a missing port is a launch failure naming the port.
Prompts and schema versions are attributes of the package, not of the contract.

## 5. Not done, said plainly

No file moved on the real tree and no workspace was created in it; the numbers above are an import scan, and the isolated-run proof is the toy
workspace of stage-packages.md section 1. The first real proof is WORKSPACE-3, which can fail on a hidden import (a test reaching `support`
fixtures that need the engine); that is why review goes first and alone.
