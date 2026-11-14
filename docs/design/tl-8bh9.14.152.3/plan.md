# Depth
Medium: two behaviours, stream connection status and last-round age. No owner decision is missing and no dependency is explicitly stated to be unlanded. Evidence budget: 12 model calls total. The preceding dashboard parts are ordered dependencies because they edit the same files; their mention alone does not establish that they are unlanded.

## Size
Estimated changed files: 4, including this plan, two runtime files and one existing browser fixture script. Independent behaviours: 2. Estimated model calls for one implement attempt: 35, including focused verification and the final gates.

1. Stream status: a fixture starts with a connecting label, becomes connected only after EventSource open, becomes disconnected after a transport error, and recovers on reopening. A successful board fetch alone never makes the stream connected. The header has no unconditional green indicator.
2. Last-round age: fixtures show the elapsed age of the latest recorded round for the dashboard backlog, keep aging while disconnected or without messages, and explicitly distinguish an empty available log from a failed read. Old-round and no-round fixtures cannot appear as an overall healthy factory merely because the stream connects.

## Implementation
Use the supplied glossary definitions: this is dashboard presentation of a task factory, not a new scheduler, step or source of factory control state. Reuse the existing owning `read_round_log` path through `DashPorts.log`, `/api/log` and parsed `log` stream messages. No database, schema, process observation, raw-log parsing or additional state path is needed.

In `api.js`, extend `subscribe` with a connection callback reporting a boolean on EventSource open/error. Transport errors remain distinct from JSON messages whose existing kind is `error` (an application read failure). Retain native EventSource reconnection and existing reconnect resynchronization. Also request a resync on the first open so a change between the initial HTTP snapshot and stream subscription is recovered. Keep the existing message vocabulary rather than adding a new kind for connection state. Remove the unused fixed `live` label once its sole caller is replaced.

In `app.js`, replace the unconditional green mode tag with explicit connection text and a separate last-round label within the existing `mode` element. Start at “Stream connecting”, show “Stream connected” only after open, and show “Stream disconnected” after transport error. Use neutral styling and existing tag helpers; text carries the state in both themes. Connection status is not a claim that the board, tracker or rounds are healthy. Preserve existing board failure banners, owner attention and factory-fault presentation.

Load `source.logs()` during initial synchronization and each stream resync, independently of whether the Logs screen is selected or the board read succeeds. The response already contains the dashboard backlog and reader-produced rows. Select the latest valid timestamp from rows matching that backlog and the existing `round` move. Ignore task activity, `rounds` start/wait/stop records and other backlogs. Update this observation from matching streamed log rows even while Logs is hidden, and continue forwarding every log row to `onLog`.

Display “Last recorded round … ago”, including the absolute timestamp as hover text, and reuse the existing `data-since`/`tick` mechanism so age advances on the existing one-second timer even during disconnection. Show “No round in available log” for a successfully read tail with no matching round, and “Last round unavailable” for a read failure. Do not substitute page-load time, stream-open time or a later unrelated log row. A disconnected stream leaves the last observed timestamp visibly aging. A successful empty resync replaces an obsolete observation; a failed reload does not leave an unqualified fresh-looking age. Reject invalid timestamps and qualify future timestamps as a clock discrepancy rather than showing a fabricated age of zero.

The bounded reader can omit older rounds, and `Trail.close` suppresses repeated unchanged round summaries. Thus absence means absence in the available log, and the timestamp means the last recorded round, not proof of process liveness. Showing elapsed age needs no invented freshness threshold. Guard overlapping reloads and streamed updates so an older HTTP result cannot overwrite a newer observed round or another reload's result. Keep these helpers bounded and local to the existing page module.

Extend `tests/dash/owner-attention.test.js` with `/api/log` fetch fixtures, an explicit backlog, controlled timestamps/timer callbacks and EventSource open/error dispatch. Keep its existing owner-attention and factory-fault assertions, and exercise the real `apiSource` adapter through the existing app import. Its existing HTML contains `mode`, so no HTML or CSS change is needed. No new runtime or test files are needed; this plan is the only new artifact. Add no dependency or subprocess use in factory source or tests.

