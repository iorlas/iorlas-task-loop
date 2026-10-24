---
name: task-loop
description: Run the autonomous task loop on a repo that tracks work in bd (beads), with several sessions in parallel worktrees or slots, taking ready beads one after another (claim, plan, delegate the code, verify, merge into main, close) until none is left, with a live dashboard of every task, session and worker. Use when the owner says "task loop", "ticket loop", "take tickets autonomously" or "do the next things on your own".
---

# task-loop

Several sessions run this at once on one repo and one shared bd database, each in its own worktree. The engine
(`tl run-task`) does each task with headless workers; the session picks, starts and watches it (attended mode). The project's rules come from its **loop profile**; this file is the method,
the profile is the project.

The owner pre-approves everything here: claiming, committing, merging into main, filing beads. No plan mode, no
approval questions. Ask only for a decision the owner owns (product direction, scope, an architecture choice that is
hard to reverse, deleting large parts): block the bead with the question and take the next. Tokens are not a
constraint; time is: run independent work in parallel, and when a check is slow, file a bead to make it faster.

Read this skill and the profile in full at the start and again after every context compaction.

`tl` below means `python3 ${CLAUDE_SKILL_DIR}/tl.py` (`python` or `py -3` on Windows). It names the session for bd,
records what the loop does for the dashboard, and runs slots. Python 3.8+, standard library only.

## The loop profile

