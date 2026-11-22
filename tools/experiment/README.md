# tools/experiment: run an A/B experiment from a frozen spec

Not a `tl` command. It builds N arms from a frozen base commit and task texts, block-randomizes them, runs them with N in
flight, and writes `results.json` and a `report.md` skeleton. It replaces the ad-hoc runners
(`docs/design/tl-7125/experiments/pilot5/run6.py`, `pilot6/run7.py`, `pilot7/run8.py`).

```bash
uv run --frozen --no-sync python tools/experiment/experiment.py plan SPEC.json    # print the randomized order, build nothing
uv run --frozen --no-sync python tools/experiment/experiment.py run SPEC.json     # build, run, collect, report
uv run --frozen --no-sync python tools/experiment/experiment.py report SPEC.json   # re-render report.md from results/
```

Run it from a checkout of this repo (the toolkit's own `.venv`); the `engine` it tests is another checkout with its own
installed `.venv`, frozen for the whole experiment. Real agents run: it spends tokens. Nothing is ever landed
(`land: manual`) or pushed outside the run's local bare origin.

## Spec (JSON; relative paths are relative to the spec file)

```json
{
  "name": "pilot8",
  "source": "/path/to/repo",
  "base": "<frozen commit sha, reachable from a ref of source>",
  "engine": "/path/to/engine-checkout",
  "work": "/tmp/aa/pilot8",
  "tasks": [{"id": "tl-p8a", "title": "…", "text_file": "tasks/tl-p8a.txt"}],
  "arms": {"a": {"workflow": "default", "efforts": {"implement": "medium"}},
           "b": {"workflow": "default", "efforts": {"implement": "low"}}},
  "seed": 8,
  "in_flight": 2
}
```

Optional: `repo_name` (default `aa`), `label`, `backlog`, `wall_minutes` (45), `attempt_minutes` (40), `round_seconds` (15).
Keep `work` short: the factory refuses a slot path over 64 bytes, and the toolkit refuses first, with the length.

## What one run is

Folder `work/runs/<task>_<arm>/`, never reused (an existing folder is a refusal): a local bare origin `<repo_name>.git` with
`main` at `base`, a clone, one managed slot, its own tracker holding the task under the **same id in every arm**, its own
`factory.db`, artifacts and slots, and one neutral commit on `main` shared by all arms: `.task-loop.json` with `land: manual`
and every check command run under `env BEADS_DIR=<empty external tracker>` (the repo's gate needs a bd database; an
inherited `BEADS_DIR` also breaks `bd init`, so bd calls drop it). `MISE_TRUSTED_CONFIG_PATHS` includes `work`.

The run is one `tl rounds start --exit-when-idle`: it ends by itself when nothing is left to do, so there is no polling and
no pid stop. The wall cap (`wall_minutes`) stops that process tree through the process library and is its own outcome
(`cap:wall`). There is no token cap: it would need polling; bound cost with `wall_minutes` and `attempt_minutes`.

Outcome comes from state (`tl attempt list`), never from logs: `pass` (waiting to be landed), `held`, `incomplete`,
`cap:wall`, `infra` (setup or the rounds process failed; the detail says why). Evidence per run: `tl attempt export --json`
rows, the numstat and patch of `origin/task/<id>` against the arm's base (`work/diffs/`), host load at start and end, and
the planned in-flight count.

## Method standard (from the experiments README)

- Freeze engine, base commit, task text, workflow digests and efforts; the report header records them.
- Block-randomized pairs: one run of every arm per task, random order inside the block, seeded and recorded in `order.txt`.
  At most two in flight (`in_flight`); record in-flight count and host load per run.
- Screen every task before the first run: it must not need an edit to a protected file (public-surface snapshot, DDL hash,
  import contracts, repeated-string census, shelf pins, workflows).
- Calibrate with one run, then one pair, before any larger run; agree the acceptance window and cost up front. Size the wall
  cap from a measured check cycle.
- Report repeats as the denominator for any feedback comparison; uncached and cached input separately; plan and implement
  separately. Holds and caps are results, never dropped. Unknown is not zero: a run with an unknown value is left out of that
  row and `n` says how many remain.
- Keep the per-run results JSON, not run trees. Read every number as exploratory.

## Layout

`experiment.py` (command line), `exp_spec.py` (spec and result models), `exp_order.py` (randomization), `exp_arms.py`
(arm building over one process port), `exp_run.py` (runs, verdict, evidence), `exp_report.py` (statistics and markdown).
Tests: `tests/steps/test_experiment_tools.py` (a fake process port; no live agent, no git, no bd).
