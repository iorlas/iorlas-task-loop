# Engine attributes by reads and writes (ATTR-MAP, tl-e5t0.56)

Measured by `dev/attrmap.py` (AST, no execution; rerun it before and after each stage conversion). It replaces the "which dirs mention it"
count in `stage-isolation.md` section 1, which section 7 point 5 had already marked unreliable.

An attribute is every name the `app/run` classes assign on `self` (186). Reads and writes count `self.X` inside `app/run` and `e.X` / `eng.X` /
`engine.X` / `host.X` / `h.X` anywhere in `src`, per stage (`dev/reach.py`'s table). Generic names (`key`, `kind`, `t`, `n`, `name`, `text`, `why`,
`cwd`) also match other classes' receivers named `h` or `host`, so they read wider than they are; they are all run facts or shell-private.

## Result

| class | count | meaning | design consequence |
|---|---|---|---|
| private to the shell | 92 | touched only by `run/launch/loop/wire/prune` | stay on the Engine; the thin root splits them later (C-THIN) |
| private to one stage | 24 | work 13, land 9, gate 2 | move into that stage's own `State` (FACTS, B-*) |
| run fact | 58 | written only by the shell (at open or per step), read by 2+ stages | `RunFacts` / small ports, constructor-injected |
| hand-off | 5 | written by one stage, read by another | return values between stages (CloseIntent for those the close needs) |
| shared | 7 | written by 2+ stages | one owner each; the rest read the owner's value |

So 116 of 186 attributes (62%) have one user; the "232 attributes, 37 in 4+ dirs" fear came from counting mentions, not writes.

## The 12 that cross a stage boundary

Hand-offs (writer -> reader):

- `branch`, `landed_sha`, `unverified`: land writes, work reads (the look verdict and the close text). Land returns them; the pipeline hands them to close.
- `last_run`, `stuck_why`: work and shell write, land reads. A stage input, not shared state.

Shared (written by land, work and the shell; read by work): `amend_text`, `amend_why`, `amended`, `last_summary`, `old_plan`, `plan_summary`,
`unchecked`. All are one family, the amend/replan loop. They become a single `AmendState` owned by plan, with land receiving it as an input and
returning a changed copy. This is the one place where a stage needs another stage's writable state today; it is the work for B-PLAN and B-LAND.

## Run facts (read-only for stages)

`bead`, `bead_parent`, `bead_title`, `cfg`, `wt`, `repo`, `home`, `run_id`, `run_dir`, `task_dir`, `evidence_dir`, `brief_file`, `dry`, `fresh`,
`claim`, `now`, `clock`, `env`, `git`, `spawner`, `steps`, `log`, `checklog`, `store`, `stores`, `checkpoints`, `checker`. These are the `RunFacts`
fields (16 data fields up to `now`) plus 11 ports (`clock`, `env`, `git`, `spawner`, `steps`, `log`, `checklog`, `store`, `stores`, `checkpoints`, `checker`). The other run facts are per-step counters the
shell updates and work reads (`write_rounds`, `look_retried`, `link_*`, `budget`, `shots_skipped`, `verify_answer`, `verified`, `answered`,
`account_notes`, `last_flag`, `sessions`, `writer`, `stats`, `filed`, `scope`, `detail`): they belong in work's `State`, written by the shell only
because the shell runs the loop; B-WRITE and B-REVIEW move them.

## What this changes in the plan

- The conversion order stays. The first host to become small is gate (2 private, no hand-off) then land (9 private, 3 hand-offs out).
- `RunFacts` is 16 data fields plus 11 ports, not 232 attributes: FACTS is feasible as one PR.
- The amend family (7 shared) is the one design question left for B-PLAN: confirm `AmendState` owned by plan before B-LAND starts.
