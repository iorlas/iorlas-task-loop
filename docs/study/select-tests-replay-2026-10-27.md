# Test selector replay over the last 50 landings (2026-10-27)

Input and results: `select-tests-replay-2026-10-27.json` (the checker reads it directly; `replay_result` holds the output).
Rebuild: `build_select_tests_replay.py WORKDIR OUT.json`; analysis: `analyze_select_tests_replay.py RECORDS`.

- Window: 50 version-bump landings on first-parent `origin/main`, 0.22.4 .. 0.23.58. Base = previous bump; paths = base to the commit before the bump (the bump's `plugin.json` would force the whole suite on every landing).
- Inventory: `unittest discover -s tests` on `git archive <landed>`, 639 to 1542 ids. No test body run.
- Red ids (47 across 15 landings): FAIL/ERROR lines in release suite logs and in check/gate logs of landed task-loop runs under `~/.config/task-loop`. Release logs are attributed to the first landing at or after the log time whose inventory holds every red id. Only surviving logs count; older red rounds are not recoverable.

## Result (checker, as specified)

- Misses: 0 (exit 0). Median selected share: 100%. Every landing selected the whole suite, so zero-miss is vacuous.
- Cause: 48 of 50 hit the checker's fallback "feature map names modules absent from that inventory" (HEAD map replayed on old inventories). 2 are forced by a path.
- Hub share: 41 of 50 landings (82%) touch `engine.py`, `tl.py` or `loop.py`; these select everything regardless.

## Counterfactual (not the checker's rule)

HEAD map restricted to modules that existed at each landing: median share still 100%, 0 misses; only landings 8, 12, 42, 48 select a subset (66 to 77%). Landing 12 has 3 recorded red ids, none missed.

Verdict: selection saves nothing on this window. The flat hub modules and path rules send 46 of 50 landings to the full suite.
