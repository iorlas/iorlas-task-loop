# Test times: what eats the time, and what to do

## pix run: whole tests/ tree, one worker (this is the measurement that replaces the Mac numbers below)

Host: OrbStack NixOS arm64 VM, 13 cores, idle. `TL_DELEGATE_TESTS=1 PYTHONPATH=dev nice -n 10 uv run pytest -p testtimes tests -m "not live"`, main `e01abeea` merged into the branch. 4696 tests recorded, **206 CPU s, 519 wall s summed over tests**; the run itself was 415 s wall.

Caveats: (1) the one-process full run polluted itself: 208 failures and 73 errors (`git rev-parse exited 128: no message from git`, `Needed a single revision`) in loop/real, slots/real, ports/real, report/real, prune/real, release/real, none of which fail when their files run alone. The 29 failing files were re-run alone (151 s) and their timings replace the polluted ones; 2 failed and 10 errored in isolation (6 delegate `@real_proc` tests: no codex/claude/opencode CLI on pix; `tests/loop/real/test_loop.py::QueueRuleFromBase` x4; `rules/test_envvars`; `dash/test_dash_artifacts` serve test), not chased. The pollution source is not found (first failure in file order is tests/dash/test_dash_artifacts). (2) CPU = user+sys of the process plus waited-for children. (3) The `why slow` clauses are read from names and directories, not profiled.

**Mac vs pix:** the Mac's "4.8-9.7 s per land/real test" was load (~80). On an idle host the same tests are 0.5-0.9 CPU s. CPU on the Mac was inflated too, so its table must not be used for ranking the levers.

### Top 50 by CPU

