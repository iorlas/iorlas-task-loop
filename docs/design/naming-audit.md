# Naming audit: purging "lane" (2026-11-05)

Three read-only passes (Haiku subagents) over task-loop src/skills, task-loop docs/tests/dashboard page, and delegate origin/main. Counts are regex matches; the docs/tests pass was classified by keyword rules and is about +/-20%; the src pass was classified by line. The canonical names are in docs/glossary.md.

## What "lane" means today

| Meaning | New name | task-loop src/skills | task-loop docs/tests/page | delegate origin/main |
|---|---|---|---|---|
| Vendor connection with usage windows (delegate's) | account | 586 in 103 files | about 812 lines in 152 files | 2019 lines in 154 files (all of it) |
| Parallel sequence of checks in one gate block | track | 145 in 20 files | about 136 lines in 55 files (undercount) | none |
| Loop process from `tl factory start` | loop | 76 in 11 files | about 192 lines in 55 files | none |
| Dashboard slot row ("Floor" lanes) | slot | 7 in 3 files | about 130 lines in 34 files (includes panels of A) | none |
| Bead label prefix `lane:` for areas; `pick` filter wording | neither renamed: the prefix is a profile value the repo chooses (`area_label_prefix`); reword the docs | 5 in 2 files | | |

## Rename list (one cut, no alias)

Task-loop:
- `domain/lanes/` (policy.py, pauses.py, retry.py) becomes `domain/accounts/`; 37 lines import it. `contracts/usage.py`, `contracts/delegate_status.py`, `contracts/trace.py` (`lanes` manifest), `lane_poll`, `lane_wait_min` (to `account_wait_min`), `no_lane` stop reason, `res.lane` in `worker_call.py`.
- `tl lanes` becomes `tl accounts`; the `lanes` panel and cards in the dashboard (`lanes.js`, `lanecards.py`, `phone.js`, `app.js`, `data.js`, `shell.js`, CSS) become Accounts.
- Check lane: `checks[].lane` becomes `track` (`contracts/checks.py:85`, `contracts/config.py:109`, `app/checks/lanes.py`, `executor.py:56`, `contracts/log.py` CheckStart/CheckEnd/WaitEnd fields, `stage_logs.py:66`, skills/task-loop/SKILL.md "Lanes." section at line 218, `tests/checks/test_lanes.py`). A hard profile key cut: only `track` is accepted; the former key is refused as unknown (CLAUDE.md).
- Loop process: `lane_states` and `factory-lane-K.log` become `loop_states` and `factory-loop-K.log`; `LANES running=` becomes `LOOPS running=`; `idle_lanes` becomes `idle_loops` (`slot_liveness.py`, `loop.py:237`); `exits.py` docstrings; `SkipKind "lane"`, `lanes_seen` (`contracts/loop.py`: decide per use, A or C); the `lanes` argument and profile wording that is really `slots.count` (`setup.py`, `setup_apply.py`, skills/task-loop/SKILL.md:342, `cli/factory.py _wanted`).
- Dashboard: the "Floor" tab, `views/floor.py`, `floor.js`, badges, 41 occurrences in 16 files become Slots; `Math.floor` (3) stays.
- Docs: README lines 22, 77, 97, 112, 114; roadmap; design notes that describe the current system; the architecture and review notes under docs/ are history and are not edited.

Delegate (moves into `src/delegate` per the cutover; the purge happens in the copy, not before):
- `routing.json` key `lanes` and `worker_lane_gate`; `config.json` `profile.lanes`; `state.json` `out`, leases and holds keyed by lane; status, doctor and cockpit JSON; `LaneSpec`, `LaneOut`, `LanePicker`, `LaneFact`, `LaneRow`, `CockpitLane`, `LaneGoneWatcher`; modules `domain/lanes/`; CLI `--lane`, `hold LANE`, `release`; the three skills (`delegate`, `init`, `status`); 92 test files (39 .py, 53 goldens and fixtures). The retired CLI, skills and wire JSON (see the cutover) remove part of this; the rest is a mechanical rename in the copy.
- Lane ids `CLAUDE_SUBSCRIPTION`, `OPENAI_SUBSCRIPTION`, `GROK_SUBSCRIPTION`, `DEEPSEEK_FREE`, `ZAI_CODING_SUBSCRIPTION` stay as account ids.

## Other words found

| Word | Problem | Verdict |
|---|---|---|
| floor | dashboard "Floor" view; lifesim's game floor is unrelated | ✅ Slots in the dashboard; word stays out of the engine |
| kind (delegate) | "subscription" vs launcher (codex, claude_p, opencode) | ✅ split: account `plan` vs `harness` |
| profile (delegate) | owner's per-account choices vs task-loop's `.task-loop.json` | ✅ delegate's becomes `choices` or lives under the account; "profile" stays task-loop's |
| provider | OpenCode provider id (zai-coding-plan) | ✅ keep, reserved for that |
| account | Codex rate-limit RPC and Claude login already use the word | ✅ fine: it is the same thing from the vendor side |
| node | engine stage name vs Node.js vs pytest node | ✅ stage everywhere in task-loop prose; `node` only for the engine record field until renamed |
| agent | AI agent, `agent-setup` recipe, `agent-runs` folder | ⚠️ `agent-runs` is delegate's publication; goes with its retirement; others stay |
| task | repo name, `run-task`, generic queue item | ✅ bead for the unit; `run-task` stays as the command |
| job | worker job kind, old design, shell job | ✅ role, not job |
| instance | factory instance in older prose | ✅ factory |

## Hard-to-classify (decide at rename time)

`app/run/state.py:37`, `contracts/loop.py:15,85`, `loop.py:299` ("waits for a lane" is an account wait), `floor.js` slot.lane values (an account shown on a slot row), `tests/dash/golden/closes.json`, `tests/fixtures/dash/snapshot.json` (lane field in dashboard data), `docs/design/dashboard/dash-spec.md:395`, `tests/support/lanes.py`. Lifesim fixtures that say "default lane" (a Unity test category) are not ours and stay.