`docs/agents/task-loop.md` in the repo (or the file the repo's AGENTS.md names) is for you and for people; the engine
reads only `.task-loop.json` at the repo root, as committed on the base branch (`engine.base`): a rule counts once
pushed, after the next fetch; the working tree only when there is no remote. Put everything the engine must act on there: `engine.gate`,
`engine.checks` (repo checks with their group and the paths that trigger them), `engine.worker_rules` (the file the
writer reads first). The profile gives:

| key | what |
|---|---|
| setup | the command a fresh worktree runs once |
| pick | the `bd ready` filter: labels, lanes, what to exclude |
| gate | the command that must be green, and whether the pre-push hook runs it |
| land | the branch to land on and any rule about how (default: `git push origin HEAD:main`) |
| workers | how workers run here (what a sandbox can and cannot run, build flags): `engine.worker_rules` points at it |
| checks | the repo's own checks beyond each stage's (Unity, screenshots, log greps), as `engine.checks` |
| close | per-ticket cleanup (editors to close, caches) |
| known | flaky checks (retry once) and other standing facts |

`.task-loop.json` (optional):

```json
{"slots": {"count": 3, "dir": ".slots", "base": "origin/main",
           "setup": "just agent-setup", "setup_inputs": ["mise.toml", "client/Packages/manifest.json"],
           "keep": [".task/"]},
 "engine": {"gate": "just check", "worker_rules": "docs/agents/codex.md",
            "checks": [{"id": "fmt", "cmd": "just fmt-check", "group": "static"},
                       {"id": "unity-tests", "cmd": "just unity-tests", "group": "tests", "when": ["client/**", "content/**"],
                        "retry": 1}]}}
```

`engine.host: true` (the 0.6 name `no_sandbox` still works) or `engine.host_beads: [ids]` says the work needs the
host: the writer runs Unity and tests itself, on this machine. Only the `.task-loop.json` committed on the base branch
(`origin/main`) counts: a worker can label its own bead or edit a checkout's config, but not main without review and
the gate. The labels `host` / `no-sandbox` alone grant nothing (a ⚠ says so); `sandbox` still turns it off for one bead.
Workers go through delegate's worker-run v2 (`docs/contracts/worker-run-v2.md`, delegate 0.29+): the engine checks
`route.py contract --json` before any step and blocks the task when delegate speaks another version. A granted host is
`--host` on every step. Delegate, not the engine, tells each worker what its sandbox allows, how to ask for a blocked
command and the git and credential rules; the engine's briefs say only what the step is for. Each answer's `next` is
the whole policy: `retry` waits until `retry_after` (past `engine.lane_wait_min` the run pauses, bead open), except
that a resumed writer answering `lane_out` (`next` retry, or owner when delegate cannot say when the lane frees) goes on at once as a new thread (delegate gives it the role's next rung, e.g.
Sonnet while Codex is out; its brief says to continue the earlier writer's work in the tree), which then becomes the
writer and the review's `--authored-by`. A writer is a fallback when delegate's answer says `fallback: true` (0.32,
feature `fallback`), else when it is that new thread; its first-choice lane is the answer's `first_lane`, else the lane
seen out (the checkpoint keeps `writer_fallback` and `fallback_lane`). Each later write round, in this run or after a
pause, reads `route.py status --json`: while that lane is out the fallback thread is resumed (no context lost); once it
is not, or when no lane is known, it asks delegate fresh with the same continue-the-work brief, so Codex takes over
again (transition `fallback_retake`); a lane the status does not list makes it no fallback (tl-bxk.10.5). Any other
writer is resumed as before. Only a retry from that new thread waits, and its `lane_out`
with no time pauses ("no lane", bead open, no ask); `owner` pauses for a login or setup or raises a verify ask, `fail` tries once more as a new thread, then fails the task. The
trace keeps each session's `reason` and `context` (instruction files, env key names) and the run's lane manifest. A command the worker was denied shows as a ⚠; denied with no answer, or a second denied write in the bead (across lanes and runs), blocks it "needs a human:
<command>". `tl run-task` refuses the main checkout as a worktree (it holds the bead database and the config).

A rerun resumes, never restarts. Each step saves a checkpoint (`~/.config/task-loop/checkpoints/<bead>.json`): the
plan, the accepted stages, the stage, round and feedback, the writer's thread, the branch head. The next run on that
branch goes on at the same stage and round with the same thread, or straight to land when every stage was accepted. A
red gate at land re-plans with the gate's output. A changed bead (an answered ask, a new comment) keeps the accepted
stages and re-plans the rest; the engine's own close lines and labels (`needs-owner-check`) are no change, so a rerun
after a failed or stopped run resumes without a plan. An ask raised in a land fix round resumes at land. A commit or
edit that is not the engine's starts over. `tl run-task ID --fresh` drops the checkpoint. A replan keeps the stages
already accepted.

Before claiming, run-task takes back what the engine itself left: a `tl-` claim whose lease ran out (a restarted
Claude session has a new actor name) is released, and a bead the engine blocked is reopened for a plain retry, or when
a comment after the block answers the open ask. It stays blocked (`TAKEN: <why>`) while a person holds it, while an
ask waits unanswered, when a person commented after the block with no ask open (they may have parked it), or while
another bead blocks it. A `tl-` claim whose lease is live is another run-task of the bead, still running: `TAKEN`
names it and its engine log; wait for it, never start a second one.

A slot's git can only touch that slot: the engine's own git calls run with `GIT_DIR` and `GIT_WORK_TREE` pinned to the slot; workers and checks run unpinned (they may run git on other repos). The engine asserts before and after every node, and before the land, that ambient git agrees (`core.worktree` unset, `core.bare` not true); a worker or check that redirects git is caught before review or land, and the run stops with an owner ask. `tl doctor` warns when `extensions.worktreeConfig` is off.

Land is one bead at a time per repo (a lock across slots and sessions): fetch, rebase, gate, push. A red gate or a
rebase conflict goes to a fix round outside the lock: the writer fixes it, every stage's checks run again (plus no
conflict markers), and a review checks the fix only; then land tries again. `engine.max_fix_rounds` (2) per bead, then
the bead is blocked and its next run re-plans with the gate's output. Limits per bead, across runs: `max_replans` (1;
a changed bead never counts), `max_fix_rounds` (2); per stage: `max_rounds` (3), `max_check_tries` (3) red checks in a
row per round.
Push to main by hand only via `tl land-lock [--repo DIR] [--wait-min N] -- CMD...` (same lock; exits with CMD's code, 75 on timeout).

Acceptance cases: the plan has at least one per acceptance criterion of the bead (the criterion quoted, a check). They
run on the last stage and again in every fix round at land. A writer may add cases it finds (the review sees them as
added by the writer); none can be removed, since the plan is the engine's. Pictures under the task's `evidence/` are
copied to the run dir at close and named on the bead.

A check proves the code and the tree only, never the tracker: the planner is told no check runs `bd` or reads `.beads/`
(writers cannot run bd, so no code change satisfies one; lifesim-fld.26.12 and fld.27.9 burned 3 rounds, 2 replans and
89 min on a `bd list | jq` check for a follow-up bead). Follow-up work the plan wants filed goes in its `leftovers`
(title, why), filed at the close with the reviews' (the Reflect `filed=` count); the checkpoint keeps the filed
titles, so a replan in a later run that names one again files no second bead. A plan with such a check in a stage,
risk or case is sent back to the planner once naming them; a second such plan fails the run.

A check never runs a gate-only command either: the gate (`engine.gate`) always, and each command prefix in
`engine.gate_only` (`"just unity-check"` or `{"cmd": "just unity-check", "why": "fails on uncommitted client/"}`),
for commands red by design on the uncommitted tree a writer leaves (lifesim-fld.27.9: 68 min stuck on
`just unity-check`). The planner is told the list; a plan with one as a command (at the start, or after `&&`, `;`,
`|`, `then`...; `just check-fmt` is another command) is sent back once with `<cmd> runs only in the gate at land:
<why>`, and a second such plan fails the run.

Dashboard Asks tab: open asks, most urgent first, each answerable in place (the answer goes on the bead as a comment and
opens it; first answer wins). Answering needs no token from loopback or Tailscale (100.64.0.0/10), judged by the socket's
peer address, never a header; a POST from any other address (a container bound to 0.0.0.0, the LAN) needs the token in
`~/.config/task-loop/dash.token`: `tl dash url` prints `ANSWER LINK`s with it. The page never asks for a token up front;
on a 401 it shows one inline hint. Every ask record has `options`, a list of `{label, answer, note?, recommended?, edit?}`,
shown as buttons above the text box (recommended first); a click posts its `answer` through the same path. verify: "Right"
(`right`, which the engine reads as accept) and "Wrong" (opens the box with `wrong: `). stuck: only answers the engine
handles: "Run again" on an over-budget ask (any answer resumes from the checkpoint, and the budget counts per run) and
"Allow one more planner run" on the re-plan cap; other stuck asks and tickets have the text box only. decision: the
planner, writer or reviewer returns `options` (2-4, each label, cost, exact answer, one `recommended`; a required schema
field, empty with no question) and the engine copies them into the record. A red banner shows when delegate says a subscription lane is out.
Push: put one shell command in `~/.config/task-loop/notify`; each new ask runs it with `TL_ASK_KIND`, `TL_ASK_BEAD`,
`TL_ASK_ID`, `TL_ASK_TEXT`. A dashboard left on an older plugin version restarts at the next session start.

Intake: a bead with no acceptance criteria (the field, or a `## Acceptance Criteria` section) is a ticket ask before any
AI step; a plan of more than `engine.max_stages` (3) stages is a split ticket, unless the owner already answered one. A decision or ticket ask takes the bead out of the unattended queue: with `engine.pick_label` set (lifesim: `auto`) the engine removes that label and adds `engine.needs_info_label` (`needs-info`), and the ask comment says so; answering does not relabel it, the owner does. Verify and stuck asks keep the label. Neither label change counts as an answer.

The owner's inbox: `tl ask list` (ordered by what each ask unblocks), `tl ask answer <bead> <text>`, `tl ask withdraw <bead> [why]`;
the dashboard's Asks page does the same with one click per option, an 8 s Undo before the comment is written, and a
Dismiss button for a stale ask. An ask's `question` is tidied (no command dumps, ends at a word) and the full text is in
its `detail`; each option carries `then` (what happens next) and `cost`. Withdrawn, closed-bead and replaced asks are never listed.

Asks: every block is an owner ask, `~/.config/task-loop/asks/<bead>.json` plus an `Ask (engine)` comment: decision
(a step's question; a planner's, writer's or reviewer's question that an accepted requirement already answers, quoted
in its `decided` field, is no ask: the planner plans again once with the requirement quoted (transition
`planner_decided`), a writer or reviewer gets a fix round citing it. A test that an accepted requirement makes fail is
no conflict between requirements: it is fixed to match the requirement, never weakened or deleted to make the code
pass (COMMON says the same); an owner's answer in the comments decides as a requirement does. The engine never fills
`decided` itself: a question whether a requirement should change reaches the owner. Only two accepted requirements in conflict or a
missing requirement reach the owner, lifesim-d5f.58, tl-bxk.10.3), verify (a denial, or what the workers could not check), stuck (rounds, replans or fix rounds used up,
budget, land failed), ticket (intake). A machine pause (a `retry` answer past the wait, or `owner` for a login or setup) is no ask. A rerun with the ask open and
the bead unchanged waits (no AI step, the bead stays blocked); the owner answers by commenting on or editing the bead,
and the rerun goes on from its checkpoint. An answered verify for a denial goes straight to land; one for what the
workers could not check goes straight to land only when the answer is a yes (a few words, each a yes: `right`,
`ok, land it`, `LGTM`), or opens with such a yes and then gives only evidence or reasons (`Right. The log shows X.`);
an answer whose first clause is not a yes, that has a `?`, a turn word anywhere (`but`, `though`, `missing`, `don't`)
or a work verb opening a clause (`Right. Fix ...`), or any other answer (`add a test that X, then land`, `wrong: ...`) goes to the planner with the
answer in its prompt, keeping the accepted stages, and a plan of no stages (the answer asks for nothing more) lands.
The writer's `unchecked` items go to the review, which reports what is still unproven after the checks.
Unchecked items are per stage: each review is shown every item still open (earlier stages' and this writer's) and its
list replaces them, so the last stage's review, which sees the whole tree and the acceptance cases run, decides what
stops the land (lifesim-gfr.31.1 stopped on a stage-1 case that stage 2 ran green); a fix round at land only adds.
Non-final stages are told a case the last stage runs is not unchecked;
a requirement, number, deletion, link, case or tooling item stops the land with a verify ask; `other` items land and
label the bead `needs-owner-check`. The review is told the gate runs at land and the passed checks are facts, and the
engine drops any unchecked item that names the gate or a check (repo or stage) that passed that round: the owner has
nothing to add to them. Once a round ran every acceptance case green (the last stage, a fix) it also drops every
`case` item, and that review is told a case is never unchecked (a case whose check does not prove its criterion is a
finding). The planner writes no case for a criterion that names the gate.
Before that verify ask, an item naming a tool (a backticked command, or a known linter or formatter such as ruff
backticked or right after a run, lint, format or check verb; prose like "the biome transition" names none) that nothing
in the tracked tree mentions (`git grep -w -I`, dot directories, CI, toolchain and agent files included), nor the
engine's gate and checks, and that is not on PATH is dropped as `not a check here`, the grep and `which` result quoted
in the Verify comment (transition `not_a_check`; lifesim-gfr.31.3 'nobody ran ruff', tl-bxk.10.9); an item for a
tool the repo uses goes on as before. Then one verifier call (delegate role `reviewer`: read-only on every rung, `--authored-by` the
writer's family) gets the task, the changed files, the evidence folder and the items, and answers per item: `settled`
with the evidence quoted (the item is dropped), `wrong` with the defect (one fix round at land, counted in
`engine.max_fix_rounds`; none left, the item goes to the owner naming the defect) or `open` (only a person can judge
it). A `settled` without quoted evidence, or an item it does not answer, is open. Only open items, and what the fix's
review leaves unchecked, reach the owner; all settled lands. It runs once per land; if it cannot run (no lane, budget)
every item goes to the owner as before. The checkpoint keeps what is unchecked, wrong items included until their fix
is accepted, so a run that pauses in the fix round verifies them again on resume and never lands them. Its answers are a `Verify (engine)` comment, the trace's `verified` and the
Reflect comment's `self-verified=` count, so the owner can audit what nobody asked him (the 2026-10-21 lifesim night:
lifesim-d5f.46, lifesim-fld.26.15, lifesim-gfr.31.1 each waited hours on an ask settled by reading in a minute).

Checks run one at a time, cheapest first: by the median of earlier runs of the same command (a small per-repo history in `~/.config/task-loop/check-durations/`; a command never run, or under 5 s, counts as free; ties go static → tests → acceptance, or static → acceptance → tests after a round red only in acceptance; a check reading `$TL_CHECK_LOG_<ID>` stays after `<ID>`). A red group skips the groups after it; any red also skips every expensive check (expected 5 s or more), after the cheap ones have run to the end. Only green runs enter the history.
Every string command (checks, gate, land) runs under `bash -e -o pipefail`: a red command before a `;` or inside a pipe
fails it; `! cmd` and `cmd || true` still pass. The planner is told to grep a file, not `cmd | grep -q` (an early
exit kills `cmd` with SIGPIPE, exit 141). `when` runs a
check only when the task changed a matching path; `retry` reruns a known flaky one, but never a check that timed out (exit 124: the engine's limit or the command's own; the log says "no retry: timed out after N min"). `timeout_min` sets one check's time limit in place of `engine.check_timeout_min` (60). A repo check that passed on the
same tree and base is reused; mark one `"cache": false` when it reads state git cannot see. Stage checks always run. A repo check that ran in this block exports its log and exit code to the checks after it as `TL_CHECK_LOG_<ID>` and `TL_CHECK_RC_<ID>` (id upper-cased, other characters `_`); a plan check asserts with `grep -q 'Passed: 12' "$TL_CHECK_LOG_UNITY_TESTS"` and never re-runs the command (a plan check containing a repo check's command is logged "re-runs <id>" and still runs as written). Within one checks block each distinct command (whitespace stripped, same directory and time limit) runs once; a repeat gets the first result. Time spent waiting for a shared resource (a Unity slot, read from `unity-slot: ... got slot N after Ns` in a check's output and capped at that run's wall time; a lane wait; an editor-lock wait) is not counted in `budget_min`; the over-budget ask gives wall and waited minutes. `engine.budget_min_by_label` (`{"unity": 300}`) gives a bead with that label that larger budget. The gate runs once, on the rebased
tree at land, and the push gets `TASK_LOOP_GATED_TREE` (the tree it passed) so a pre-push hook can skip a second run.

**Check inputs (per-check cache).** A repo check may list `inputs`, globs over repo paths (`*` and `?` stay in one folder, `**` crosses folders, `{a,b}` is either; the same rules for tracked and gitignored files; `when` still uses shell-style matching, where `*` crosses `/`):
`"checks": [{"id": "unity-tests", "cmd": "just unity-tests", "group": "tests", "inputs": ["client/**", "content/**", "src/**"]}]`.
A green result is then remembered by the key: command, the check's `env`, the hash of the tracked files matching `inputs`, the
contents of gitignored files matching them (read directly; keep the globs off build output such as `Library/`, which changes on
every run), the justfile, lockfiles (`*.lock`, `packages-lock.json`, `Directory.Packages.props`...) and `.task-loop.json`, and the
base sha. `"inputs_only": true` drops the last two groups, so only the globs count. `exclude` (same glob rules) drops matching paths from both the tracked and the ignored set, and the ignored walk is cut at excluded folders:
`"exclude": ["client/Assets/Features/*/Generated/**", "client/Assets/Views/*/Generated/**", "client/Assets/Kit/UI/Fonts/**"]`.
The ignored walk lists only under the globs' literal folders (`client/Assets/{App,Core}/**` walks `client/Assets/App/` and `.../Core/`), so a `Library/` the globs do not name is never read. An `inputs` glob that matches no tracked file switches the cache off for that check (logged `inputs glob X matches no tracked file; not cached`; `tl doctor` reports it). A hit is logged
`cached: unity-tests, inputs unchanged since round N`. No `inputs`: the key stays the whole tree plus the base. Only a pass is remembered.
**Hang watchdog.** `engine.check_idle_min` (10; 0 = off; `idle_min` on one check overrides): a check is stopped as hung only when
for that long all three are flat: its stdout/stderr, any file under the worktree (size, count, mtime; checked about every
minute) and the CPU time of its process tree. The whole group is killed, descendants that called setsid too. It is reported as
`hung: no output, file writes or CPU for N min` (`hung` in the round record, the last output lines in the brief), fails the
round, and is never retried. A timeout keeps the output collected so far in the log.
**Duplicates.** A stage check whose `&&` segment is exactly a repo check's command (no args, env prefix, `||`, `!`, `;` or subshell),
optionally redirected (`> f`, `| tee f`), after setup only (`mkdir`, `echo`...) and followed only by readers (`grep`, `test`, `wc`, `tail`,
`head`, `cat`) of that redirect target, reads the repo check's log instead of running it again, when the repo check ran green (or is cached
with its log kept). Anything else runs as written, and the repo check always runs too. At land the gate is skipped when it already passed on the same tree; the gate gets
`TL_CHECKS_GREEN=<id>,<id>` (repo checks green at their inputs), which a gate script may honour to skip those parts. The push gets
`TL_GATE_PASSED=<tree>` (plain `git rev-parse HEAD^{tree}` of the commit pushed, set only when the gate passed on it; also
`TASK_LOOP_GATED_TREE`, same value): a pre-push hook compares it with its own tree and skips the gate run when equal.

No `slots` (or `count` 0): slots are off. No profile: say so in one line, use
`bd ready --exclude-type epic --exclude-label slot`, the gate the repo's AGENTS.md names, and land on main by push.

## Identity

Sessions share one database, and bd lets the same actor claim a bead twice silently, so every bd call names the
session: `tl bd <command>` (actor `tl-<first 8 of $CLAUDE_CODE_SESSION_ID>`; `tl actor` prints it). The lifecycle
calls below (`tl claim`, `tl close`, ...) do this themselves and also record the event for the dashboard and in the
bead's provenance.

## 0. Start (once)

1. `tl dash ensure`: starts the dashboard if it is not running (one per machine) and prints its addresses. Tell the
   owner the address in one line.
2. `git worktree prune`; `tl bd dolt pull`.
3. Where to work:
   - **Slots on:** `tl slot init` once per machine (creates the slot beads `slot <host> s1..sN` and their worktrees);
     then `tl slot take` → prints `NAME DIR SLOT-BEAD`, or `NONE` (all held: stop with that one line). Keep the
     slot bead for the heartbeat. The slot's setup runs in step 1.5, only when its inputs changed.
   - **Slots off:** `tl worktree sunset` (removes clean loop worktrees of sessions that hold no lease), then
     `tl worktree start` → prints this session's worktree, made once and reused for every task.
4. Your work directory (`WT` below) is that slot or worktree. A session cannot move its own folder: work there with
   absolute paths and `git -C "$WT"`; the shell's cwd resets between calls.
5. Workers come from the iorlas-delegate plugin (required, see **Workers**). Feed it your Claude usage now:
   `get_usage`, then `$TL usage '<plan.windows as JSON>'`.

## 1. Pick (before every task)

1. `tl bd reclaim --older-than 15m` (returns dead sessions' beads, slots included, to ready).
2. Candidates: the profile's pick filter over `bd ready --json`, never a bead labelled `slot`, never `in_progress`,
   never an epic.
3. Order: beads whose `## Touches` overlap no `in_progress` bead's Touches first, by priority; overlapping ones after
   them, by priority. Overlap lowers the order, never skips a bead: the engine's rebase before landing resolves shared files.
4. Take the first one to the engine (step 2): it claims the bead as this session (`TAKEN`, exit 1 → the next
   candidate), continues `metadata.branch` when the bead was worked before, and keeps the claim alive while it runs.
   Nothing left after a fresh reclaim → step 5.
5. Slots on: before the engine, `tl slot reset <name> --bead <id>` (commits leftover work, never wipes it; reruns the
   setup only when its inputs changed). `DIRTY` → block the slot's last bead with the output, release the slot, take
   another. A bead with `metadata.slot` set continues in that slot.

## 2. Run the engine (per task)

The engine does the task; you watch it. `tl run-task <id> --worktree "$WT" [--slot <name>]` in a background Bash job
(several at once is fine, one per slot or worktree). Send its output to a log with `>>` or to one file per run: a
second `> log` on the same path truncates a live run's log (the engine writes in append mode, so it then goes on from
the cut, without a hole). It claims the bead, then: reset → plan → per stage (write →
checks run by the engine → review by the other model family) → gate → land → close. Every AI step is a headless
worker with a schema-checked answer; the close step always runs; the plan, findings and a Reflect line go into the
bead. Engine settings: `.task-loop.json` → `engine` (gate, land, budgets). Every run appends one line to
`<config dir>/task-loop/traces.jsonl` (never pruned): bead, repo, branch, outcome, your session id, and every worker
session (Codex thread, `claude -p` session) with its transcript. `tl trace <id>` lists them; reflection and improvement
are done by hand from these traces for now.

Its output is verbose by default (`--quiet` for less): each step, the facts behind it (checks with exit codes, gaps,
findings, unmet requirements, cost) and **⚠ lines** for what you must look at. Read the output as it comes
(the job's output file, or the dashboard's Engine run). Never do a step's work yourself; change what makes the
engine misbehave. Never stop a live run to apply an engine fix: the fix applies to the next bead (the running
process loaded the old engine anyway; 3 of 5 lifesim-vbo restarts on 2026-10-18 were stops for fixes, one a step before
landing). Stop a run only when it is burning a paid lane or doing damage.

| ⚠ line | what to do |
|---|---|
| owner decision needed (a question from plan, writer or reviewer) | leave it blocked, report it at the end |
| write 2+, stage stuck after N rounds | read the failing checks and the review's unmet list: a vague bead → sharpen its description and acceptance criteria, reopen; a wrong check in the plan → note it in the bead |
| a check fails the same way every round | the environment or the profile (setup, a missing tool, a flaky test): fix it or file it, then reopen |
| needed a retry / no valid output / engine error | an engine problem: file a bead in iorlas-task-loop with the engine log path, then reopen and rerun |
| tests removed, high finding, a check marked flaky failed | read the diff; if wrong, reopen with a note saying what must not change |
| budget 50% / 80% | fine once; on every task → the beads are too big (split them) or the budget too small |
| push rejected | normal under parallel landings; five in a row → main is too busy, run fewer at once |

Reopen = `tl bd update <id> --status open --append-notes "<answer or correction>"`, then run the engine again: it
continues the task branch (its earlier work is kept) and the next plan reads the note.

## 3. After each run

- Landed: next bead (step 1).
- Blocked with an owner question: leave it; it goes in the final report.
- Blocked or failed for any other reason: act on the ⚠ table, then rerun or move on.
- Every problem you notice gets a bead (`tl bd create ... --deps discovered-from:<id>`); problems with the engine
  itself go to iorlas-task-loop.

## 4. By hand (only when the engine cannot run here)

When the engine cannot run here (delegate missing or not set up, no Codex or `claude` CLI login), do the same steps
yourself in the same order, with the same records: `tl claim`, `tl stage`, plan in the bead, write through workers, run the checks
yourself, a reviewer from another model family on every stage, `tl land`, `tl close` or `tl block`.

## 5. Stop

No candidate left: `tl bd dolt push`, the profile's close step; slots on: `tl slot release <name>`; slots off:
`tl worktree sunset --self-too` (removes your worktree if it is clean). One report to the owner: beads closed, beads
filed, beads blocked with their question, the dashboard address. Nothing else.

## Loop (no session per bead)

`tl loop` runs the queue by itself, one bead at a time, in the foreground of any shell (a background job, tmux, a
container); the session that starts it only watches it.

- **Start:** `tl loop [--repo DIR] [--max-beads N] [--until HH:MM] [--wait-slot-min M] [--wait-drained] [--pin]`. Several loops
  may run on one repo, each with its own actor (never its session's: bd lets an actor re-claim its own bead) and its
  own state; the race test (tl-bxk.11.1) runs two with a hand run, a hold and releases at once. Each pass: `bd reclaim` of tl- actors' lapsed claims only (never a person's), take any free slot (none free: wait in the repo's slot line, first come first served, a line every M minutes;
  slots off: the loop's one worktree; never a held slot or one whose worktree has a live engine, see Slots), pick by the queue rule, check the bead's area and claim it under the area lock (area busy or taken → the next bead), `tl slot reset`, then
  `tl run-task` as a child with its own log, release the slot, record the outcome, next pass. `--until`: no bead
  starts after that time. No ready bead: `DRAINED`, exit 0 (`--wait-drained`: look again every 5 minutes). Every
  ready bead waiting for its area is not drained: the loop looks again every minute.
  Between beads (never mid-bead) the loop moves to the newest installed task-loop: when a newer version dir sits beside its
  own and `tl.py --help` passes there, it logs `loop: moving to <ver> (was <ver>)` and re-execs itself (same pid; failure
  count, rests, `--max-beads` count and actor carry over in `TL_LOOP_STATE`). A broken newer install is warned about once
  and skipped. `--pin` stays on the running version.
- **Outcomes** (`run-task --outcome-file`, also its last stdout line as JSON): `landed` → next. `parked` (an ask was
  raised, or the bead is blocked for the owner) → next. `paused` (lane out, login, network; the bead stays open) → a
  lane back within an hour is waited for, otherwise the next bead first; either way the bead is retried at its
  `retry_after` plus a 30-90 s random margin, never a fixed step (no time: 15 min); a bead paused 3 times rests an
  hour; when every ready bead is paused the loop sleeps until the earliest is due. A hand run that pauses prints
  `PAUSED <bead>: the lane is back at <date time>; rerun then` above its outcome line (tl-bxk.10.6). `failed` (anything else, an engine crash included) → 2 in a row stop the loop
  (exit 2); a landing ends the run, parks and pauses never count. `taken` (another live session holds it) → the next
  bead, that one again in 15 minutes. A bead a gone run left assigned (a pause keeps the bead open and assigned) is
  released first, as run-task does.
- **Watch:** `tl loop status [--last N]`: per live loop its pid, the bead running now, its slot and since when, then one line per
  finished bead (outcome, minutes, rounds, tests added, ask, trace id). The log is `<config dir>/loop/<repo>-<hash>.jsonl`
  (fields `ts bead slot outcome minutes rounds tests_added asked trace engine_log run_log why`); each run's own output
  is beside it, one file per run. `tl next` prints what the loop would take next and why, claiming nothing.
- **Stop:** `tl stop` ends every loop on the repo after its current bead (a loop started after the stop does not
  read it). Slots off: each loop start reuses its session's worktree (`.worktrees/loop-<session>`); a second loop of
  the session at the same time gets its own. `tl stop --now` sends SIGTERM to the running bead (the
  engine's close step still runs, then the loop puts the bead back in the queue unclaimed and releases the slot).
  A stop during the push waits for it: a push that went through closes the bead landed, and the loop never reopens a
  bead whose land commit is on the base. Ctrl-C or SIGTERM to the loop itself is `--now`.
- **Leases:** the loop heartbeats the slot bead and the task bead from the slot take to the release (a slow slot
  setup included); run-task heartbeats both too (`TASK_LOOP_SLOT_BEAD`), so a loop killed with SIGKILL leaves its
  slot held until the running bead ends, then the lease lapses and `bd reclaim` frees it.
- **Stopped means stopped:** a SIGTERM to the engine (`tl stop --now`, Ctrl-C to the loop) sends SIGTERM to the running
  delegate call (route.py stops its worker, which runs in a process group of its own; 0.31.1+ names it on stderr,
  `delegate: worker pid=N pgid=N`, kept in the engine lock), waits 10 s, then SIGKILLs a route.py still alive and the
  worker's group. A route.py that named no worker: the process tree is looked at before and after the wait and only
  processes unchanged in both (pid, group, start time) are SIGKILLed. A worker that still lives is logged and keeps the
  slot busy (engine lock) until it ends.

The queue rule is `.task-loop.json` → `engine`; the defaults take every ready bead:

| key | what |
|---|---|
| `pick_label` | only beads with this label (lifesim: `auto`) |
| `skip_labels` | never a bead with one of these (e.g. `["owner-taste", "needs-info"]`); epics and slots never either |
| `epic_order` | epic ids: within one priority, beads under an earlier one (at any depth) first, beads under none last |
| `epic_only` | `true`: beads under none of `epic_order` are not taken |
| `areas` | `{"area": ["epic-id" or "label", ...]}`: a bead under one of the epics (at any depth), or with one of the labels, is in that area; first entry that matches wins |
| `area_label_prefix` | e.g. `"lane:"`: after `areas`, the bead's first label with the prefix names its area (`lane:live` is area `live`) |

Order: priority first, then `epic_order`, then the lowest id (natural: `fld.26.9` before `fld.26.10`). The loop does
not look at `## Touches`; the land lock and the rebase before landing keep sequential loops safe.

**Areas (tl-bxk.11.4):** two beads of one area never run at once (they edit the same files). A bead with no area is
unrestricted. Running means a slot bead held for it (`held_bead` in its metadata, set by the loop and run-task) or a
live engine lock naming it, in any slot or worktree of the repo. The queue skips a bead whose area runs elsewhere and
`tl next` says why (`skip lifesim-2p02: area live busy: lifesim-fld.27.8 in s3`); the loop checks again and claims
under one per-repo area lock (`<config dir>/locks/area-<repo>.lock`), so two loops never both see an area free. lifesim:
`"area_label_prefix": "lane:", "areas": {"build": ["build"]}`. A hand `tl run-task` in a busy area warns
(`⚠ area live busy: ...: running anyway beside it`) and runs; `--exclusive-area` refuses it (`taken`) instead.

**Visual work with a shot table (tl-bxk.13.15, docs/design/visual-work.md):** with `engine.shot_table` (a repo path, read
from the base branch) the writer on a visual stage does not save screenshots: it returns `shots` (a method from the table,
its args, names) and the engine renders them (static checks first), a look judge (fresh, other family, only the shrunk
pictures, references and 'before' shots) returns text findings, and the writer fixes them: at most `look_rounds` (2) render
rounds per stage, a defect that comes back is a leftover. The plan's cases carry a class (test / look-objective / taste);
taste goes to the owner-look bead (metadata `looks` for the gallery) and never blocks the land. Without `shot_table` the
old way below stands.

**Look and feel (tl-bxk.10.23):** `engine.visual_paths` `{"include": [globs], "exclude": [globs]}` (`**` crosses
folders, `{a,b}` is either; read from the base branch like the other engine keys; absent = none of the rules below) and
`engine.evidence_dir` (a repo folder, lifesim `design/look-reviews`). A stage whose planned files or diff match an include
and no exclude is visual: the writer is told to save a screenshot of every changed screen or state in
`.task/<bead>/evidence/` (descriptive names) or give a one-line `logic_only` reason; the reviewer gets the screenshot
paths, opens and judges them against done-when and linked decisions or reference images (`look`, one paragraph) and
sees any `logic_only` reason, which it may reject (medium finding). No screenshot and no reason is a medium finding the
engine adds. A verify item of the kind 'only the owner can judge the look' is never asked: the verifier judges it from
the screenshots; a mismatch is `wrong` (writer fix round), `open` counts as no mismatch (none saved: `wrong`). At land the
screenshots are copied to `<evidence_dir>/<bead>/` and committed with the work (the repo's LFS attributes apply); after
the land one bead is filed: label `owner-look` (not `auto`), parent = the source bead's parent, title `Look review:
<title>`, body = each committed path plus the reviewer's look paragraph, `related` to the source bead. No screenshots, no
bead. The Plan tab counts `owner-look` beads as 'waits on you'; add `owner-look` to `skip_labels` where `pick_label` is
unset. lifesim: `"visual_paths": {"include": ["client/Assets/Features/**", ...], "exclude": ["client/Assets/Tests/**",
"**/*.meta", "**/*.md"]}, "evidence_dir": "design/look-reviews"`.

## Report (the M2 scorecard)

`tl report --planner [--prefix P] [--since T]` is the planner's cost per bead (calls, first plan / full plans again /
amends / check send-backs, input = `in`, plus cached on rows from before delegate 0.22, from delegate's `history.jsonl`); the plain report has one such line.

`tl report [--repo DIR] [--since T] [--until T] [--json]` scores a window; read-only (traces.jsonl, the loop log,
engine logs, git refs never fetched, bd show/comments). T: ISO (`2026-10-21T06:00`, `...Z`), `HH:MM`, or a
duration back (`90m`, `12h`, `2d`); default the last 24 h. `--since HH:MM` is its last past occurrence (a morning
`--since 22:00` is last night), `--until HH:MM` its next one. A run counts when it overlaps the window, so a bead asked at
05:43 and landed at 06:18 is a landing with an ask. Exit 0 on M2 PASS, 1 on FAIL.

- **Per bead:** `landed` (any run landed), else the last run decides: `parked` (an owner ask: decision, verify, stuck,
  ticket), `paused` (`paused:`/`waiting:`), `failed` (everything else, crashes included).
- **Asks:** every blocked run with an ask, plus a run that went on from an ask raised earlier (its log's `ask X is
  answered` note). An answer by anyone counts as an ask. Who answered is the first person's comment after the ask
  comment: signed `(Claude, supervising.)`, `checked by Claude` or `delegated the call to Claude` is the supervisor,
  anything else the owner, none is open.
- **Crashes:** the loop saw run-task exit with no outcome; an engine log with no `close:` and no trace, quiet 30 min
  with no live `run-task <bead>`; or a trace closed `failed: engine error ...` (an exception the engine caught). A stop
  (`failed: stopped (SIGTERM)`) is a failure, not a crash. A run's `.stderr` is route.py's (worker test tracebacks
  land there) and is never read.
- **Also:** minutes per bead (median, p90; all its runs in the window), fix rounds, replans, tokens by lane (codex,
  claude) and by role.
- **Verdict:** `M2 PASS` or `M2 FAIL: <what>` against >=10 beads, >=7 landed with no ask, 0 lost, 0 crashes.

`tl lost [--repo DIR] [--since T] [--json]` classes every commit on `task/*` and `wip/*` that is not on the base (the
base and its local/remote twin). Exit 1 when any is lost.

| class | when |
|---|---|
| landed | its patch is on the base (`git cherry`), or a land of its bead came after it: a base commit whose title ends `(<bead>)` (the engine titles its one squashed land commit so) or a trace's land sha on the base (squash lands are no ancestors) |
| reclaimed | a later run of the bead started after it (that run continues the branch) |
| pending | the bead is open, blocked or in progress and no run took it up yet: listed, not lost (a paused bead's wip) |
| unknown | bd failed (tracker unreachable): listed, never counted as lost |
| lost | the bead is closed or unknown and never landed after it, or any commit on a `wip/<slot>/<ts>` branch (`tl slot reset` makes one for a detached slot's leftovers; it has no bead, so it is lost even while the session that made it still lives) |

`tl report` counts `lost` against M2 and lists `pending` branches; `--since` limits both to commits made since T.

## Slots

A slot is a persistent worktree, set up once and reused task after task, so a heavy setup (an engine import, a large
restore) is paid once per slot, not once per task. Each slot is a bead labelled `slot` and titled
`slot <host> <name>`: holding a slot is claiming its bead, so the lease, heartbeat and reclaim come from bd. Leases are
local to one machine, hence the host in the title.

- A held slot belongs to one session; a dead session's slot returns through `reclaim` once its lease lapses
  (about 20 minutes with `--older-than 15m`).
- `tl slot reset` never discards work: leftover changes are committed on the branch they were on (or on
  `wip/<slot>/<time>` if detached) before the next task's branch is checked out.
- Setup runs again only when a file in `setup_inputs` changed; when it is heavy and several slots could rerun it at
  once, the profile's setup command must queue itself (a lock or a slot limit of its own).
- **A hand run holds its slot too:** `tl run-task ID --slot S` (no `--worktree` needed: the slot is the worktree) takes
  S's bead as the loop does, heartbeats it and releases it when the run ends, whatever the outcome (a stop included).
  `--worktree` on a slot's folder is the same as `--slot`. `--slot any` takes the next free slot in line (none free:
  `taken`; `--wait`: wait in line for one). A held slot bead is refused, also to the session's own actor
  (two hand runs from one session share its actor, and bd lets an actor re-claim its own bead): `TAKEN: slot S held by <holder> since <t>
  (<why>)`, nothing runs. Only a run the loop started (`TASK_LOOP_SLOT_BEAD` names that slot's bead) uses the loop's
  take and does not take or release again.
- **Engine lock:** every run-task writes `<worktree>/.task/engine.lock` (pid and start time, bead, route.py and the
  worker) and removes it at the end; the loop writes its own from the slot take through the slot reset until its
  run-task takes it over. The loop's slot choice, `tl slot reset` (exit 4, `BUSY`, with the lock's path and pid),
  `tl slot release` and another run-task keep off a worktree whose lock names a live process, even when the slot bead
  is open. A pid whose start time differs (reused) or a zombie is dead. `--force` on reset or release drops the lock.
  Windows: start times are not read, so a reused pid there keeps the slot busy until `--force`.
- **Hold** a slot for something that is no bead (screenshots, a person working in it):
  `tl slot hold S --why TEXT [--for MIN]` (default 60 minutes; hold again to renew), `tl slot release S` to end it. A
  hold outlives the bead's lease; the loop, run-task and `tl slot reset` keep off it until it expires, the holder's own
  runs too (release it first; reset takes `--force`). An expired hold gives the slot bead back. A slot in use, or one
  whose claim another session wins, cannot be held.
- **The slot line (tl-bxk.11.5):** every waiter for any slot (each `tl loop`, `run-task --slot any [--wait]`,
  `tl slot take`) takes a ticket, `<config dir>/slots/<repo>/<seq>.json` (pid, start time, seq, why), made whole in
  one step under the line's lock; numbers only grow. Only the first live ticket may take a slot, so a waiter with a
  ticket ahead of it never steals one; a ticket whose process is gone (pid and start time) is dropped by the next
  reader. A named take (`run-task --slot S`, `tl slot hold S`) does not queue. Every slot claim runs under one
  per-repo lock with a fresh look at the slot bead: bd lets an actor re-claim its own bead, and hand runs of one
  session share its actor. Windows: the OS locks are no-ops there (no fcntl), so these guards and the area lock hold on POSIX
  only.
- `tl slot list`: name, bead, status, holder, why (and since when, or until when for a hold), the live engine if any,
  folder.

Slots off: one worktree per loop session (`.worktrees/loop-<session>`), made at start and reused for every task;
never one worktree per task. `tl worktree sunset` removes loop worktrees whose session holds no lease, never a dirty
one, and never a worktree the loop did not make.

## Dashboard

`tl register [DIR]` adds a repo's main checkout to the dashboard before claiming a bead; DIR defaults to the current directory.

`tl dash ensure` starts one server per machine (`tl dash url` prints its addresses, `tl dash stop` stops it; it
restarts by itself when the plugin's code changes and exits after hours without a loop). It listens on 127.0.0.1 and,
when Tailscale is up, on the machine's Tailscale address; `TASK_LOOP_DASH_BIND=0.0.0.0` (e.g. in a container with a
published port) overrides; `TASK_LOOP_DASH_PORT` changes the port (default 7878). `ensure` replaces a running server whose
files are gone, whose version differs, or that lacks an address the installed one would bind; a bind failure exits non-zero
naming the address and holder pid. A copy run from a git checkout (tests, dev) uses a random loopback port unless `--port`/`--bind` are given.

It shows every repo the loop touched: the bead tree (epics and children; live, open, blocked, done), each task's
sessions and workers (the orchestrating session, its Agent-tool subagents, Codex runs, recorded `claude -p` runs) and
the live log of any of them. A Workers tab lists every worker run on the machine for the last 24 hours. It reads the
records `tl` writes, `bd list`, and the transcripts Claude Code and Codex already write; it changes nothing.
Finished tasks stay visible for 7 days.

## Workers

The loop needs these kinds of worker; it does not care what runs them.

| kind | does | never |
|---|---|---|
| reader | reads many files or logs, returns a conclusion | edits |
| writer | one stage's code, runs the stage's checks | commits, pushes, branches |
| reviewer | reads the diff against the bead and its risks; another model family than the writer | fixes |
| hard | a subtask two writers failed | |

How to get them: from the **iorlas-delegate** plugin, which every task-loop install has. You don't talk to it; the
engine does, one `route.py run ROLE` per AI step (contract: `docs/contracts/worker-run-v1.md` in this plugin's repo).
Delegate picks lane, model and effort from its role table and live plan limits, and never spends API credit for the
engine. Its role names (reader → `light`, writer → `worker`, reviewer → `reviewer` with the writer's family, hard →
`hard`) matter only in §4 by hand, where you ask delegate's skill for each worker yourself. The engine has no verifier
or judge: its own checks are the facts, and accept is a rule (checks green, nothing blocking in the review).

The one thing the engine cannot do itself: read your Claude usage. Since delegate 0.18 Claude steps run without a
reading, but only a fresh reading keeps delegate's reserve for your own sessions, so while an engine runs feed it every
20 minutes: call `get_usage`, then `$TL usage '<plan.windows as JSON>'`.

Any launcher can put its runs on the dashboard by writing agent-runs v1 records
(`docs/contracts/agent-runs-v1.md` in this plugin's repo); otherwise record them with `tl worker`.

## Beads are the record

Everything about a task lives in its bead, so any session or worker can pick it up: the plan, the named risks, every
review's findings, the reflect line with its stats, the provenance of who claimed, handed off and landed it. Chat and
worker reports are not the record.

## Context

The session runs task after task; its context window is the scarce resource. Keep in it decisions, plans and
verdicts; everything bulky goes through a worker that returns the conclusion. The task's thinking stays in the session;
move it to a per-task hard worker only if compactions start losing tasks.