| # | test | CPU s | wall s | why slow | verdict |
|---|---|---|---|---|---|
| 1 | `rules/real/test_selection_mutations.py::test_the_selection_holds_the_test_the_mutation_breaks[a function body in a leaf module]` | 2.67 | 2.68 | mutates a tree copy and runs dev/affected.py per case | one shared tree copy, parametrize over the mutation only |
| 2 | `rules/real/test_selection_mutations.py::test_the_selection_holds_the_test_the_mutation_breaks[a signature in contracts]` | 2.58 | 2.58 | mutates a tree copy and runs dev/affected.py per case | one shared tree copy, parametrize over the mutation only |
| 3 | `rules/real/test_selection_mutations.py::test_the_selection_holds_the_test_the_mutation_breaks[pyproject.toml]` | 2.51 | 2.51 | mutates a tree copy and runs dev/affected.py per case | one shared tree copy, parametrize over the mutation only |
| 4 | `rules/real/test_selection_mutations.py::test_a_change_that_reaches_no_test_selects_the_rules_only` | 2.51 | 2.51 | mutates a tree copy and runs dev/affected.py per case | one shared tree copy, parametrize over the mutation only |
| 5 | `rules/real/test_selection_mutations.py::test_the_selection_holds_the_test_the_mutation_breaks[a changed test file]` | 2.50 | 2.50 | mutates a tree copy and runs dev/affected.py per case | one shared tree copy, parametrize over the mutation only |
| 6 | `rules/real/test_selection_mutations.py::test_the_selection_holds_the_test_the_mutation_breaks[a contracts golden file]` | 2.50 | 2.50 | mutates a tree copy and runs dev/affected.py per case | one shared tree copy, parametrize over the mutation only |
| 7 | `rules/real/test_selection_mutations.py::test_the_selection_holds_the_test_the_mutation_breaks[a script that tests run by path]` | 2.49 | 2.49 | mutates a tree copy and runs dev/affected.py per case | one shared tree copy, parametrize over the mutation only |
| 8 | `rules/real/test_selection_mutations.py::test_the_selection_holds_the_test_the_mutation_breaks[a constant in a vendored package]` | 2.48 | 2.48 | mutates a tree copy and runs dev/affected.py per case | one shared tree copy, parametrize over the mutation only |
| 9 | `rules/real/test_selection_mutations.py::test_the_selection_holds_the_test_the_mutation_breaks[a new record type with no sample]` | 2.47 | 2.47 | mutates a tree copy and runs dev/affected.py per case | one shared tree copy, parametrize over the mutation only |
| 10 | `rules/real/test_selection_mutations.py::test_the_selection_holds_the_test_the_mutation_breaks[the import-linter contracts]` | 2.47 | 2.47 | mutates a tree copy and runs dev/affected.py per case | one shared tree copy, parametrize over the mutation only |
| 11 | `rules/real/test_selection_mutations.py::test_the_selection_holds_the_test_the_mutation_breaks[a test support helper]` | 2.47 | 2.47 | mutates a tree copy and runs dev/affected.py per case | one shared tree copy, parametrize over the mutation only |
| 12 | `rules/test_state_writers.py::StateFilesHaveOneWriter::test_store_mutations_and_raw_publications_belong_to_their_writer` | 2.41 | 2.41 | AST/grep walk of the whole src tree each test | parse once per session (cached fixture) |
| 13 | `delegate/test_review_order.py::ReviewOrder::test_opus_is_never_returned_for_any_loop_role` | 1.54 | 1.54 | loop of full runs / fake CLI processes in one test | table-test the pure function; one real run |
| 14 | `loop/real/test_loop.py::Loop::test_a_role_delegate_cannot_judge_fails_open_after_the_unknown_wait` | 1.49 | 7.17 | loop of full runs / fake CLI processes in one test | table-test the pure function; one real run |
| 15 | `rules/test_arch_invariants.py::ArchitectureInvariants::test_slices_follow_the_allow_table` | 1.30 | 1.30 | AST/grep walk of the whole src tree each test | parse once per session (cached fixture) |
| 16 | `rules/test_factorydb_owners.py::FactoryOwnersTest::test_only_the_legacy_importer_may_name_the_run_manifest_file` | 1.21 | 1.21 | AST/grep walk of the whole src tree each test | parse once per session (cached fixture) |
| 17 | `rules/test_enumtotal.py::EnumTotal::test_every_production_enum_literal_is_total` | 1.17 | 1.17 | AST/grep walk of the whole src tree each test | parse once per session (cached fixture) |
| 18 | `slots/real/test_areas.py::ReviewFixes::test_a_long_area_wait_says_how_long_and_who_holds_it_and_until_still_ends_the_loop` | 1.09 | 5.23 | real loop, waits and real git | share the repo fixture |
| 19 | `slots/test_slot_sim.py::Sim::test_seed_2_holds_every_invariant` | 0.94 | 0.94 | seeded simulation loop | keep (it is the invariant test); fewer seeds in gate |
| 20 | `slots/test_slot_sim.py::Sim::test_seed_6_holds_every_invariant` | 0.90 | 0.90 | seeded simulation loop | keep (it is the invariant test); fewer seeds in gate |
| 21 | `land/real/test_engine_real_git.py::RealGitLandTest::test_a_conflict_fix_leaving_markers_is_not_accepted_the_marker_check_still_runs` | 0.88 | 1.03 | fresh bare remote + clone + engine per test (real git, processes) | template repo copied per test |
| 22 | `rules/test_git_ratchet.py::GitRule::test_no_file_calls_git_outside_the_port_unless_it_says_why` | 0.86 | 0.86 | AST/grep walk of the whole src tree each test | parse once per session (cached fixture) |
| 23 | `land/real/test_engine_real_git.py::RealGitLandTest::test_push_race_retry_keeps_one_land_lock_and_lands` | 0.85 | 1.05 | fresh bare remote + clone + engine per test (real git, processes) | template repo copied per test |
| 24 | `loop/real/test_loop.py::Loop::test_a_live_storm_record_waits_before_any_claim_then_expires` | 0.85 | 5.01 | real loop with fake clock plus real git setup | share the repo fixture |
| 25 | `loop/real/test_loop.py::Loop::test_one_instant_failure_or_a_slow_one_or_another_reason_sets_nothing_aside` | 0.84 | 3.60 | real loop with fake clock plus real git setup | share the repo fixture |
| 26 | `hook/real/test_prepush.py::PrePush::test_a_mixed_push_with_a_stamped_base_passes_and_an_unproven_base_does_not` | 0.80 | 1.62 | fresh bare remote + clone + engine per test (real git, processes) | template repo copied per test |
| 27 | `slots/test_slot_sim.py::Sim::test_without_the_watchdog_the_same_seeds_find_the_stall` | 0.79 | 0.79 | seeded simulation loop | keep (it is the invariant test); fewer seeds in gate |
| 28 | `rules/test_runstate_rule.py::LivenessIsRecorded::test_no_reader_derives_liveness_from_a_log_gap` | 0.79 | 0.79 | AST/grep walk of the whole src tree each test | parse once per session (cached fixture) |
| 29 | `delegate/test_run_vendors.py::RunVendors::test_every_answer_carries_call_id_usage_transcript_object_and_typed_stop` | 0.76 | 3.04 | loop of full runs / fake CLI processes in one test | table-test the pure function; one real run |
| 30 | `loop/real/test_hold_e2e.py::HoldEndToEnd::test_a_hold_with_an_end_keeps_the_loop_off_the_bead_until_the_clock_passes_it` | 0.75 | 3.47 | real loop with fake clock plus real git setup | share the repo fixture |
| 31 | `delegate/test_contention.py::Contention::test_parallel_report_and_next_preserve_out_marks_and_fresh_dwell` | 0.75 | 0.56 | loop of full runs / fake CLI processes in one test | table-test the pure function; one real run |
| 32 | `land/real/test_engine_real_git.py::RealGitLandTest::test_a_rebase_conflict_goes_to_a_fix_round_not_blocked` | 0.74 | 0.87 | fresh bare remote + clone + engine per test (real git, processes) | template repo copied per test |
| 33 | `loop/real/test_hold_e2e.py::HoldEndToEnd::test_a_hold_without_an_end_lasts_until_it_is_released` | 0.72 | 3.14 | real loop with fake clock plus real git setup | share the repo fixture |
| 34 | `loop/real/test_loop.py::Loop::test_a_lane_pause_wakes_when_the_role_is_usable_not_at_the_hint` | 0.68 | 2.59 | real loop with fake clock plus real git setup | share the repo fixture |
| 35 | `run/test_stages.py::Handoff::test_the_amend_planner_sees_what_the_rounds_did` | 0.66 | 0.68 | inferred from name only | review |
| 36 | `delegate/test_contention.py::Contention::test_parallel_config_cli_and_update_config_lose_no_updates` | 0.65 | 0.74 | loop of full runs / fake CLI processes in one test | table-test the pure function; one real run |
| 37 | `domain/real/test_slot_env.py::EverySpawnPath::test_checks_gate_land_and_the_worker_get_the_slot_values` | 0.65 | 0.81 | fresh bare remote + clone + engine per test (real git, processes) | template repo copied per test |
| 38 | `delegate/test_run_stops.py::RunStops::test_network_stops_never_bench_the_pair` | 0.64 | 2.06 | loop of full runs / fake CLI processes in one test | table-test the pure function; one real run |
| 39 | `e2e/test_selftest.py::SelfTest::test_the_scenario_through_engine_run_passes_in_a_bounded_number_of_processes` | 0.63 | 0.75 | fresh bare remote + clone + engine per test (real git, processes) | template repo copied per test |
| 40 | `e2e/test_release.py::Release::test_a_stale_branch_is_rebased_before_the_suite` | 0.62 | 1.50 | fresh bare remote + clone + engine per test (real git, processes) | template repo copied per test |
| 41 | `delegate/test_run_stops.py::RunStops::test_every_answer_carries_the_stop_facts` | 0.61 | 2.02 | loop of full runs / fake CLI processes in one test | table-test the pure function; one real run |
| 42 | `rules/test_subprocess_rule.py::SubprocessRule::test_raw_process_calls_stay_at_the_process_boundary` | 0.60 | 0.60 | AST/grep walk of the whole src tree each test | parse once per session (cached fixture) |
| 43 | `rules/test_no_whole_suite_command.py::test_no_src_or_skill_code_builds_a_pytest_command` | 0.59 | 0.59 | AST/grep walk of the whole src tree each test | parse once per session (cached fixture) |
| 44 | `e2e/test_release.py::Release::test_two_branch_releases_queue_rebase_and_test_the_pushed_tree` | 0.59 | 1.52 | fresh bare remote + clone + engine per test (real git, processes) | template repo copied per test |
| 45 | `delegate/test_route.py::StateLock::test_parallel_processes_lose_no_update` | 0.59 | 0.19 | loop of full runs / fake CLI processes in one test | table-test the pure function; one real run |
| 46 | `loop/real/test_loop.py::Loop::test_a_role_that_stays_down_keeps_the_bead_waiting_while_others_run` | 0.56 | 2.72 | real loop with fake clock plus real git setup | share the repo fixture |
| 47 | `hook/real/test_prepush.py::PrePush::test_the_head_that_is_not_green_runs_the_plan_then_passes` | 0.54 | 1.18 | fresh bare remote + clone + engine per test (real git, processes) | template repo copied per test |
| 48 | `land/real/test_cleanup.py::EngineCleanup::test_remote_that_moves_after_the_push_check_is_kept_on_retry` | 0.54 | 0.66 | fresh bare remote + clone + engine per test (real git, processes) | template repo copied per test |
| 49 | `land/real/test_cleanup.py::EngineCleanup::test_engine_push_land_removes_remote_local_and_worktree_after_recording_receipt` | 0.53 | 0.64 | fresh bare remote + clone + engine per test (real git, processes) | template repo copied per test |
| 50 | `loop/real/test_loop.py::Loop::test_drained_waits_when_asked_and_polls_until_the_end_time` | 0.52 | 2.57 | real loop with fake clock plus real git setup | share the repo fixture |

