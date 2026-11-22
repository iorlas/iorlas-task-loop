# Pilot 4: "trap" task calibration (task aa-trap1, `slug` tool), default efforts (plan high, implement medium), Codex gpt-6.1-sol

## Result in one line
NOT accepted. 8 of 8 runs (the cap) passed on the first implement attempt, with 0 failed_check repeats, in both trap variants. First-attempt pass rate 100%, outside the 25-75% window. The agents read every document the repo pointed at, even one hop away, and followed the convention.

## Setup
- Engine `aa-engine` untouched (ecb6092be, engine digest fcbebd9c), default workflow digest b10f912b: same as pilots 2 and 3, so results stay comparable.
- Guards as in pilot 3: fresh clone, tracker, db and artifacts per run; land never run; rounds stopped by pid; 2 block-randomized pairs (one a and one b, started together, random order inside the pair); host load sampled at start and end; nothing committed to the aa-engine repo. In flight 2 for every run.
- Runner `/tmp/aa/pilot4/run4.py` (v1) and `run5.py` (v2): copies of pilot 3's with the task id `aa-trap1`, the base repo and the effort lines removed (defaults).

## Task (text identical in both variants)
```
Add a tool named slug that turns text into a URL slug.

1. Lower-case the text, treat only the ASCII letters a-z and the digits 0-9 as slug characters, and replace every run of any other characters (spaces, punctuation, underscores, non-ASCII letters) with one hyphen. No hyphen at the start or end.
2. 'Hello World' -> 'hello-world', '  A  b--c!! ' -> 'a-b-c', 'C3PO_rocks' -> 'c3po-rocks'.
3. Text with no slug character at all (empty, only spaces or punctuation, only non-ASCII letters) is an error.

Add unit tests in tests/test_slug.py (unittest).
(+ Acceptance Criteria: every rule holds; PYTHONPATH=src python3 -m unittest discover -s tests passes)
```
The text states three behaviours and no convention. The plan-size gate never held a run (0 plan holds in 8).

## Trap v1 (base `74eb8072...`, hidden check `/tmp/aa/pilot4/hidden/accept.py`)
The repo has a small package `src/aa/tools/` with `registry.py` (`@register(name)`, `REGISTRY`, the only error class `ToolError` with message `<tool>: <reason>`), the sibling tools `upper.py` and `reverse.py`, `__init__.py` importing every tool module (registration happens on import), and `docs/tools.md` (table of tools plus "Adding a tool" steps). Nothing in the repo's own tests enforces the registration of a new tool. The hidden check tests behaviour and the convention: the tool is in `aa.tools.REGISTRY` after `import aa.tools`, defined in `src/aa/tools/slug.py`, raises `ToolError` with a message starting `slug: `, and the `docs/tools.md` table lists exactly the registered tools.
- Verified by hand: a reference implementation passes; a naive implementation (`slug.py` with `ValueError`, not registered, no import, no docs row) fails 3 of 4 checks, and the message says `the 'slug' tool is not in aa.tools.REGISTRY after import aa.tools: see how the existing tools are registered and loaded (docs/tools.md)`.

## Trap v2 (base `640e9bd5...` = seed `ed53b6cc...` plus profile commit, hidden check `accept2.py`)
Adds a convention one hop away: `docs/tools.md` step 5 says only "Add the release note: see CONTRIBUTING.md." `CONTRIBUTING.md` states the form: a bullet under `## Unreleased` in `CHANGELOG.md`, in exactly the form ``- tool `<name>`: <one-line summary>`` (lower-case, no trailing period). `CHANGELOG.md` already holds the entries for upper and reverse. The hidden check has all v1 checks plus the changelog one.
- Verified by hand: the reference passes (5 tests OK); the reference without the changelog bullet fails with `CHANGELOG.md has no well-formed release note for tool 'slug' under '## Unreleased' (see CONTRIBUTING.md)`.

