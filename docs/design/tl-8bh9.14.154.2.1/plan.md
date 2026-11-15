# Header
Task: tl-8bh9.14.154.2.1
Base: 212f6104dbf84e1a0b93992f566cd9ac4a242fd6
Depth: small; one stylesheet behaviour.
Decision/dependency: none missing or explicitly unlanded.
Evidence budget: 6 model calls.
Size: 5 changed files, 1 behaviour, ~30 implement model calls.

## Outcome and non-goals
Suppress CSS motion while preserving final visibility and position. Existing utilities lack a reduced-motion override. Exclude indicator text, responsive layout, amber semantics and app.js programmatic card movement.

## Settled decisions
- Add one stylesheet media query.
- Regenerate shipped CSS with pinned Tailwind 4.1.11.
- Verify suppression in both input and shipped CSS.

## Open decisions
- None.

## Change map
- src/taskloop/dash/static/dash.input.css — add reduced-motion override.
- src/taskloop/dash/static/dash.css — regenerate.
- tests/dash/test_reduced_motion.py — new pytest stylesheet contract, following accessibility test conventions.
- src/taskloop/dash/static/index.html — consult stylesheet link, backdrop and drawer.
- src/taskloop/dash/static/app.js — consult newCard/renderBoard transition and flash consumers.
- src/taskloop/dash/static/ui.js — consult STATE.running pulse producer.
- src/taskloop/dash/static/logs.js — consult render pulse/entry consumers.
- src/taskloop/dash/static/lines.js — consult line entry consumer.
- src/taskloop/dash/static/taskview.js — consult bar pulse producer.
- src/taskloop/dash_server.py — consult PAGES asset serving.
- tests/dash/rail.html — consult stylesheet consumer.
- tests/dash/owner-attention.html — consult stylesheet consumer.
- docs/design/tl-8bh9.14.154.2.1/plan.md — retain plan.
- docs/design/tl-8bh9.14.154.2.1/plan-metadata.json — retain evidence.

## Read list
- src/taskloop/dash/static/dash.input.css:1-36 — utilities and keyframes.
- src/taskloop/dash/static/dash.css:1-2 — minified cascade and compiler header.
- src/taskloop/dash/static/index.html:8-40 — stylesheet and transitions.
- src/taskloop/dash/static/app.js:192-230 — CSS and programmatic motion.
- src/taskloop/dash/static/ui.js:21-25 — pulse state.
- src/taskloop/dash/static/logs.js:46-74 — live pulse and entry.
- src/taskloop/dash/static/lines.js:56-62 — entry.
- src/taskloop/dash/static/taskview.js:14-20 — skeleton pulse.
- src/taskloop/dash_server.py:28-32 — serving.
- tests/dash/rail.html:1-5 — stylesheet link.
- tests/dash/owner-attention.html:1-5 — stylesheet link.
- tests/dash/test_accessibility_markup.py:1-29 — pytest conventions.
- tests/cli/test_dash_server.py:205-208 — shipped assets.
- tests/rules/test_tool_versions.py:72-88 — compiler header constraint.
- tools/check_tool_versions.py:86-90 — artifact version check.
- mise.toml:10-10 — compiler pin.
- pyproject.toml:31-37 — package inclusion.

## Contract
Intent: prefers-reduced-motion: reduce matches. Effect: an unlayered rule for all elements and before/after pseudo-elements sets animation: none !important and transition: none !important, overriding utilities. Result: CSS effects settle immediately while final styles remain effective. Without the preference, existing effects remain available. No typed names, stored fields or process effects change.

## Work packages
1. Edit input and regenerate CSS; close A1.
2. Add the new pytest contract verifying query scope, selector coverage, disabling declarations and precedence in input and output; close A1. Verify ordinary utilities remain outside the query. After installation run the focused file; then run just check and just test once each, last, with prescribed output tails.

## Acceptance behaviours
A1. Reduced motion suppresses CSS flash, pulse, entry and transition effects across dashboard elements and pseudo-elements; ordinary motion remains available otherwise.