### Per directory

| dir | tests | CPU s | wall s |
|---|---|---|---|
| rules | 196 | 40.3 | 40.3 |
| loop | 246 | 26.3 | 100.4 |
| delegate | 589 | 25.8 | 161.7 |
| run | 551 | 20.9 | 28.7 |
| land | 403 | 20.4 | 26.4 |
| e2e | 29 | 9.4 | 23.0 |
| checks | 318 | 9.0 | 23.0 |
| slots | 159 | 8.3 | 21.3 |
| hook | 61 | 6.6 | 11.4 |
| plan | 103 | 5.9 | 6.7 |
| review | 102 | 4.6 | 5.3 |
| ports | 150 | 4.1 | 10.5 |
| adapters | 264 | 3.4 | 14.3 |
| dash | 355 | 3.2 | 6.0 |
| asks | 162 | 2.8 | 4.7 |
| doctor | 35 | 2.0 | 6.2 |
| prune | 70 | 1.8 | 3.0 |
| write | 30 | 1.6 | 3.2 |
| report | 50 | 1.5 | 4.6 |
| release | 33 | 1.3 | 5.3 |
| look | 17 | 1.2 | 1.5 |
| track | 36 | 1.2 | 1.4 |
| cli | 82 | 1.1 | 2.3 |
| contracts | 241 | 0.9 | 2.5 |
| domain | 165 | 0.8 | 1.0 |
| stores | 83 | 0.5 | 2.6 |
| launch | 51 | 0.5 | 0.8 |
| wire | 81 | 0.2 | 0.2 |
| artifacts | 34 | 0.1 | 0.1 |

### Slowest by wall (sleeps and waits, not CPU)

- 8.0 s wall / 0.43 CPU: `delegate/test_delegate_kill_tree.py::RealTrees::test_supervisor_timeout_leaves_no_process`
- 8.0 s wall / 0.45 CPU: `delegate/test_delegate_kill_tree.py::RealTrees::test_run_tree_timeout_stops_the_tree`
- 7.2 s wall / 1.49 CPU: `loop/real/test_loop.py::Loop::test_a_role_delegate_cannot_judge_fails_open_after_the_unknown_wait`
- 7.0 s wall / 0.40 CPU: `delegate/test_own_contract.py::RealProcesses::test_call_timeout_stops_a_worker_that_ignores_sigterm`
- 5.6 s wall / 0.10 CPU: `delegate/test_stream_supervisor.py::Replay::test_a_stalled_stream_is_killed_and_its_tail_logged`
- 5.5 s wall / 0.50 CPU: `delegate/test_own_contract.py::RealProcesses::test_sigterm_to_the_delegate_stops_the_worker_tree_first`
- 5.3 s wall / 0.10 CPU: `delegate/test_run_vendors.py::RunVendors::test_a_claude_worker_waiting_on_a_background_task_is_stopped_after_its_answer`
- 5.2 s wall / 1.09 CPU: `slots/real/test_areas.py::ReviewFixes::test_a_long_area_wait_says_how_long_and_who_holds_it_and_until_still_ends_the_loop`

