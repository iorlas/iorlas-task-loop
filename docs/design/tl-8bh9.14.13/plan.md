# Time since the agent's last command

Task: tl-8bh9.14.13. One CLI slice for [self-hosting roadmap B10](../self-hosting-roadmap.md#b10-time-since-the-last-command-dashboard-later).
Prepared against the successor tree on 2026-11-12. This is an implementation plan.

## Current code and scope

`tl step list` and `show` already display this value. `cli_composition.open_reads` supplies
`EvidenceFiles.last_command` to `StatusPorts`; `attempt_status._idle` computes whole elapsed seconds, and
`show_render`, `step_render` and `result_data` render the value. The missing requirement is its source:
`EvidenceFiles.last_command` currently reads a separate `last-command` file, written by `CommandSink` at most
once a second.

The event stream now exists: the same sink writes typed `any_agent.activity` records to the attempt's
`events.jsonl`, opened through `EvidenceFiles.open_events`. `activity_file` provides bounded tail/follow
reads for the dashboard. Use that stream as the sole source for the command timestamp. The roadmap's B10
"Built" paragraph describes the earlier sidecar implementation; this task's explicit event-stream requirement
governs this change.

Keep this one slice: replace the reader's source and remove its competing writer. No database/schema change,
new dependency, harness parsing, transcript reconstruction, persisted timestamp cache, scheduler rule or
hung-agent detection. D7 and D8 require a display fact only. Existing dashboard cards already consume
`AttemptView.last_command` and will inherit the reader; further dashboard presentation belongs to tl-8bh9.7.x.

## Observable behavior

Preserve the current CLI and JSON contract:

| Attempt/evidence | `tl step show` | `tl step list` column `last command` | JSON `last_command` |
|---|---|---|---|
| Agent attempt whose entry is observed running, with a command start at `at` | `Last command: N s ago` | `N s ago` | integer `N` |
| Running agent attempt, no recorded command start | `Last command: none` | `none` | `"none"` |
| Running agent attempt, unreadable command evidence | `Last command: unreadable` | `unreadable` | `"unreadable"` |
| Other entry states, or a checks attempt | no last-command line | `-` | `null` |

`N = max(0, int(now - at))`, with the existing injected wall clock. The entry observation remains the existing
eligibility rule; a stored worker PID is not a new liveness probe. Missing evidence never changes command exit
status or suppresses the rest of a row. Check commands and setup commands are not agent commands.

## Stream reader

Keep the public `EvidenceFiles.last_command(key) -> float | Literal["none", "unreadable"]` port. Resolve only
`events_path(key)` with the existing evidence-root confinement, and delegate file decoding/scanning to
`activity_file`. Pass the owning evidence size bound into the helper rather than importing `evidence_files`
back into `activity_file` or duplicating its constants. Reads create no directories or files.

A command means a record decoded by the existing `any_agent.activity.decode` with `kind == "command"` and
`state == "running"`: the start emitted for `events.Cmd`. Select the most recently appended such record,
using its finite wall-clock `at`. File order decides recency even if the wall clock moves backwards.
Command completions never refresh the timestamp: an orphan `CmdEnd` has no observed start, and overlapping
commands can finish out of order. Messages, tools, reasoning, waiting and errors do not count. Read raw records
before the dashboard's collapse-by-id operation; a finished record must not hide its start.

Use a native reverse scan from a snapshot of the opened file's size, with reads and line buffering bounded by
`activity_file.READ_CAP` (currently 256 KiB). Continue into earlier chunks until finding the latest start or
reaching the beginning; `activity_tail(limit)` alone can miss a command behind many later messages. Bound
total work by the supported `EVENTS_CAP` (currently 8 MiB) plus the truncation marker's fixed allowance.
An oversized file or line is `unreadable`, never an unbounded read. No cross-request cache or new cursor API
is needed. Preserve the existing dashboard tail/follow behavior.

Reader outcomes:

- A missing file, empty stream, or valid stream without a command start returns `none`.
- A final line without a newline is an in-progress append: ignore it until complete and use earlier complete
  records. A subsequent read observes it after its newline arrives.
- An I/O error, root-confinement failure, invalid UTF-8 or malformed/invalid complete record encountered while
  searching backwards returns `unreadable`. It could conceal a newer command; do not silently use an older one.
  Use the shelf decoder's validation, including rejection of nonfinite timestamps.
- The capped writer's `[truncated]` marker returns `unreadable`, including when attached to a cut JSON record.
  After that marker the stream stops recording commands, so an earlier timestamp would become misleading.
  Detect it before ignoring an incomplete suffix. Files beyond the supported size allowance are also unreadable,
  including repeated markers from resumed writers.

Once a latest valid start has been found, older damaged records cannot alter that selection. Parsing and file
failures remain display outcomes; they cannot fail an attempt or trigger any recovery operation.

## Implementation

1. Add the bounded timestamp read in `src/taskloop/activity_file.py` and route
   `EvidenceFiles.last_command` through it. Keep the typed sentinel result and evidence-root checks.
2. Remove `EvidenceFiles.note_command` and the sidecar portion of `CommandSink`: `EVERY_S`, monotonic clock,
   throttle state and constructor `tick` argument. Retain `Timeline`, capped event appends, sink lifetime,
   `WatchedHooks` and failure suppression. Each observed command start is recorded without a one-second throttle.
   Update affected test constructors. Leave existing sidecar files untouched and never read them as a fallback;
   old attempts with only a sidecar show `none`.
3. Preserve CLI composition, renderers and JSON shape unless a small correction is required to maintain the
   contract above. Keep `open_next`'s `StatusPorts` without the command-evidence reader: rounds currently use
   its no-op default. No `Next`, deadline, hold, retry, release, claim or reservation decision may consume the age.
4. Adapt the focused behavioral tests below. Retain the stream's current cursor, collapse and cap contracts.
   Keep the repository's 400 source lines/file, 80 lines/function and 800 test lines/file caps, with no new
   `Any`, `cast`, ignore escape, subprocess or direct process-control code.

## Acceptance and verification

Use pytest functions with temporary evidence, semantic process observations and injected clocks; no live agent
or tracker calls are needed.

- In `tests/steps/test_last_command.py`, drive `CommandSink -> events.jsonl -> EvidenceFiles -> show/list ->
  human/JSON` to prove exact elapsed seconds, sub-second successive commands, the existing column/line/JSON
  contract, and a future timestamp clamping to zero. Preserve the production shelf-run live-sink wiring test.
- Cover messages/tools/waiting, orphan completions, overlapping commands finishing in reverse order, reused
  harness IDs across sink instances, and backwards wall time. Only the latest appended command start counts.
- Exercise a command followed by more than `READ_CAP` bytes of messages, chunk-boundary records, missing/empty
  streams, a partial final line completed on a later read, corrupt complete records, invalid/nonfinite timestamps,
  oversized input and cap markers (standalone and attached to cut JSON). Keep reads bounded without losing a
  command solely because it is outside the most recent dashboard page.
- Verify evidence-root confinement and unreadable paths, no directories created by reads, failed writes never
  failing the sink, no new sidecar, and a conflicting pre-existing sidecar ignored and preserved.
- Compare identical stored attempts and process observations under different command evidence: absent, recent,
  old and unreadable. Only display data changes; `Next`, phase, result, deadline and database contents do not.
  An expired running entry still follows the existing deadline rule regardless of activity. Non-running entries
  and checks attempts never display agent-command age.
- Update `tests/steps/test_activity_file.py` helpers for the simplified sink constructor and retain its existing
  paging/cap tests. Retain `tests/cli/test_step_cli.py`'s CLI rendering coverage. Run existing dashboard read tests
  to verify that the shared status reader still serves its current consumer, without adding dashboard UI work.

Read the current justfile before implementation verification. Run `just check` and `just test`, the repository's
required focused gates (the latter selects `tests/cli`, `tests/steps` and `tests/rules`). During development, after
`just install`, use `uv run --frozen --no-sync python -I -m pytest -q tests/steps/test_last_command.py
tests/steps/test_activity_file.py tests/steps/test_dash_read.py tests/cli/test_step_cli.py` as one command. Do not
run a whole-suite/live harness or use baseline installs/PYTHONPATH.

Complete when the existing CLI reports running attempts' elapsed command time solely from event evidence,
the shared reader and sink have one source for this display fact, and focused tests prove both its edge cases
and independence from factory control state. Planning itself changes only this file; implementation and its
validation remain subsequent work.
