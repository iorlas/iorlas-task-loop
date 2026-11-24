# Live run 1: shipped features on a throwaway repository

Date 2026-11-24. Built from `experiments-pilot89` (HEAD a0c47374e, schema v39). One task ("add `goodbye()` to `hello.py`"),
codex harness, model `gpt-6-luna`, plan and implement effort `low`, one round chain (plan, implement, check). Throwaway
local bare origin and a throwaway bd database under `/tmp/l1`; no owner data, no push to the real remote. Land is `manual`.
Token use of the whole run: 3 agent attempts, about 270k input (about 200k cached), about 2.6k output.

## Result

| # | feature | result | evidence | defects |
|---|---|---|---|---|
| 1 | `rounds start --exit-when-idle` ends itself | worked with 2 slots; FAILED with 1 slot | 2 slots: `rounds stopped idle`, "tl rounds start: idle", exit 0. 1 slot: the task passed and waited to land, every round reported `stopped=slot_for_land`, and the process was still running after 3+ minutes (killed by its own pid) | D1 |
| 2 | tracked task branch, push, secret scan | branch and push worked; secret scan not reached | `origin.git` has `task/live-3sl` (8e2861d, 3 commits over `main`); local `task/live-3sl` upstream is `refs/remotes/origin/main` (new branch tracks origin main, as `docs/glossary.md` "task branch" says). The throwaway profile has no secret-scan check, so none ran | none; scan needs a profile check (not exercised) |
| 3 | per-step effort flags | worked | `--plan-effort low --implement-effort low` accepted and recorded (`effort=low`, `ran_effort=low` in the export). `--plan-effort bogus` refused before any agent run, for `rounds start` and `config show`: "effort 'bogus' is not accepted by codex model 'gpt-6-luna'; it accepts low, medium, high, xhigh, max" | none |
| 4 | reasoning tokens in `attempt export` | worked | `t_reasoning` is 0, 234 and 0 for the three attempts (non-NULL; the harness reported it). A plan attempt with 234 reasoning of 1008 output tokens | none |
| 5 | `tl drain` export and sticky drain | worked | prints `Attempt export /tmp/l1/state/artifacts/exports/attempts-20261124T015052Z.json`; file exists (JSON list of 3 rows). After the drain, `tl rounds once` refused ("blocked by the durable drain request"); `tl rounds start` reopened it, then `rounds once` ran | D3 (minor) |
| 6 | schema v38/v39 upgrade-drain | reached only as far as refusal | no v38 build to produce a real old db. A copy of the v39 db with `user_version=38`: `tl drain` and `tl rounds start` both refuse ("records schema version 38; this runtime expects 39. The database has been preserved"), `refused:schema`, db untouched. The drain-then-discard path with a real running v38 attempt: not reachable | none |

## Defects

| id | defect | suggested fix (not applied) |
|---|---|---|
| D1 | With `slot_count = 1` and `land: manual`, a passed task waiting to land keeps the last slot, so every round is `stopped=slot_for_land` and `--exit-when-idle` (needs `not found.stopped` in `rounds.py` `_rounds`) never fires, against `docs/cli.md` ("a task waiting to be landed counts as idle") | in `_rounds`, treat the `slot_for_land` stop as no work (the stop word names a wait, not a pending move), or refuse `--exit-when-idle` with fewer than 2 slots |
| D2 | A slots root whose path is too long (the scratchpad path here) is accepted: `slot adopt` and the plan step run, then implement is refused `environment:path_long` and relaunched every round without end | check the slot's temporary path length at `slot adopt` (and `config show`), not first at implement |
| D3 | A second `tl drain` while one is complete ("retrying observes the same request") writes a second export file (`attempts-...015053Z.json`) | write the export once per drain request, or reuse its path on retry |

## Notes

- The first plan attempt of each task was `uncommitted` and repeated once (agent did not commit); the repeat committed. Cheap
  model behaviour, not a feature defect.
- Run 0 (long scratchpad path) was stopped by its own confirmed pid; its files are kept beside the run (not in the repository).
- Not tested: dashboard, land, `--retake-lapsed`, the secret-scan check, a real v38 upgrade.