### Three biggest levers (pix numbers)

1. **tests/rules (40 CPU s, 20% of all CPU, 196 tests):** 11 `selection_mutations` cases at 2.5 s each (28 s) plus whole-tree walks (`state_writers` 2.4, `arch_invariants` 1.3, `factorydb_owners` 1.2, `enumtotal` 1.2). Parse the tree once per session and share one mutated copy: ~35 CPU s saved, and these run on every `just test`.
2. **Wall, not CPU, in delegate and loop (delegate 162 s wall for 26 CPU; loop 100 s for 26):** real timeouts and waits (`kill_tree` 8 s x2, `own_contract` 7 s, `stream_supervisor` 5.6 s, 7 s loop wait). Inject the clock / shorten the limits; ~120 s of wall for no CPU.
3. **Test isolation:** a whole-tree run fails 280 tests that pass alone. Find the leaking test (cwd, env or a patched git); until then no full-tree timing or run is trustworthy, and the order-dependence can bite xdist too.

Not a lever on pix: land/real fixtures (the Mac's #1) are 0.5-0.9 CPU s each; the template-repo idea is worth ~10 s, not 60.

---


## Earlier Mac run (load ~80; superseded above)
Measured 2026-11-05/06 with `dev/testtimes.py` (local, uncommitted). **Scope: the 5 largest directories** (delegate, run, land, dash, checks: 2214 tests, 1852 subtests), once, `nice -n 10`, one worker. The full tree was started first and stopped at 6% / 16 min (23 s CPU in 16 min of wall: starved by load ~80), so `adapters`, `loop`, `contracts`, `domain`, ... are **not measured**. CPU = user+sys of the pytest process plus the children it waited for; wall = elapsed. Whole run: 307 CPU s, 3620 s wall (12x: the host, not the tests). Children that were killed rather than waited for are not in CPU, so kill-tree tests are under-counted. The "why slow" column comes from reading the test and its names, not from a profiler.

## Verdict on the suite

- ❌ **No test is individually heavy**: the worst is 9.7 CPU s, the median is 0.017 s. The cost is volume (2214 tests + 1852 subtests in these five dirs alone) times per-test setup, on a starved host.
- ❌ **`land/real` is 12 of the top 13**: each is a full engine land over real git (~300 process spawns); the repo setup is already a template copy and is not the cost. 4.8-9.7 CPU s each, 74 s together, in a dir that is 41% of all CPU.
- ❌ **"every X" tests** (112 in the tree): a loop of full runs in one test. `test_classify::test_every_fixture_row...` took 36.7 s wall for 0.56 s CPU.
- ❌ **Not pytest-native**: 246 `setup_method`/`setUp`, 282 `subTest`/`subtests`, 14 `parametrize`. Each xunit `setup_method` fixture is paid per test (RunCommand/RunStops/RunVendors ~2 s each, 100 uses).
- ❌ **11 failures in `checks/real`** in this run (pass_files x5, tl_check x2, check_hooks, checks_speed, gateplan, lanes_real). Not investigated: likely the load (time limits) or running inside a worktree; they need a root cause before anyone trusts that dir.

## Per directory (measured dirs only)

| dir | tests | CPU s | share | wall s |
|---|---|---|---|---|
| land | 401 | 125.5 | 40.9% | 888 |
| run | 551 | 70.4 | 22.9% | 1173 |
| delegate | 589 | 68.7 | 22.4% | 1131 |
| checks | 318 | 36.1 | 11.8% | 344 |
| dash | 355 | 6.3 | 2.0% | 85 |

## Top 50 tests by CPU

| # | CPU s | wall s | test | why slow | verdict |
|---|---|---|---|---|---|
| 1 | 9.73 | 26.2 | `land/real/test_engine_real_git.py::RealGitLandTest::test_a_conflict_fix_leaving_markers_is_not_accepted_the_marker_check_still_runs` | one full engine land over real git: ~300 process spawns (profiled on #2: ~190 git calls: 36 `--no-optional-locks`, 32 rev-parse, 27 add, 25 read-tree, 25 merge-base, 16 worktree; setup is 0.3 of 6.5 CPU s) | cut spawns in the engine's land path (product code), or keep 1-2 real cells and leave the rest to the gitsim twin |
| 2 | 9.07 | 28.5 | `land/real/test_engine_real_git.py::RealGitLandTest::test_a_rebase_conflict_goes_to_a_fix_round_not_blocked` | one full engine land over real git: ~300 process spawns (profiled on #2: ~190 git calls: 36 `--no-optional-locks`, 32 rev-parse, 27 add, 25 read-tree, 25 merge-base, 16 worktree; setup is 0.3 of 6.5 CPU s) | cut spawns in the engine's land path (product code), or keep 1-2 real cells and leave the rest to the gitsim twin |
| 3 | 8.97 | 28.1 | `land/real/test_engine_real_git.py::RealGitLandTest::test_push_race_retry_keeps_one_land_lock_and_lands` | one full engine land over real git: ~300 process spawns (profiled on #2: ~190 git calls: 36 `--no-optional-locks`, 32 rev-parse, 27 add, 25 read-tree, 25 merge-base, 16 worktree; setup is 0.3 of 6.5 CPU s) | cut spawns in the engine's land path (product code), or keep 1-2 real cells and leave the rest to the gitsim twin |
| 4 | 5.68 | 18.6 | `land/real/test_outbound.py::Land::test_an_lfs_repo_pushes_the_ref_s_objects_before_the_push` | one full engine land over real git: ~300 process spawns (profiled on #2: ~190 git calls: 36 `--no-optional-locks`, 32 rev-parse, 27 add, 25 read-tree, 25 merge-base, 16 worktree; setup is 0.3 of 6.5 CPU s) | cut spawns in the engine's land path (product code), or keep 1-2 real cells and leave the rest to the gitsim twin |
| 5 | 5.40 | 15.0 | `land/real/test_engine_real_git.py::RealGitLandTest::test_happy_path_lands_and_closes` | one full engine land over real git: ~300 process spawns (profiled on #2: ~190 git calls: 36 `--no-optional-locks`, 32 rev-parse, 27 add, 25 read-tree, 25 merge-base, 16 worktree; setup is 0.3 of 6.5 CPU s) | cut spawns in the engine's land path (product code), or keep 1-2 real cells and leave the rest to the gitsim twin |
| 6 | 5.35 | 14.3 | `land/real/test_cleanup.py::EngineCleanup::test_remote_that_moves_after_the_push_check_is_kept_on_retry` | one full engine land over real git: ~300 process spawns (profiled on #2: ~190 git calls: 36 `--no-optional-locks`, 32 rev-parse, 27 add, 25 read-tree, 25 merge-base, 16 worktree; setup is 0.3 of 6.5 CPU s) | cut spawns in the engine's land path (product code), or keep 1-2 real cells and leave the rest to the gitsim twin |
| 7 | 5.26 | 17.8 | `land/real/test_engine_real_git.py::RealGitLandTest::test_wip_from_an_earlier_run_lands_as_one_titled_commit` | one full engine land over real git: ~300 process spawns (profiled on #2: ~190 git calls: 36 `--no-optional-locks`, 32 rev-parse, 27 add, 25 read-tree, 25 merge-base, 16 worktree; setup is 0.3 of 6.5 CPU s) | cut spawns in the engine's land path (product code), or keep 1-2 real cells and leave the rest to the gitsim twin |
| 8 | 5.08 | 12.4 | `land/real/test_cleanup.py::EngineCleanup::test_remote_already_gone_is_success` | one full engine land over real git: ~300 process spawns (profiled on #2: ~190 git calls: 36 `--no-optional-locks`, 32 rev-parse, 27 add, 25 read-tree, 25 merge-base, 16 worktree; setup is 0.3 of 6.5 CPU s) | cut spawns in the engine's land path (product code), or keep 1-2 real cells and leave the rest to the gitsim twin |
| 9 | 5.08 | 16.2 | `land/real/test_outbound.py::Land::test_a_pre_push_hook_that_fails_does_not_stop_the_land` | one full engine land over real git: ~300 process spawns (profiled on #2: ~190 git calls: 36 `--no-optional-locks`, 32 rev-parse, 27 add, 25 read-tree, 25 merge-base, 16 worktree; setup is 0.3 of 6.5 CPU s) | cut spawns in the engine's land path (product code), or keep 1-2 real cells and leave the rest to the gitsim twin |
| 10 | 5.06 | 12.7 | `land/real/test_cleanup.py::EngineCleanup::test_engine_land_keeps_registered_slot_and_detaches_at_base` | one full engine land over real git: ~300 process spawns (profiled on #2: ~190 git calls: 36 `--no-optional-locks`, 32 rev-parse, 27 add, 25 read-tree, 25 merge-base, 16 worktree; setup is 0.3 of 6.5 CPU s) | cut spawns in the engine's land path (product code), or keep 1-2 real cells and leave the rest to the gitsim twin |
| 11 | 4.86 | 14.9 | `land/real/test_stages_land.py::Contracts::test_a_network_failure_on_the_push_is_retried_with_a_rest_and_lands` | one full engine land over real git: ~300 process spawns (profiled on #2: ~190 git calls: 36 `--no-optional-locks`, 32 rev-parse, 27 add, 25 read-tree, 25 merge-base, 16 worktree; setup is 0.3 of 6.5 CPU s) | cut spawns in the engine's land path (product code), or keep 1-2 real cells and leave the rest to the gitsim twin |
| 12 | 4.84 | 13.2 | `land/real/test_cleanup.py::EngineCleanup::test_engine_push_land_removes_remote_local_and_worktree_after_recording_receipt` | one full engine land over real git: ~300 process spawns (profiled on #2: ~190 git calls: 36 `--no-optional-locks`, 32 rev-parse, 27 add, 25 read-tree, 25 merge-base, 16 worktree; setup is 0.3 of 6.5 CPU s) | cut spawns in the engine's land path (product code), or keep 1-2 real cells and leave the rest to the gitsim twin |
| 13 | 4.46 | 13.6 | `land/test_engine_land_1.py::EngineLand1Test::test_a_stop_during_the_push_waits_for_it_and_the_bead_lands` | logic-kind engine land over gitsim; several full engine rounds per test (push race / resume matrix) | fake the clock/process: the 4 `sigterm_*` variants of one test are one parametrized case; share the round setup |
| 14 | 1.92 | 23.1 | `delegate/test_contention.py::Contention::test_parallel_config_cli_and_update_config_lose_no_updates` | starts N real processes that contend for one state file | move to the real kind (a `real/` folder); drop to 2 processes, not N |
| 15 | 1.92 | 14.9 | `delegate/test_contention.py::Contention::test_parallel_report_and_next_preserve_out_marks_and_fresh_dwell` | starts N real processes that contend for one state file | move to the real kind (a `real/` folder); drop to 2 processes, not N |
| 16 | 1.91 | 13.8 | `delegate/test_run_vendors.py::RunVendors::test_every_answer_carries_call_id_usage_transcript_object_and_typed_stop` | loops a table inside one test; each row is a full run (fake CLI + git) or a full matrix | delete the loop: assert the table on the pure function; keep one real run for wiring |
| 17 | 1.83 | 2.1 | `delegate/test_review_order.py::ReviewOrder::test_opus_is_never_returned_for_any_loop_role` | loops a table inside one test; each row is a full run (fake CLI + git) or a full matrix | delete the loop: assert the table on the pure function; keep one real run for wiring |
| 18 | 1.39 | 12.7 | `delegate/test_run_stops.py::RunStops::test_every_answer_carries_the_stop_facts` | loops a table inside one test; each row is a full run (fake CLI + git) or a full matrix | delete the loop: assert the table on the pure function; keep one real run for wiring |
| 19 | 1.38 | 4.4 | `checks/real/test_pass_files.py::PassFiles::test_the_files_are_part_of_the_cache_key` | runs `tl check` as a subprocess (uv script start, git repo init) per test | shrink: call the check function in process; keep one subprocess smoke test |
| 20 | 1.28 | 4.0 | `checks/real/test_tl_check.py::TlCheck::test_a_red_run_keeps_its_evidence_and_prints_the_path` | runs `tl check` as a subprocess (uv script start, git repo init) per test | shrink: call the check function in process; keep one subprocess smoke test |
| 21 | 1.27 | 10.1 | `delegate/test_run_stops.py::RunStops::test_network_stops_never_bench_the_pair` | several full `route.py run` calls per test, each spawning a fake CLI and git; the per-test setup_method adds ~57 ms | shrink: parametrize per row, module-scoped home fixture; move the run-spawning ones to `real/` |
| 22 | 1.22 | 25.4 | `run/real/test_close_kill.py::CloseKill::test_a_process_killed_before_the_bd_close_is_finished_by_the_next_one_which_closes_once` | real process trees plus waits for a kill/timeout to take effect | move to the real kind, fake the clock for the timeout |
| 23 | 1.21 | 10.4 | `delegate/test_route.py::StateLock::test_parallel_processes_lose_no_update` | starts N real processes that contend for one state file | move to the real kind (a `real/` folder); drop to 2 processes, not N |
| 24 | 1.18 | 13.2 | `delegate/test_contention.py::Contention::test_parallel_agent_runs_keep_unique_runs_and_whole_lane_snapshots` | starts N real processes that contend for one state file | move to the real kind (a `real/` folder); drop to 2 processes, not N |
| 25 | 1.15 | 3.6 | `checks/real/test_tl_check.py::TlCheck::test_green_gate_exits_0_and_a_second_run_is_cached` | runs `tl check` as a subprocess (uv script start, git repo init) per test | shrink: call the check function in process; keep one subprocess smoke test |
| 26 | 1.08 | 3.3 | `checks/real/test_pass_files.py::PassFiles::test_all_hands_every_tracked_file_that_matches_when` | loops a table inside one test; each row is a full run (fake CLI + git) or a full matrix | delete the loop: assert the table on the pure function; keep one real run for wiring |
| 27 | 1.07 | 8.5 | `delegate/test_run_stops.py::RunStops::test_bad_request_never_benches_the_pair` | several full `route.py run` calls per test, each spawning a fake CLI and git; the per-test setup_method adds ~57 ms | shrink: parametrize per row, module-scoped home fixture; move the run-spawning ones to `real/` |
| 28 | 1.00 | 14.8 | `run/real/test_close_kill.py::CloseKill::test_the_restart_reuses_the_dead_runs_id` | real process trees plus waits for a kill/timeout to take effect | move to the real kind, fake the clock for the timeout |
| 29 | 0.99 | 15.3 | `run/real/test_close_kill.py::CloseKill::test_a_process_killed_after_the_bd_close_does_not_close_again` | real process trees plus waits for a kill/timeout to take effect | move to the real kind, fake the clock for the timeout |
| 30 | 0.94 | 11.4 | `run/test_stages.py::Handoff::test_a_smaller_session_goes_on_and_the_limit_is_the_repos_to_set` | several engine/CLI calls per test, wall dominated by process starts | fake the process; one real call per file |
| 31 | 0.93 | 10.5 | `land/test_engine_land_1.py::EngineLand1Test::test_push_race_interrupted_validation_fix_resume_requires_acceptance_denial_reviewer` | logic-kind engine land over gitsim; several full engine rounds per test (push race / resume matrix) | fake the clock/process: the 4 `sigterm_*` variants of one test are one parametrized case; share the round setup |
| 32 | 0.91 | 3.7 | `checks/real/test_check_move.py::CheckMove::test_real_trim_commit` | runs `tl check` as a subprocess (uv script start, git repo init) per test | shrink: call the check function in process; keep one subprocess smoke test |
| 33 | 0.90 | 9.6 | `delegate/test_own_contract.py::RealProcesses::test_sigterm_to_the_delegate_stops_the_worker_tree_first` | real process trees plus waits for a kill/timeout to take effect | move to the real kind, fake the clock for the timeout |
| 34 | 0.88 | 8.6 | `delegate/test_delegate_kill_tree.py::RealTrees::test_run_tree_timeout_stops_the_tree` | real process trees plus waits for a kill/timeout to take effect | move to the real kind, fake the clock for the timeout |
| 35 | 0.88 | 8.8 | `delegate/test_delegate_kill_tree.py::RealTrees::test_supervisor_timeout_leaves_no_process` | real process trees plus waits for a kill/timeout to take effect | move to the real kind, fake the clock for the timeout |
| 36 | 0.84 | 10.1 | `land/test_engine_land_1.py::EngineLand1Test::test_a_red_gate_replans_with_its_output_and_keeps_the_accepted_stages` | logic-kind engine land over gitsim; several full engine rounds per test (push race / resume matrix) | fake the clock/process: the 4 `sigterm_*` variants of one test are one parametrized case; share the round setup |
| 37 | 0.82 | 3.1 | `checks/real/test_pass_files.py::PassFiles::test_a_check_gets_only_the_changed_files_that_match_its_when` | runs `tl check` as a subprocess (uv script start, git repo init) per test | shrink: call the check function in process; keep one subprocess smoke test |
| 38 | 0.82 | 10.0 | `land/test_engine_land_1.py::EngineLand1Test::test_push_race_interrupted_validation_fix_resume_requires_acceptance_pause_worker` | logic-kind engine land over gitsim; several full engine rounds per test (push race / resume matrix) | fake the clock/process: the 4 `sigterm_*` variants of one test are one parametrized case; share the round setup |
| 39 | 0.82 | 10.2 | `land/test_engine_land_1.py::EngineLand1Test::test_push_race_interrupted_validation_fix_resume_requires_acceptance_sigterm_transition` | logic-kind engine land over gitsim; several full engine rounds per test (push race / resume matrix) | fake the clock/process: the 4 `sigterm_*` variants of one test are one parametrized case; share the round setup |
| 40 | 0.82 | 9.9 | `land/test_engine_land_1.py::EngineLand1Test::test_push_race_interrupted_validation_fix_resume_requires_acceptance_sigterm_failed_checks` | logic-kind engine land over gitsim; several full engine rounds per test (push race / resume matrix) | fake the clock/process: the 4 `sigterm_*` variants of one test are one parametrized case; share the round setup |
| 41 | 0.81 | 18.9 | `delegate/test_engine_only_lanes.py::ClaudeHookTest::test_the_generated_hook_denies_the_recipe_with_the_rule` | several engine/CLI calls per test, wall dominated by process starts | fake the process; one real call per file |
| 42 | 0.81 | 3.2 | `checks/real/test_childenv.py::CheckHomeCanaryTest::test_cli_gate_in_real_git_checkout_cannot_find_owner_state_through_home` | runs `tl check` as a subprocess (uv script start, git repo init) per test | shrink: call the check function in process; keep one subprocess smoke test |
| 43 | 0.79 | 8.8 | `land/test_engine_land_1.py::EngineLand1Test::test_push_race_interrupted_validation_fix_resume_requires_acceptance_sigterm_checkpoint` | logic-kind engine land over gitsim; several full engine rounds per test (push race / resume matrix) | fake the clock/process: the 4 `sigterm_*` variants of one test are one parametrized case; share the round setup |
| 44 | 0.79 | 7.6 | `delegate/test_own_contract.py::RealProcesses::test_call_timeout_stops_a_worker_that_ignores_sigterm` | real process trees plus waits for a kill/timeout to take effect | move to the real kind, fake the clock for the timeout |
| 45 | 0.79 | 3.2 | `checks/real/test_tl_check.py::TlCheck::test_it_claims_nothing_and_writes_results_and_run_evidence` | runs `tl check` as a subprocess (uv script start, git repo init) per test | shrink: call the check function in process; keep one subprocess smoke test |
| 46 | 0.78 | 24.2 | `run/test_exchanges.py::Recorded::test_the_cases_replay` | replays recorded exchanges through the whole engine; cheap CPU, long waits | fake the clock; share the replay setup |
| 47 | 0.77 | 2.7 | `checks/real/test_tl_check.py::TlCheck::test_it_runs_the_gate_steps_and_exits_1_on_a_red_one` | runs `tl check` as a subprocess (uv script start, git repo init) per test | shrink: call the check function in process; keep one subprocess smoke test |
| 48 | 0.75 | 2.7 | `checks/real/test_pass_files.py::PassFiles::test_no_changed_file_that_matches_skips_the_check_and_says_so` | runs `tl check` as a subprocess (uv script start, git repo init) per test | shrink: call the check function in process; keep one subprocess smoke test |
| 49 | 0.73 | 2.7 | `checks/real/test_tl_check.py::TlCheck::test_clean_repo_check_records_the_repo_plans_skip_for_green` | runs `tl check` as a subprocess (uv script start, git repo init) per test | shrink: call the check function in process; keep one subprocess smoke test |
| 50 | 0.72 | 6.6 | `land/test_engine_land_1.py::EngineLand1Test::test_a_red_gate_after_a_conflict_fix_still_gets_a_fix_round_and_the_gate_ran_once_on_the_result` | logic-kind engine land over gitsim; several full engine rounds per test (push race / resume matrix) | fake the clock/process: the 4 `sigterm_*` variants of one test are one parametrized case; share the round setup |

## Top fixtures (own setup CPU, summed)

The xunit `setup_method` of RunCommand 2.0 s (35 uses), RunStops 2.0 s (33), RunVendors 1.8 s (32), TlCheck 1.3 s, PassFiles 1.2 s; `delegate/conftest.py::own_home` 1.1 s over 589 uses. Full list: `python3 dev/testtimes_report.py five.json`.

## The three biggest levers

1. **Spawn count in the land path** (CORRECTED: the template-repo copy already exists, `copy_origin_and_clone`, and setup is only 0.3 of 6.5 CPU s). One real-git land makes ~300 process spawns, ~190 of them git, at ~20 ms CPU each (the Mac's per-process cost, see the Defender note in beads memory): `rev-parse` x32, `add` x27, `read-tree` x25, `merge-base` x25 repeat. Fewer or batched git calls in the engine, plus dropping real-git cells that duplicate their gitsim twin (5 cells re-run `test_engine_land_1`), is the lever for the 12 tests, ~74 CPU s.
2. **Kill the "every X" loops and `subTest`**: assert tables on the pure function (stops, routing, classify), parametrize the rest, one real run for wiring. Removes whole-matrix runs of fake CLI + git.
3. **Real-process tests out of logic dirs**: `@real_proc` tests living in `tests/delegate` and `tests/run` (not under `real/`) run whenever those dirs are selected, with `LIMIT_S = 60` hiding it. Move them to `real/`, fake the clock for the timeout ones.

(A fourth, cheaper than all: run the gate at normal priority. Wall is 12x CPU here because everything runs at load ~80.)

## Always-on test telemetry (design only)

Goal: every run records timings without being asked, and says so in stdout when something is off.

**Python.** `dev/testtimes.py` becomes a default plugin of `dev/runtests.py` (`-p testtimes`, `TL_TEST_TIMES=<run file>`). Overhead measured: tests/domain + tests/asks (326 tests), 2 runs each: CPU 11.6 / 10.7 s without, 11.0 / 10.8 s with. Within noise, far below 5 s. Memory: a dict per test, ~350 bytes of JSON per test (112 KB for 326, 764 KB for 2214).

**Where it lands.** `~/.config/task-loop/test-runs/<UTC-iso>-<pid>.json` (next to `check-durations`; the loop's own config dir, only tl writes there). The file is rewritten every 25 tests, so a killed run keeps its data (done in the plugin). One file per runtests invocation; xdist workers each write `<run>.<worker>.json`, the report merges them. Prune by age with `tl prune`.

**Format.** `{schema, run: {git_head, branch, start, argv, workers, host_load_1m}, tests: {nodeid: {setup_cpu, call_cpu, teardown_cpu, *_wall, kind}}, fixtures: {...}}`.

**Aggregation.** `dev/testtimes_report.py` takes a directory: median CPU per test over the last N runs (CPU, not wall: wall is 3-12x CPU on this host), flags tests whose median rose >50% vs the previous 20 runs, per-directory totals trend.

**Budgets, warned in stdout at the end of the run.**
- Default budget: **5 s CPU per test**, 5 s per fixture setup, and a per-run budget set in the profile (`.task-loop.json`; a new key ships one release after the code that reads it).
- One line per offender, at most 10 lines then `+N more (full list: <file>)`: `SLOW tests/land/real/test_x.py::T::test_y 9.7 s CPU > 5 s budget; fix: shrink (shared template repo)`. The fix class is inferred from facts the plugin has: spawned git/process (procsim) -> "move to real kind / shared template repo"; wall >> CPU or a sleep -> "fake clock"; many subtests/loop -> "parametrize / shrink". It is a hint, not a diagnosis.
- Today those 12 `land/real` tests would warn on every run: that is the point.

**Fail or warn: warn first, then fail.** ❌ Warn-only forever: every warned-at test gets ignored by the third run. ✅ Warn while the existing offenders are fixed (the first fortnight), then **fail the gate on a new offender** (a test not already in the baseline file, or a test that grew over budget), because the existing `LIMITS_S` in `tests/conftest.py` already fails tests over 2 s (logic) and 15 s (real), so the infrastructure for failing exists; the new budget is the same mechanism with a lower real/e2e number and a report. No silence by deleting the line.

**Known-slow tests.** Explicit marker `@pytest.mark.slow(reason="...", budget_s=12)`: the reason is required (a marker without one is itself an error), the test is judged against its own budget, and the warning prints it as `SLOW-OK (reason)` in the file but not in stdout. A rule test greps that every `slow` marker has a reason and that no more than N exist.

**.NET.** `dotnet test --logger "trx;LogFileName=<run>.trx"` already records per-test duration (TRX `<UnitTestResult duration=...>`, wall only: no CPU). Always on via `Directory.Build.props` or the wrapper that runs `dotnet test`; a small converter turns the TRX into the same JSON (nodeid = fully qualified test name, `call_wall`; `call_cpu` absent). Same budgets on wall, labelled as wall so the report never mixes the two. Fixtures: xUnit class/collection fixtures are not in the TRX; use an `ITestOutputHelper`-independent `IAsyncLifetime` timer, or skip fixtures for .NET at first. Not measured: no .NET project is in this repo.

**Cost and risk.** The Python hook adds two clock reads per phase per test and a JSON dump every 25 tests: no measurable cost here. Risk: a growing `test-runs/` dir (age prune), and warning fatigue (cap of 10 lines, one line per offender, budget set to what the suite can meet).