## Read list
- `src/taskloop/dash/static/api.js:13-37` — source interface, log fetch, EventSource producer and reconnect behaviour to edit.
- `src/taskloop/dash/static/app.js:4-16` — imports and local presentation state integration.
- `src/taskloop/dash/static/app.js:156-190` — board failure and resync callers; preserve banners while refreshing the log observation.
- `src/taskloop/dash/static/app.js:200-232` — replace the fixed green tag, connect callbacks, log updates and existing age timer.
- `src/taskloop/dash/static/index.html:13-29` — existing header mode element and failure banner; consult only.
- `src/taskloop/dash/static/ui.js:37-51` — existing DOM and tag helpers; consult only.
- `src/taskloop/dash/static/ui.js:85-125` — duration, age and timer formatting; reuse without changing shared task timing.
- `src/taskloop/dash/static/logs.js:15-42` — existing log screen loading and streamed-row consumer to preserve.
- `src/taskloop/dash_composition.py:36-68` — owning reader composition and the dashboard backlog integration; consult only.
- `src/taskloop/dash_server.py:28-45` — log/backlog ports and polling settings; consult only.
- `src/taskloop/dash_server.py:103-139` — application errors, resync and parsed log event production; consult only.
- `src/taskloop/dash_server.py:189-198` — existing log endpoint response shape; consult only.
- `src/taskloop/round_reader.py:18-58` — owning parsed row shape and bounded reader semantics; consult only.
- `src/taskloop/evidence_files.py:172-190` — bounded tail and missing-log behaviour; consult only.
- `src/taskloop/round_log.py:10-18` — producer timestamp grammar and UTC convention; consult only.
- `src/taskloop/round_trail.py:31-59` — producer summary and repeated-round suppression; consult only.
- `src/taskloop/rounds.py:120-142` — producer use of quiet summaries between rounds; consult only.
- `tests/steps/test_round_reader.py:18-79` — existing producer/reader contracts, malformed rows and missing/bounded log coverage.
- `tests/cli/test_dash_server.py:115-139` — endpoint serialization and static-file whitelist contracts; preserve the existing endpoints and asset set.
- `tests/cli/test_dash_server.py:154-173` — incremental log publication contract; consult only.
- `tests/dash/owner-attention.html:5-14` — existing browser fixture DOM and script entry point; consult only.
- `tests/dash/owner-attention.test.js:1-48` — extend fake HTTP/EventSource ports and fixture setup.
- `tests/dash/owner-attention.test.js:93-131` — add health acceptance cases while retaining existing board/drawer/theme checks.

## Verification
Use offline semantic fixtures only; no live factory, tracker or agent calls.

- Run the existing browser fixture with its fake fetch/EventSource ports using an available offline browser runner. Exercise connecting/open/error/reopen, application `error` messages and normal log messages independently. Add connected, disconnected, old-round and no-round cases in both themes. Verify a successful snapshot cannot connect the stream; advancing the fake clock ages the label without new events; unrelated backlog/activity rows cannot freshen it; a matching streamed round does; reconnect refreshes missed rounds; read failures are explicit; future/invalid timestamps and delayed snapshot races do not mislead. Verify all previous owner-attention and fault assertions still pass. If browser tooling is absent, report that concrete validation limitation instead of claiming the fixture ran.
- Existing Python round-reader and dashboard-server tests remain the ownership/serialization checks; add no tests that merely duplicate those implementations. New assets are unnecessary, so the static whitelist stays intact.
- After all edits and focused verification, run the required gates once each, last: `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`. Preserve their actual exit status when piping. Do not rerun or broaden gates without a new change or unresolved failure.

Completion requires both acceptance criteria, preserved preceding dashboard behaviour and passing required gates. This plan attempt does not run implementation checks.
