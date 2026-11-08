# DBOS / Restate / Absurd spike: pass/fail written BEFORE running (2026-11-02)

Owner criteria (Denis): no enterprise-grade sprawl; execution logs visible without another product; start on SQLite only if DBOS is good, else build/reuse small libs on SQLite. Box: 1 day. Work in a scratch dir, never in the task-loop checkout; no installs into /usr (uv/mise only); no Docker (none here).

## Questions
Q1 DBOS on Postgres as the shared state for Mac + devbox (Tailscale). Down-case: what Mac loops do when it is unreachable; local fallback design. Install/ops cost on Mac (brew) measured or sourced.
Q2 Logs without a second product: can our dashboard read workflow_status / operation_outputs / events rows directly? Which admin HTTP/CLI is free vs Conductor/cloud-only.
Q3 Versioning: recovery only on same app version. With bundle hash = version, does recovery work with 3 live versions kept on disk? How are old versions collected?
Q4 Footprint: deps under `uv run --script` (PEP 723), import time, Python 3.12 and 3.15.
Q5 Mapping: claim, prepare, plan, write, check, review, land, close as workflow+steps; idempotent push/merge/bd; human wait = end attempt; retry_at timers; kill-at-every-step matrix (~40 cells).
Q6 Compare with the ~600-line SQLite journal: lines owned, matrix results, ops cost, multi-host, exit cost.
Also Restate (BUSL ok internal) and Absurd-style "Postgres + one SQL file": one paragraph + cheap smoke test each.

## Verdict rules (fixed now)
DBOS PASSES only if ALL hold:
 P1 installs and runs under uv with no system service on SQLite mode on this box in <= 5 new top-level deps and import <= 1.5 s.
 P2 kill -9 at every one of the matrix cells resumes with no duplicate effect and no lost step (>= 95% cells clean, 0 duplicate effects).
 P3 a row-level read (plain SQL) shows run, step, input, output, error, timing: enough to draw our dashboard timeline with no extra server.
 P4 three app versions can coexist: an old run resumes on its own bundle; a new version never steals it.
 P5 Postgres mode: devbox outage leaves Mac loops in a defined state (pause, not corrupt), shown by a test with the server stopped.
 P6 wait-for-human and retry_at expressed without a polling loop of ours, or with <= 30 lines.
FAIL on any of: needs a hosted/enterprise component for logs or recovery; recovery needs an always-on separate server we would run; effects not idempotent by construction and cannot be made so in <= 50 lines each.
Restate/Absurd: pass only if smoke test kills a worker mid-step and the step resumes once; otherwise untested/fail with reason.
The SQLite journal stays the default unless DBOS passes P1-P6 AND owns fewer lines than ~600 after the mapping.
