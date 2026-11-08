# Pause reasons

Every pause reason is **transient** (the loop retries it by itself after a backoff and shows the next-retry time on the Board) or
**needs_owner** (parked with a typed reason and an ask). Source: `TABLE` and `OVERRIDES` in `src/taskloop/domain/lanes/pauses.py`
and the permanence of each reason in `packages/delegate/src/delegate/data/contract.json`. `tests/rules/test_pause_reasons.py` fails when a row here
differs from the code or a reason has no row: change the code, then this table.

Backoff: first retry after `base` seconds, doubling to `cap` seconds; `tries` is the retry budget (`0` on a transient reason:
no budget, the network probe or the fault outcome's own history policy decides; `-`: needs_owner, no retry).

| reason | producer | class | base s | cap s | tries |
|---|---|---|---|---|---|
| no_account | delegate | needs_owner | - | - | - |
| only_family_unready | delegate | transient | 60 | 3600 | 3 |
| loop_excluded | delegate | needs_owner | - | - | - |
| same_family | engine | transient | 60 | 3600 | 3 |
| busy | delegate | transient | 30 | 1800 | 3 |
| timeout | delegate | transient | 60 | 3600 | 3 |
| network | delegate | transient | 30 | 1800 | 0 |
| engine_crash | engine | transient | 60 | 3600 | 3 |
| stage_refused | engine | needs_owner | - | - | - |
| transient_infrastructure | engine | transient | 60 | 3600 | 3 |
| rate_limited | delegate | transient | 60 | 3600 | 3 |
| hung | delegate | transient | 60 | 3600 | 3 |
| vendor_blip | delegate | transient | 30 | 1800 | 3 |
| worker_failed | delegate | transient | 60 | 3600 | 3 |
| schema_invalid | delegate | transient | 60 | 3600 | 3 |
| held | delegate | transient | 60 | 3600 | 3 |
| duplicate_task | delegate | transient | 30 | 1800 | 3 |
| lock | delegate | transient | 30 | 1800 | 3 |
| crash | delegate | needs_owner | - | - | - |
| no_answer | engine | transient | 60 | 3600 | 3 |
| killed | delegate | transient | 60 | 3600 | 3 |
| worker_survived | delegate | needs_owner | - | - | - |
| engine_only_unenforced | delegate | needs_owner | - | - | - |
| overrun | engine | needs_owner | - | - | - |
| secrets | delegate | needs_owner | - | - | - |
| credit_exhausted | delegate | needs_owner | - | - | - |
| logged_out | delegate | needs_owner | - | - | - |
| bad_request | delegate | needs_owner | - | - | - |
| caller | delegate | needs_owner | - | - | - |
| setup | delegate | needs_owner | - | - | - |
| profile_ahead | engine | needs_owner | - | - | - |
| setup_own_tree | engine | needs_owner | - | - | - |
| contract_violation | engine | needs_owner | - | - | - |
| pause_lane | engine | transient | 60 | 3600 | 3 |
| pause_network | engine | transient | 30 | 1800 | 0 |
| pause_killed | engine | transient | 60 | 3600 | 3 |
| pause_moved | engine | transient | 60 | 3600 | 3 |
| fault_infra | engine | transient | 60 | 3600 | 0 |
| fault_crashed | engine | transient | 60 | 3600 | 0 |
| fault_stale_base | engine | transient | 60 | 3600 | 0 |
| fault_slot | engine | needs_owner | - | - | - |
| fault_denied | engine | needs_owner | - | - | - |
| fault_plan | engine | needs_owner | - | - | - |
| fault_land | engine | needs_owner | - | - | - |
| fault_engine | engine | needs_owner | - | - | - |
| fault_bad_request | engine | needs_owner | - | - | - |
| fault_contract_skew | engine | needs_owner | - | - | - |
| fault_base_red | engine | needs_owner | - | - | - |
| ask_decision | engine | needs_owner | - | - | - |
| ask_stuck | engine | needs_owner | - | - | - |
| ask_budget | engine | needs_owner | - | - | - |
| ask_ticket | engine | needs_owner | - | - | - |
| wait_ask | engine | needs_owner | - | - | - |
| owner_park | engine | needs_owner | - | - | - |
| plan_noop | engine | needs_owner | - | - | - |
| lost_run | engine | transient | 60 | 3600 | 3 |
| bd_push_rejected | engine | needs_owner | - | - | - |
| dolt_push_rejected | engine | needs_owner | - | - | - |
| forge_5xx | engine | transient | 30 | 1800 | 3 |
