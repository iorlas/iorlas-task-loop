# Header
Task: tl-8bh9.14.153.2
Base: c0d83f93d95f67487e6e3a8f70ee28da226ee324
Depth: medium
Reason: two display behaviours. No owner decision missing; predecessor landed.
Evidence budget: 12 model calls.
Size: 7 changed files incl. artifacts; 2 independent behaviours; ~55 implement model calls.

## Outcome and non-goals
Reveal full commands and show tool arguments relative to the slot. Message folding, complete finished feeds and jump to latest already work. Preserve them, event ordering, live limits and duration indicators. Exclude URL navigation, other tabs and retained-record changes.

## Settled decisions
- Keep command disclosure in `lines.js`, using native buttons with an accessible expanded state and literal text nodes.
- Compact commands occupy one line; expansion preserves the entire command, including whitespace, and permits wrapping within the content column. Short commands may expose the same control.
- Resolve the exact slot path through `SlotsStore.adopted(row.repo_id)[row.slot]`, using the existing connection port. The fenced attempt loader cannot read released attempts.
- Share tool-only formatting across detail, finished feeds and cursor updates. Preserve raw commands and activity.
- Use existing stylesheet utilities so no generated stylesheet change is expected.

## Open decisions
- None.

## Change map
- `src/taskloop/dash/static/lines.js`: `fill`, `line`, `lines`, `show`; add a command disclosure renderer used by initial and replacement rows; retain tool labels and status cells.
- `src/taskloop/dash_task.py`: `feed_event`, `_page`, `build_feed`, `_agent`; pass the exact slot path into tool projection, obtained through `SlotsStore.adopted`; translate slot-read failures to the existing unavailable result at `build_feed` and `build_task` boundaries. Consult `_history` and `history`, which reach `_agent`.
- `tests/dash/lines.test.js`: add command expansion and tool-row rendering contracts alongside `messageFolding` and `jumpToLatest`; cover initial rendering and `apply`/`show` updates.
- `tests/dash/rail.test.js`: import and invoke the new contracts in the existing both-theme runner; retain `eventIndicators`, `feedDisplay` and `liveFeedDisplay` coverage.
- `tests/steps/test_dash_read.py`: extend projection coverage through `CommandSink`, `build_task` and `build_feed`, including a released attempt and a custom slot path.
- `docs/design/tl-8bh9.14.153.2/plan.md`: new implementation plan.
- `docs/design/tl-8bh9.14.153.2/plan-metadata.json`: new preparation metadata.
- Consult `drawer.js` callers: `follow` invokes `apply`, `show`, `setNote` and `touchQuiet`; `render` uses `atBottom`; the selected body invokes `lines(a)`. Preserve these interfaces.
- Consult `dash_composition.py` callers: `_ports.task` calls `build_task`; `_ports.feed` calls `build_feed`; `_ports.body` constructs the same `TaskPorts` for `build_body`. No port expansion is needed.
- Consult producers: `CommandSink._record` writes activity; `EvidenceFiles.activity_complete`, `activity_tail`, `activity_after` supply `ActivityPage`; `_page` calls `feed_event`. `FeedEvent.cmd` is the display argument consumed by `fill`.

## Read list
- `src/taskloop/dash/static/lines.js:23-164` — initial rows, disclosure precedent, incremental replacement.
- `tests/dash/lines.test.js:1-105` — browser fixture and existing interaction assertions.
- `tests/dash/rail.test.js:1-24` — imports and attempt fixture.
- `tests/dash/rail.test.js:390-425` — initial and incremental event indicators.
- `tests/dash/rail.test.js:762-785` — both-theme runner integration.
- `src/taskloop/dash/static/drawer.js:103-130` — live update callers.
- `src/taskloop/dash/static/drawer.js:340-361` — selected attempt rendering.
- `src/taskloop/dash/static/ui.js:38-46` — text-only DOM helper.
- `src/taskloop/dash/static/dash.input.css:1-12` — Lines utility scanning.
- `src/taskloop/dash_task.py:52-109` — task ports and feed projection boundary.
- `src/taskloop/dash_task.py:128-147` — initial agent feed producer.
- `src/taskloop/dash_task.py:251-278` — history callers.
- `src/taskloop/dash_task.py:300-326` — detail failure boundary and existing slice-store composition.
- `src/taskloop/dash_model.py:128-185` — feed and attempt display shapes.
- `src/taskloop/dash_composition.py:39-66` — endpoint callers and shared ports.
- `src/taskloop/slots_store.py:18-55` — owning path reader and failure type.
- `src/taskloop/attempt_reads.py:45-80` — attempt repo and slot identity.
- `src/taskloop/attempt_loads.py:155-210` — reservation-fenced loader to avoid for history.
- `src/taskloop/command_sink.py:24-62` — unchanged activity producer.
- `src/taskloop/evidence_files.py:299-338` — activity read ports.
- `src/taskloop/activity_file.py:17-49` — decoded page and replacement semantics.
- `tests/steps/test_dash_read.py:312-336` — initial and cursor feed integration fixture.
- `tests/dash/rail.html:1-15` — browser harness with compiled stylesheet.

## Contract
Intent: reveal a command without changing its event. Effect: a local button toggles the complete `e.cmd` between a single-line preview and wrapped, whitespace-preserving text. Result: accessible expanded state and action label match the rendered state. No persisted UI field or API field is added. Replacing a command row may reset its disclosure; unrelated arrivals preserve existing expanded rows.

Intent: show a tool's file argument without its absolute slot prefix. Effect: extend `feed_event` and `_page` with explicit slot-path context, resolved from the owning slot reader using the selected attempt's repo and slot. Result: exact path occurrences below that root become relative paths; the root itself becomes `.`. Respect path boundaries, quoting and spaces; preserve unrelated absolute paths, relative paths, tool names and non-tool event text. Similar prefixes must not match.

Apply the projection at both `_agent` and `build_feed`, covering released attempts without an active reservation. A failed slot lookup or missing mapping needed for a tool projection yields the existing unavailable result with an explanation; do not guess a root from host-specific path patterns. Add no database fields, schema version or activity-file rewrites. Read-only store calls finish before rendering; no external write action occurs.

## Work packages
1. In `dash_task.py` and `test_dash_read.py`, resolve the slot path and share tool formatting across initial, finished and cursor feeds. Close acceptance B, including custom roots, release, boundary cases and lookup failures.
2. In `lines.js`, `lines.test.js` and `rail.test.js`, add command disclosure. Close acceptance A and verify tool labels and timing. Run `tests/dash/rail.html` locally in both themes and confirm its passed result.
3. Run focused projection coverage using `uv run --frozen --no-sync python -I -m pytest -q tests/steps/test_dash_read.py --tb=short | tail -40` after package installation. Finish with `just check 2>&1 | tail -60` and `just test 2>&1 | tail -40`, once each, last. The browser harness is separate from these Python gates.

## Acceptance behaviours
- A: A compact command exposes a keyboard-operable expansion control; expanding reveals its complete literal text, multiline whitespace and long tokens within the row width; collapsing restores one line. Initial, running, finished, failed and incrementally replaced command rows retain their status and duration indicators.
- B: Tool rows show slot-relative arguments for both default and custom slot locations in initial, released-attempt and live cursor feeds. Root-only, quoted and spaced paths shorten correctly; similar-prefix external paths and existing relative arguments remain intact. Raw activity and command text are unchanged; unavailable slot context produces an explained unavailable result.
