# Stages and their handoffs: audit of night 1 and a redesign (2026-10-23)

Status: proposal, nothing built. Inputs: engine.py 0.23.6, 104 night-1 runs (10-22 09:41 .. 10-23 05:19), night 2 (10-23
18:30, 1-3 runs so far), five read-only audits (notes G1..G5, listed under Evidence).

## Verdict

- The stages are **not short of models, skills or context**. They are short of **engine rules that match what the stages
  say**, and of a **handoff record** that survives a replan. Of the 8 stage-side causes below, 7 are engine code, 1 is prompt text.
- No existing skill (tdd, code-review, diagnosing-bugs) should be added. Workers cannot load skills at all.
- Parallel beads barely collide on files (5 of 73 overlapping pairs). They collide on **knowledge**: 5 beads diagnosed the
  same flaky heap test separately.

## Denominator

The brief's "8 of 67 (12%)" reproduces: from 10-22 18:00 there are 67 beads, 8 landed on their first run with no ask.
Not measured by that number: 33 of the 67 never got past a 2-minute `bad_request` (the Codex schema bug, fixed in 0.23.5/0.23.6).
Among the 34 beads that actually ran: 8 clean (24%), 16 landed in all, 14 reached an ask. All counts below are
**beads moved**, not tokens. Docs/research beads are 45 of 98 planned night-1 beads (landed 8 of 45 vs 11 of 53 for code):
the design must work for both.

## 1. Role map

| role | exists | model / lane (night 1 sessions) | input | output contract | permissions |
|---|---|---|---|---|---|
| planner | yes, fresh session per plan/amend | claude opus-5.5 (120 of 120) | brief + PLAN_PROMPT; amend: old plan JSON + `replan.md` (last round only) | `plan`: stages[goal, files, checks, hard], cases, risks, question, options, decided, leftovers | read-only; ~12 tool calls budget |
| writer | yes, ONE session resumed across rounds | claude sonnet-5.5 173, codex gpt-6.1-sol 118 | first: brief + plan + stage; later: delta (feedback, checks) | `write`: summary, checks_run, question, bad_checks, new_cases, unchecked | workspace-write; no `bd`, no gate, often no Unity |
| reader | **no** | - | - | - | - |
| reviewer | yes, **fresh session per round**, other family when a lane is free | claude sonnet 117, codex 4 | brief + plan + stage diff + engine check results + writer summary | `review`: findings[file,line,severity,fix], unmet, unchecked, leftovers, question | read-only |
| verify | yes, fresh, once before land | claude sonnet 19 | brief + work summary + evidence + unchecked items | `verify`: per item settled/wrong/open + kind | read-only, Bash for reading commands only; denied: builds, `just soak` |
| judge | removed in 0.6.0 (10 old traces) | - | - | - | - |
| engine | code | - | runs plan checks, gate, land, files leftovers | - | - |

Lane limits (trace `lanes`): both lanes see only the brief, delegate rules and the repo's AGENTS.md/CLAUDE.md. Hidden: user
config, **every skill**, plugins, MCP servers, hooks.

## 2. Findings (evidence; beads moved)

Each: cause -> effect -> evidence. Source note in brackets.

**F1 reviewer cannot see what the plan deferred; engine routes by wording (~9 beads).** [G2 G3 G4]
- The reviewer never sees the plan's `leftovers`/accepted deviations, so it marks "follow-up beads not filed" or an already
  deferred Windows run as `unmet`. d5f.34: 9 review rounds on one unmet item, 3 replans, stuck. gfr.38 (43 min), d5f.61
  (70 min), fld.25.15 (3 runs): 8 send-backs, then the replan asks the owner. 6 of 8 asks in G4's 7 runs should not have
  reached the owner.
- `ENGINE_FILES` is a regex ("file ... follow-up|leftover"). "File beads", "to be filed as beads" miss it, so an
  `engine_step` item is judged `wrong` ("add a test") and costs 2 fix rounds (22b3: 22 nodes, 42 min; fld.25.19-0141).
- Same item blocks twice when its owner-review bead is already a leftover (iqad-1703, iqad-0123).

**F2 an empty plan is a block (2 beads).** [G3] engine.py:2495 raises "plan has no stages" unless `verify_answer`. yxbb.7 and
fld.25.16: the work was done, only bead filing remained, leftovers (5 and 9 beads) never filed, blocked again on the same text.
Also `has_criteria` rejects "Done when" (r6z, blocked in 0 s).

**F3 `bad_checks` matched by exact command string (3 beads).** [G1 G3] engine.py:2823. d5f.40: writer flagged the same broken
check 8 times with an abbreviated cmd, nothing matched, 43 min until the round cap; the re-planner found it in 56 s.
gfr.39 and 40jy lost a write the same way (40jy also: the check passed, so it was not "failed" to begin with).

**F4 the same expensive check runs 2-4 times per round (5 over-budget beads).** [G1 G3]
- Check rounds are 80-90% of the 180+ min budget runs: yxbb.2 151/227 min, fld.10 171/188, f2by 158/183, fld.27.12 163/184.
- yxbb.2 round 5: `client-soak 1` and `3` are in stage checks and in cases: 4 soaks, 134 min in one round. fld.10 rounds
  11-12: `unity-tests` 3x per round, 99 min. 22v.24: 95 s suite twice per round.
