# FACTS: RunFacts and the shared ports (tl-e5t0.28)

Design and slicing; no engine code moves with this note. Follows `stage-isolation.md` section 1.1 (a)/(b) and `attr-map.md` (the 16 data fields and 11 ports). Checkpoint on disk unchanged. Checked against origin/main, 2026-11-06.

## What the code holds (verified)

`Engine.__init__` (`app/run/engine.py:50-110`) knows these facts in this order, which decides where a frozen object can be built:

| step | known after | fields |
|---|---|---|
| 1 | the edge | `env`, `spawner`, `git`, `who`, `home` |
| 2 | `RunFields.__init__` (`fields.py:76`) | `bead`, `cfg`, `dry`, `claim`, `wt`, `fresh`, `store` |
| 3 | stores | `clock`, `stores` |
| 5 | `RunLayout.open` | `run_id`, `run_dir`, `task_dir`, `brief_file`, `evidence_dir` (and `repo_of(git, wt)`, today not kept) |
| 6 | `RunContext.open` | `log`, `steps`, `checklog` |
| 7 | `Checker(self, ...)` | `checker` |
| 2 (earlier) | `Checkpoints(self)` in `land_fields()` | `checkpoints` |
| **later** | `RunOnce.begin` (`run_once.py:133`), again in `stages.py:125` | `bead_title`, `bead_parent` (from `bd show`) |
| **lazily** | the first registered render (`ask_flow.py:45`) | `artifact_repo` (`repo_key(git, wt)`, then cached) |

