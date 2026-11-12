# tl-8bh9.7.4 plan: readable live lines of an agent attempt

Status: implementation plan for the smallest end-to-end slice. Bead: tl-8bh9.7.4 (RECENT-ACTIVITY), reads
tl-8bh9.7.1 (ATTEMPT-LINK). Page contract: [dashboard-ui.md](../dashboard-ui.md) (*Live event*).

## What exists (found, not assumed)

- `any-agent` already parses each harness stream line once into typed `HarnessEvent`s (`Cmd`, `CmdEnd`, `Tool`, `ToolEnd`,
  `Msg`, `Think`, `HarnessError`, `Reconnecting`, `WaitingForNetwork`, `Stall`, `TurnDone`...) for Codex `exec --json`,
  Claude Code stream-json and OpenCode, and `run(..., live=)` hands every event to a `LiveSink` as it is parsed. Neither
  CLI's lines carry a timestamp, and `CmdEnd.secs` is filled only when the harness measured it (Codex and Claude never do).
- The factory's `CommandSink` is that live sink today. It keeps one number (`last-command`, the time of the latest command).
- The raw stream reaches disk only when the run ends: `EvidenceFiles.capture` writes `stdout.txt` (capped 32 MiB, whole
  stream) after the process is gone. While an attempt runs there is **no file** with its events, so a live view has nothing
  to read, and `entry.log` (what the dashboard showed) holds the entry process's own fixed-word lines, not the agent.
- Attribution: an `AttemptKey` names the attempt's directory (`attempts/<hash>`); one directory per attempt, so the events
  file is attributed to the actual attempt, never to the newest run. A session shared by two attempts has two files, one each
  (no transcript is copied, no timestamp inference): tl-8bh9.7.1's session link is not needed for this slice.

## Decisions

1. **Where the model lives: `any-agent`.** New `any_agent.activity`: `Activity` (kinds `command`, `tool`, `message`, `error`,
   `waiting`; `state` `running` or `finished`; `at`, `waited_ms`, `duration_ms`, `exit_code`; text capped), `Timeline` (folds
   `HarnessEvent`s plus the caller's wall-clock time into `Activity`s: command duration from its start, `waited_ms` from the
   previous activity's end, `Think`/tokens dropped) and `encode`/`decode` (one JSON line each way, `decode` returns `None` for
   anything that is not a line of ours). The harness parsers are unchanged: they already normalize Codex and Claude events;
   the new module is the one place that turns them into display records, so a consumer never parses a vendor line.
2. **Where the file is written: the factory's live sink.** `CommandSink` also appends `encode(activity)` to a capped
   `events.jsonl` in the attempt's directory (`EvidenceFiles.open_events`, the `CappedLog` of checks and setup). This is an
   execution artifact behind its owning reader, not an event store: nothing reads it for control, it is not in factory.db, a
   failed write is dropped, and the wall clock is the sink's own (`time.time` injected). The raw stream stays `stdout.txt`.
3. **Reader behind `EvidenceFiles`:** `activity_tail(key, limit)` and `activity_after(key, cursor)`, implemented in
   `activity_file.py`. Bounded memory: the tail reads at most 256 KiB from the end, a follow reads at most 256 KiB past the
   cursor. A running record is superseded by the finished record of the same id, so the last N are N *logical* actions. The
   **cursor is opaque** (a string the caller hands back): it encodes the byte offset after the last whole line read and the
   file's identity (inode). A cursor from another file or beyond the end answers `replaced: true` with a fresh tail, so a
   replaced or truncated file never repeats or silently skips; a file that does not exist answers an empty page with
   `available: false` (evidence availability, distinct from the attempt's state).
4. **Dashboard:** `GET /api/tasks/<id>/attempts/<step>/<n>/feed[?after=<cursor>]` returns
   `{"events": [<live event>], "cursor": "...", "replaced": false, "available": true}`. `GET /api/tasks/<id>` carries the last 20
   events and the cursor in each agent attempt's `feed` / `feed_cursor` instead of only a step line. The open drawer polls the
   selected running attempt every 2 s with its cursor and stops when the drawer closes or another attempt is selected (the
   page never switches to the newest attempt by itself). The SSE `feed` message of the mock is not produced: a poll is
   per-attempt, bounded and closed with the drawer, where a hub would need every followed attempt's key.
5. **Live event shape** (dashboard-ui.md updated): `command` as before; `message` as before; new `tool` (`id`, `name`, `text`,
   `state`, `duration_ms`), `error` (`text`), `waiting` (`text`). `waited_ms` stays the "agent thought" gap. The page styles
   each kind with an emoji (the owner asked for this for agent lines; the step and column icons are unchanged).
6. **Release:** one new `any-agent` minor (0.6.0), `stream-proc` pinned by the same shelf tag as before (a new tag means the
   factory pins both at `any-agent-v0.6.0`, same commit, as `tests/rules/test_isolation.py` requires).

## Not in this slice

Old attempts (run before this change) have no `events.jsonl`: their Lines show `available: false` and "No lines recorded";
nothing is reconstructed from `stdout.txt` (single path). Full-history paging ("older") and the session-reuse segment bounds
of tl-8bh9.7.1 stay open; the reader's cursor is built so paging can add `before` later. Claude Code and Codex are covered by
recorded-line tests in any-agent; the real-run check is Codex only.

## Verification

any-agent: pytest on recorded Codex and Claude lines (existing golden streams) for `Timeline`, codec round trip. Factory:
pytest for the reader (tail, collapse, follow, replaced, bounds, absent file), the sink (writes events, never raises) and the
endpoint; then a scratch factory with a real short Codex attempt and screenshots of the drawer.
