# LANEPURGE: the file count and the cut order (tl-w7lt.38.11)

Design note only; no code moves with it. The names are fixed by `docs/glossary.md` and `docs/design/naming-audit.md`: delegate lane -> account, check lane -> track, factory lane -> loop, Floor tab -> Slots. This note adds the measured size of the edit and where it has to be cut so each piece lands green.

## Size (word-boundary and compound matches of `lane`, 2026-11-06, origin/main)

| area | files | lines |
|---|---|---|
| src/taskloop | 106 | 463 |
| packages/dash/src/tldash (py + static js/css) | 29 | 131 |
| src/delegate | 43 | 785 |
| skills/ (SKILL.md, tl.py, _vendor) | 10 | 54 |
| tests (tests/delegate 107 and tests/fixtures 59 files in the plain `lane` count) | 289 | 2318 |
| docs/design, dev, contracts, glossary, README | 38 | 408 |
| docs/architecture, docs/review (history; excluded by the bead) | 39 | 536 |

About 515 files and 4,160 lines outside the history docs. The three meanings split the work unevenly: nearly all of delegate and the dashboard's Lanes panel are *account*; `checks[].lane` (config, checks contract, runner, profile docs) is *track* and small; *loop* is `factory-lane-K.log`, `LANES running=`, `idle_lanes`, `lane_out`/`PassEnd`, and the loop slice.

## What is persisted (a rename here is a migration, not a find-and-replace)

1. **Profile key** `checks[].lane` in each repo's `.task-loop.json`: a hard cut to `checks[].track` (CLAUDE.md: unknown keys are refused). Reader and profiles use only `track`, with no old-key reader.
2. **delegate routing.json** `lanes{}` and `history.jsonl` rows with `"lane"`: the owner's own files. Delegate is a library in this repo now, so one cut renames reader and writer, plus a one-time rewrite of `routing.json` by `delegate` itself (no alias, per the bead). Old history rows keep `lane`; readers of history must not crash on them.
3. **Log records and factory.db**: `Evidence`/`CallEnd` carry `lane` (`contracts/agent.py`, `log.py`), `PassEnd` has the value `lane_out`, `Checkpoint.fallback_lane`, `ReasonNoLane`. Engine logs are append-only and rotated; renaming a field needs the reader to accept the old name for as long as old logs exist, which is the one place a no-alias rule costs something. Proposal: bump the record version where a field is renamed and let `wire` read both versions (the wire layer already versions records), with the old reader deleted when the 7-day log window has rolled.
4. **Files and env**: `factory-lane-K.log` -> `factory-loop-K.log` (the doctor and the dashboard find them by name), `TL_*` names containing LANE (none found in src; confirm in skills/).
5. **Dashboard JSON** (`contracts/dash.py`: `lanes`, `LaneCard`, `lane` on rows) is served and read by the same release, so it needs no compatibility.

## Cut order (each step is a PR that passes `just test` alone)

1. **TRACK**: `checks[].lane` -> `track` throughout check execution and contracts. Hard cut: the old key is refused, with no alias or compatibility reader.
2. **LOOP**: factory log names, `LANES running=`, `idle_lanes`, `lane_out`, `first_lane`/`fallback_lane` where they mean a loop, the loop slice and its tests. Mostly private names.
3. **ACCOUNT, delegate side**: `src/delegate` + `tests/delegate` + routing.json rewrite; `delegate.api` names (`Account.lane` -> `Account.name`). The one wide step: about 150 files, almost all mechanical.
4. **ACCOUNT, task-loop side + dashboard**: `domain/lanes` -> `domain/accounts`, `tl lanes` -> `tl accounts`, Lanes panel -> Accounts, Floor -> Slots, contracts/dash, static js, SKILL.md.
5. **TRACK, profiles**: rename the key in the repos' `.task-loop.json` together with their consuming release; the old key is refused.
6. **Rule**: a rules test that fails on `lane` as a word in src, skills, tests and docs outside `docs/architecture` and `docs/review` (allow the `lane:` label prefix the bead names). Land it last so the intermediate PRs stay green; add the allowlist of still-open directories to each earlier PR and shrink it as they land.

## Risks and calls for the owner

- Steps 3 and 4 touch the same files as any in-flight stores or delegate work (#224 touches `src/taskloop/app/*`); do them when the queue is empty, one at a time, never in parallel lanes of work.
- Data in `routing.json` and `history.jsonl` lives on both machines (devbox and the Mac). The rewrite must run on each, by `delegate` at start.
- Whether old log records are read for seven days or rewritten is the one design call; reading both is cheaper and loses nothing.