So three of the 16 data fields in ATTR-MAP are not facts at engine open: `bead_title` and `bead_parent` are read from bd by the first step and assigned onto the engine, and `repo` is not an attribute at all (`repo_of(git, wt)` is computed inside `RunLayout.open` and thrown away; `closer_decide.repo_id` and `ask_flow.repo` recompute it). `now` is a method (`plumbing.now`, the clock's `now`), not data. `artifact_repo`, which the bead notes add, is a memoised value written by `ask_flow`.

## Shape

```
contracts/runfacts.py
  @dataclass(frozen=True, slots=True)
  class RunFacts:                      # data nobody writes after the engine opens
      bead: BeadId; wt: str; cfg: EngineConfig; home: ConfigDir
      run_id: str; run_dir: Path; task_dir: Path; brief_file: Path; evidence_dir: Path
      repo: str; dry: bool; fresh: bool; claim: Claim
  @dataclass(frozen=True, slots=True)
  class BeadInfo: title: str; parent: str      # known at begin, handed to the stages that run after it

  class Narrate(Protocol):  note(text) -> int; warn(text) -> int               # RunLog's two verbs a stage uses
  class StepBook(Protocol): id; begin(step, text, **meta) -> int; outcome(o, detail=""); end(o=""); move(to, cause, detail="")
  class RepoKey(Protocol):  key() -> str                                       # artifact_repo, computed once on first call
```

The 11 ports of ATTR-MAP keep their names and become the typed handles of one `RunPorts` (frozen, references to the engine's own objects), with the Protocol each stage may ask for:

| ATTR-MAP port | today's object | Protocol a stage takes | lives in |
|---|---|---|---|
| clock | `SystemClock` / `FakeClock` | `Clock` | `contracts/ports.py` (exists) |
| env | `Env` | `Env` (a record) | `contracts/env.py` (exists) |
| git | the git adapter | `Git` | `contracts/gitport.py` (exists) |
| spawner | `RealSpawner` | `Spawner` | `contracts/procport.py` (exists) |
| steps | `Steps` (`app/run/steps.py`) | `StepBook` | new, `contracts/runfacts.py` |
| log | `RunLog` (`stores/runlog.py`) | `Narrate` (note, warn); `emit` stays with the pipeline | new |
| checklog | `CheckLog` (`app/checks`) | `CheckLog` Protocol (checks already declares it for `CheckHost`) | moves to contracts with its consumers |
| store | the bd store | `Beads` | `contracts/beadsport.py` (exists) |
| stores | the `Stores` bundle | `Stores` | `contracts/stores.py` (exists) |
| checkpoints | `Checkpoints` (`app/run/state.py:102`, takes the engine) | `CheckpointsPort` (read, save, the `keep_*`) | new; the class stays in `app/run` |
| checker | `Checker` (`app/checks/runner.py`) | `CheckerPort` (`run_checks`) | new; the class stays in `app/checks` |

`contracts/` may not import `app/` or `stores/` (import-linter `layers`), which is why `Narrate`, `StepBook`, `CheckpointsPort`, `CheckerPort` are new Protocols and not the classes. The Engine satisfies them structurally; no class changes.

## Where it is built

At the end of `Engine.__init__` (after step 7), once: `self.facts = RunFacts(...)` from the attributes the engine already holds, and `self.ports = RunPorts(...)`. Nothing is moved or removed from the engine: the stages are not migrated, so every existing `e.bead`, `e.log` read stays. `facts` is the new read path that B-LOOK slices 2-3, B-REVIEW, B-LAND, ASKAI slice 3 and C-WORKERS take.

Frozen means the references and the data cannot be rebound; the ports are live objects (a `RunLog` appends). A test pins both: `dataclasses.FrozenInstanceError` on assignment, and `facts == facts_again` between two reads.

## The three places where a fact is not a fact

1. **`bead_title`, `bead_parent`**: read at `begin`, after the engine is built. Not RunFacts. `BeadInfo` is built by `begin` and passed to the steps that run after it (`RunOnce` already holds the bead there); the engine keeps its two attributes until the stages that read them (`write`/`plan` prompts, `ask_flow`) move. Alternative, if an owner prefers one object: build `RunFacts` after `begin`. That makes the facts not available to `begin`'s own callees (the delegate route and the claim check read `bead`, `wt`, `cfg`).
2. **`artifact_repo`**: a lazy cache written by `ask_flow` (`e.artifact_repo = e.artifact_repo or repo_key(...)`). Frozen data cannot hold it. `RepoKey.key()` computes `repo_key(git, wt)` on first call and returns the same string after (the engine's own memo is the implementation). Eager computation at open would call git for every run, including runs that never render.
3. **`repo`**: `RunLayout.open` already computes `repo_of(git, wt)`; keep it (one new field on the engine, no extra git call).
4. **`now`**: dropped as data; `clock.now()` is the port. A stage that wants a time takes `Clock`.

## Slices (each a PR that passes `just test` alone; no stage migrated; no checkpoint change)

1. **Types.** `contracts/runfacts.py` (`RunFacts`, `BeadInfo`, the Protocols above), `CheckLog` Protocol moved to contracts (the one existing consumer is `app/checks/host.py`). `tests/support/facts.py`: `fake_facts(workdir, ...)` builds a `RunFacts` and `RunPorts` from `FakeClock`, `fake_stores`, a gitsim, an in-memory step book (the pieces `FakeCheckHost` already builds). Unit tests: frozen; each Protocol has a fake in the support module.
2. **Engine builds it.** `Engine.facts` / `Engine.ports` at the end of `__init__`, and `RepoKey` over the engine's memo. Conformance test `tests/run/test_facts_contract.py` runs the same probes on the real Engine and on `fake_facts` (`host_conformance.missing` for the members, plus behaviour probes: `steps.begin` returns an id, `log.note` appends a row, `repo.key()` is stable); a mutation of the fake (drop a verb, return a different repo key) must fail it, as in #285.
3. **The checks pilot reads it.** `CheckHost` becomes the subset it needs of `RunFacts` + ports (`bead`, `wt`, `run_id`, `run_dir`, `home`, `cfg`, `log`, `steps`, `checklog`, `stores`, `spawner`, `env`), `FakeCheckHost` shrinks to a `fake_facts` call. Optional in this bead; it is the proof that the shape is enough for a real stage.

## Acceptance criteria (for the bead, replacing the one-liner)

- `RunFacts`, `BeadInfo`, `Narrate`, `StepBook`, `RepoKey`, `CheckpointsPort`, `CheckerPort` exist in `contracts/`; import-linter `layers` and the new `nobody-imports-a-root` contract hold.
- The Engine's `facts`/`ports` equal what its attributes hold (`facts.run_id is engine.run_id`, `ports.log is engine.log`); a test sets none of them after `__init__`.
- The conformance test fails when a fake drops a verb or lies about a fact (mutation shown in the PR).
- No stage, checkpoint record, or engine attribute is changed; `git diff` touches no file under `app/plan|write|review|look|land` and none of `contracts/checkpoint.py`.
- `just check` and `just test` green; files under 400 SLOC; no new `Any`, `cast` or ignore.

## Owner decisions, with a recommendation

1. **`bead_title`/`bead_parent`: a separate `BeadInfo` from `begin`, or build `RunFacts` after `begin`?** Recommend `BeadInfo`: the facts are then available to `begin`'s own callees and stay frozen at open.
2. **`artifact_repo` as a `RepoKey` port (lazy), or eager?** Recommend the port; eager costs a git call for every run.
3. **Are the 11 ports concrete handles, or Protocols per stage?** Recommend Protocols named for the capability and defined by the consumer (`Narrate`, `StepBook`, ...); `RunPorts` holds the handles, a stage declares the Protocol it takes. This matches stage-isolation 1.1 (b) and keeps contracts free of app classes.
4. **Slice 3 (the checks pilot on the facts) in this bead or after?** Recommend in: it is the only proof that the shape is complete before four stage beads depend on it.

## Not verified

The `Claim` type's mutability (`fence.Claim`, not found at the path ATTR-MAP implies) and whether `fresh` changes after open were not read; slice 1 starts by reading both. The step-order table is from reading `engine.py` and `fields.py`, not from running the engine.