## Per-run rows (all in flight 2; uncached = input minus cached)
| run | in flight | outcome | implement attempts | failed_check repeats | uncached in | cached in | out | agent wall s (plan+impl) | elapsed s | load1 start/end |
|---|---|---|---|---|---|---|---|---|---|---|
| v1 a01 | 2 | pass | 1 | 0 | 42913 | 245760 | 5446 | 144 (85+59) | 161 | 1.13/1.34 |
| v1 a02 | 2 | pass | 1 | 0 | 44124 | 235776 | 4710 | 127 (80+47) | 139 | 1.34/2.24 |
| v1 b01 | 2 | pass | 1 | 0 | 18664 | 263040 | 4644 | 126 (73+52) | 140 | 1.13/1.25 |
| v1 b02 | 2 | pass | 1 | 0 | 37839 | 244992 | 5600 | 146 (95+50) | 160 | 1.34/1.60 |
| v2 a01 | 2 | pass | 1 | 0 | 17945 | 224256 | 4535 | 122 (70+52) | 139 | 1.19/1.49 |
| v2 a02 | 2 | pass | 1 | 0 | 29219 | 256768 | 4928 | 143 (80+63) | 161 | 1.35/4.98 |
| v2 b01 | 2 | pass | 1 | 0 | 30202 | 237184 | 5670 | 146 (98+48) | 160 | 1.19/1.35 |
| v2 b02 | 2 | pass | 1 | 0 | 30709 | 264320 | 7580 | 189 (141+49) | 204 | 1.35/9.71 |

0 answer repairs, 0 plan holds, 0 infrastructure failures. Per run about 270-290k input tokens in total (about 18-44k uncached) and 4.5-7.6k output.

## Why the trap does not fire (evidence)
- The artifacts of all 4 v1 runs and all 4 v2 runs name `docs/tools.md`; the artifacts of all 4 v2 runs also name `CONTRIBUTING.md`, none of the v1 runs do. The agent reads the docs the repo mentions and follows each hop. A convention discoverable "from the repo" is therefore found by this agent about 100% of the time (0 of 8 failures; a one-sided 95% bound on the first-attempt failure rate is still about 31%).
- A pointer in prose is cheap to follow. What this agent does not find, if anything, is a fact that is NOT referenced from anywhere it reads.

## Not accepted: what would likely work (untested; the 8-run cap is used up)
1. Put the convention only in code that the agent does not need to open (for example a registry check that runs at import time in a module the agent does not edit and which fails only in an unrelated command), without any doc pointer. Risky for honesty: the agent then cannot know, so the feedback would be the only source. This tests feedback quality more than discovery, which is exactly the variable of the A/B, so it may be the right design; the owner decides.
2. A check that depends on behaviour of existing code the agent must run to see (for example an existing function whose output format the new tool must match, visible only by calling it).
3. Lower implement effort did not change the pass rate in pilot 3 (4/4 at low) and likely will not here either.

## Cost of an 8-pair A/B (default.toml vs attempt-budget.toml), if a setup with repeats exists
- 16 runs at about 280k input (about 30k uncached) and about 5.3k output per run without repeats: about 4.5M input tokens (about 0.5M uncached) and about 85k output tokens.
- Wall: about 2.3-3.5 minutes per pair (run concurrently), so about 20-30 minutes for 8 pairs one after another.
- Each failed first attempt adds roughly one more implement attempt (about 60-100k input, 1-3k output).

## Decisions made
- Task text states behaviour only; the convention lives in the repo (registry, sibling tools, docs). The hidden check is outside the repo and its failure messages name the place to look, not the fix.
- Variant 2 raised difficulty by one hop (docs to CONTRIBUTING.md) rather than hiding the rule; kept the task text byte-identical so that only the repo differs.
- Used the supervisor's stop rules: 4 + 4 runs, no run beyond the 8-run cap, no infrastructure failures.
- Profile `.task-loop.json` in the base points at the hidden check path (as in pilots 2 and 3); agents ran it from there. No agent event stream was grepped for reads of the hidden check's cases (not repeated this time).

## Improvements noticed
### A/A method
- The calibration is expensive for a null result: three pilots (22+ runs) never produced a failed first attempt. A cheaper first screen is a single run per candidate task, then one pair, instead of 4 runs per variant.
- Verify the failure probability with the agent's own exploration trace before building a task: the artifacts show which documents it opens; a trap needs a fact outside that set.
- Report uncached and cached input separately (done); plan wall varies much more (70-141 s) than implement (47-63 s).
### Tooling
- No command gives the files each attempt opened; the harness artifacts have to be grepped (done here with `grep -l`). A per-attempt "paths read" column in `tl attempt export` would make the leak and discovery check one query.
- The calibration runner is now three near-copies (run3/run4/run5). A parameterized runner (task, base, effort, pairs) would remove the copies.
### Storage
- Run trees under `/tmp/aa/pilot4/cal1/runs` and `cal2/runs` (about 3 MB each), bases `/tmp/aa/pilot4/base`, `base2`, hidden checks in `/tmp/aa/pilot4/hidden`. Nothing deleted. Nothing committed to the repo.