- Writers cannot compile Unity ("not compiled, engine runs it" in ~90% of writes), so each analyzer defect is a full
  cycle: 9 red rounds in 3 runs (MA0051, RCS1001, ...), f2by 5 analyzer rounds on one file. The analyzer takes 8-94 s.

**F5 verify turns notes into scope (3 beads).** [G3 G4] f2by: a reviewer note ("two poses not probed", not in the bead's
done-when) became an open `checkable` item: 2 fix rounds, 93 min (51% of the run). 5ban.16: verify asked for repeated
full-suite runs; the fix round built a new tool, the sandbox refused it, 146 min / 17.9M tokens. y7ll: verify wanted bd
comments the worker cannot read; the writer built a script in a docs bead. 40jy: an "unconfirmed cause" item cost a
900K-token fix round.

**F6 replan loses the rounds (3 beads).** [G3] The planner gets the old plan and `replan.md` (369 bytes in d5f.34: last
round's unmet items only). It does not get writer summaries, `decided`, `unchecked`, reviewer `unchecked`, what earlier
rounds fixed. Re-plan prompts are 17-24 KB (over the 12 KB warning), planners re-read code (8+ tool calls in d5f.40, fld.27.12).

**F7 writer context grows across stages (2 beads, 92% of all writer+review tokens are writer).** [G1]
Writer input is 58.2M of 9 landed runs, 92% writer, ~97% of that cache reads: cost = turns x context. yxbb.1 resumed a
187K-context writer from earlier blocked runs: 5.63M tokens in round 1 (~1.5M estimated fresh). yxbb.9: 276K context, stages
11.7M and 5.6M. d5f.44: one Codex session, 3 stages, 13 writes, 50K -> 203K. `write_fresh_above_k` exists (150K/200K) but
nothing resets at a stage boundary. No-change send-backs are ~7% of writer tokens (d5f.44 stage 1: writes 3-4 changed nothing,
identical review diffs; 40jy stage 1: 4 no-change writes, 5 reviews).

**F8 no memory shared across beads (5 beads on one flake).** [G5] `SoakTests` heap-growth flake diagnosed independently by
2s1, gfr.39, gqzz, d5f.61, 5ban.16 with five different mechanisms; gqzz/d5f.61/5ban.16 ran concurrently and none landed.
gfr.39 lost ~27 of 70 min to that flake at the land gate (the base had moved by one `.md`). No prompt mentions other running
beads, their files, known flakes, or what landed on main since the base. `## Touches` is in all 211 briefs, read by nobody
in engine/tl/loop code.

**F9 plan-time gaps.** ov3w: the engine's own gate check `unity-play-tests` fails because the branch merge-base predates the
recipe: 3 near-identical plans, stuck in 11 min (replanning cannot change engine checks). yxbb.1 ask 1 came after 46 min /
10.8M tokens; running the acceptance command at plan time shows the red soak in minute 3. v5z asked at minute 4 vs 43-70 min
for asks after rounds. gfr.38's brief lacked the parent epic's "macOS only: Windows parked".

**F10 ask rendering.** [G4] The engine maps every "needs a human" block to kind `verify`: Right/Wrong buttons on a cut-off
9 KB heredoc (5ban.16) or no question at all (y7ll). `decided` is empty in every message of G4's runs although the plan
was built on the recommended option in 4 of 6 planner asks.

## 3. Does each stage need what the previous did?

| handoff | needed | what happens | verdict |
|---|---|---|---|
| planner -> writer | files, checks, goal | writer re-opens ~1/3 of the planner's files (17-71%, regex, ±20%, 9 runs); planner is 3% of tokens | modest loss, skip |
| writer -> reviewer | diff, checks, summary | reviewer reads almost only touched files | fine |
| reviewer -> writer | the blocking set | works; but repeated lows re-listed by each fresh reviewer (40jy: same finding in 4 reviews) | add "already seen" list |
| plan -> reviewer | deferred items, leftovers | **absent** | F1 |
| round history -> planner | what each round fixed/failed | **369 bytes** | F6 |
| reviewer unchecked -> verify | only items inside the bead's done-when | everything promoted | F5 |
| checks -> verify | the engine's check logs | yxbb.6: 13 green checks with logs, verifier said "no saved log, evidence empty" | pass paths |
| bead A -> bead B | recent landings, known flakes | **absent** | F8 |

## 4. Skills (verdict per stage)

Workers cannot load skills (delegate disables them by path; `route.py` hidden list). A "skill" here is prompt text the engine
adds. Evidence decides:

| stage | candidate | verdict | why |
|---|---|---|---|
| writer | mattpocock tdd | ❌ | its core rule is "confirm seams with the user", impossible unattended; red-first already appears when asked (G1); the real writer limit is it cannot run Unity (permission, not method). 3.6 KB x every resumed round is pure token cost |
| reviewer | mattpocock code-review (12 Fowler smells + 2 sub-agents) | ❌ | sub-agents unavailable; smells raise send-backs, the cause of the loops in F1; REVIEW_PROMPT already says no style nits |
| writer on red round | diagnosing-bugs | ❌ as skill, ✅ as 2 lines in feedback | its lesson is "build a tight failing signal / run the flake under load": 22v.24 ran the flake alone. The text: "reproduce the failure the way the engine ran it before changing code" - 1 line in the red-check feedback |
| planner | new "stage skill" for plans | ❌ | planner is 3% of tokens; its failures are F2, F6, F9 (engine) |
| any | new engine-side rules in place of skills | ✅ | everything in F1-F10 |

## 5. Proposed handoff record

One file per run, `runs/<run>/handoff.json`, written by the engine, read by the engine into each prompt as a bounded section
(<= 1.5 KB each). Replaces `replan.md` as the replan input and is the single place the reviewer and verify learn "what is
already decided".

```
{
  "deferred":   [{"what", "why", "by": "plan|owner|decided"}],      // plan leftovers + accepted deviations
  "rounds":     [{"stage", "round", "writer": "<summary 300 chars>", "fixed": [...], "still_open": [...]}],
  "seen_lows":  ["file:line text"],                                  // reviewer: do not re-list
  "scope":      ["<done-when item>"],                                // verify/reviewer: unchecked outside this is a leftover, not checkable
  "engine_steps": ["file beads", ...],                               // items the engine does at land
  "check_logs": {"<check id>": "<path>"}                             // verify reads these before saying "no log"
}
```

Consumers: reviewer (`deferred`, `seen_lows`, `scope`), verify (`scope`, `engine_steps`, `check_logs`), amend planner
(`rounds`, `deferred`), fresh writer (`rounds`, in place of today's `DONE_SO_FAR`).

## 6. Parallel model

Facts: 104 runs on 3 slots; for runs of 5+ min, 2-3 concurrent for 89% of busy time; 73 overlapping pairs of different beads,
5 sharing a planned file, 11 landed pairs sharing 0; 21 rebases all clean, 20 pushes none rejected; 1 red gate after
rebase (flake, not the base). `take_area` (lane label) produced 106 skips, 100 in lane `sim`.

Rules (file locks are not needed):
1. **Shared notes, not locks**: `~/.config/task-loop/<repo>/shared.md`, engine-maintained, <= 1 KB, in planner and writer
   prompts: (a) beads running now with their planned files, (b) landed on main since this bead's base (subjects), (c) known
   flakes (id, test, the bead that diagnosed it, status). Writers append a flake via `new_flake` in `write`.
2. **Rebase before plan**, and before each stage when main moved: fixes F9/ov3w and keeps the resumed writer off an old base.
3. **`Touches`**: either wire it (planner files must cover it; overlap with a running bead = engine delays the later one)
   or drop the README/SKILL.md claim. Recommendation: drop; 5 of 73 does not justify a scheduler.
4. A known flake red at a gate = `retry once, then ask once`, not a fix round.

## 7. Changes, ranked by beads moved on the clean-land rate

| # | change | beads | effort |
|---|---|---|---|
| 1 | handoff `deferred`/`engine_steps`: reviewer sees deferred; route `engine_step` by kind not regex; leftover-backed owner item lands unverified | ~9 | M |
| 2 | accept `stages: []` (file leftovers, land); `has_criteria` takes "Done when" | 2 | S |
| 3 | `bad_checks` matched by check index/id, not exact string | 3 | S |
| 4 | dedupe by `norm_cmd` inside a round (stage + cases); writer told which checks it may run | 5 | S |
| 5 | verify scope rule: unchecked outside done-when -> leftover | 3 | S |
| 6 | handoff `rounds` replaces `replan.md` (<= 1.5 KB) | 3 | M |
| 7 | fresh writer at a stage boundary when context > 100K; "already seen" lows | 2 | S |
| 8 | shared.md: landings + flakes; rebase before plan | 5 | M |
| 9 | ask kind for "needs a human"; no Right/Wrong on a heredoc | 3 | S |
| 10 | plan-time acceptance probe (run the done-when command once before planning) | 2 | M |

Ranks 1-5 first: ~22 bead-instances out of the 34 that ran, mostly one-file engine edits. Expected effect is an estimate
(a bead often has two causes); the claim is "these beads' stated block disappears", not "all land".

## Evidence and caveats

- Notes (outside the repo): `G1-landed.md` .. `G5-parallel.md`, `run-index.json`, in the side-session notes folder of session
  local_a385467f.
- Only G1 opened worker transcripts (10 runs); G2-G4 read engine logs, briefs, plans and ask files; G5 read logs and the lifesim
  main log. File-reopen percentages come from a regex, ±20%.
- Night 2 has 1-3 runs, so no night-2 numbers are used.
- One pass by Sonnet agents, spot-checked against engine.py by line numbers; not cross-checked by a second reader.
- Quotes of engine line numbers (2495, 2823, ~3764) are from 0.23.6 and shift with edits.
