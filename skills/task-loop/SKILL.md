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

`tl` below means `uv run --script ${CLAUDE_SKILL_DIR}/tl.py` (macOS and Linux; `~/.config/task-loop/bin/tl` is the same command, kept by the
SessionStart hook). It names the session for bd, records what the loop does for the dashboard, and runs slots. Python 3.15+ and uv; the
script's header declares its one dependency (msgspec), which uv installs once and caches.

## The loop profile

`docs/agents/task-loop.md` in the repo (or the file the repo's AGENTS.md names) is for you and for people; the engine
reads only `.task-loop.json` at the repo root, as committed on the base branch (`engine.base`): a rule counts once
pushed, after the next fetch; the working tree only when there is no remote. Put everything the engine must act on there:
`engine.checks` (the registry of the repo's checks: their group, `run`, and the paths that trigger them), `engine.worker_rules` (the file the
writer reads first). The profile gives:

| key | what |
|---|---|
| setup | the argv list a fresh worktree runs once (no shell) |
| pick | the `bd ready` filter: labels, lanes, what to exclude |
| gate | the checks that say `"run": "gate"` (or `"both"`) in `engine.checks`: the steps that must be green at land |
| land | the branch to land on and any rule about how (default: `git push origin HEAD:main`) |
| workers | how workers run here (what a sandbox can and cannot run, build flags): `engine.worker_rules` points at it |
| checks | the repo's own checks beyond each stage's (Unity, screenshots, log greps), as `engine.checks` |
| close | per-ticket cleanup (editors to close, caches) |
| known | flaky checks (retry once) and other standing facts |

`.task-loop.json` (optional):

```json
{"slots": {"count": 3, "dir": ".slots", "base": "origin/main",
           "setup": ["just", "agent-setup"], "setup_inputs": ["mise.toml", "client/Packages/manifest.json"],
           "keep": [".task/"]},
 "engine": {"worker_rules": "docs/agents/codex.md",
            "checks": [{"id": "fmt", "argv": ["just", "fmt-check"], "group": "static", "run": "both"},
                       {"id": "dotnet", "argv": ["just", "check-dotnet"], "group": "tests", "run": "gate", "inputs": ["src/**"]},
                       {"id": "unity-tests", "argv": ["just", "unity-tests"], "group": "tests", "when": ["client/**", "content/**"],
                        "retry": 1}]}}
```

Every command in the profile (`land`, `checks[].argv`, `slots.setup`) is an **argv list**: the program and
its arguments as separate strings, exec'd as given, no shell. A string where a list belongs, or the old `cmd` key, is refused
with a one-line error naming the allowed form: a pipeline, redirect or loop goes into a repo recipe (a just target or a script)
that the argv calls, `["just", "name"]`.

`engine.host: true` or `engine.host_beads: [ids]` says the work needs the
host: the writer runs Unity and tests itself, on this machine. Only the `.task-loop.json` committed on the base branch
(`origin/main`) counts: a worker can label its own bead or edit a checkout's config, but not main without review and
the gate. The labels `host` / `no-sandbox` alone grant nothing (a ⚠ says so); `sandbox` still turns it off for one bead.
Workers go through delegate's contract 3 (`docs/contracts/worker-run-v3.md`; the contract itself is delegate's `contract.json`): the
engine resolves delegate before any step and blocks the task when it speaks another contract. Delegate, not the engine,
tells each worker what its sandbox allows and the git and credential rules; the engine's briefs say only what the step is for.
A stopped answer carries `stop{reason, scope, permanence, retry}`, and `taskloop.domain.lanes.policy.decide` (a pure function of those facts)
is the whole policy: wait, retry, a new thread, reroute, pause, or fail. The engine matches no error text. A network
stop never counts as a lane failure or toward any retry, replan, ask or storm cap and never opens a breaker: every step
(plan, write, review, verify, look, checks, land) waits for the network on the same ref, with a short resume prompt, and
a finished answer is not asked for again (`done.json`). Past the network wait cap the run pauses (bead open, auto
label, run id and time budget kept; pause time is not charged) and the next run adopts it. Land detects a push that
already went through. A paused bead wakes when its lane is usable (`route.py status --json`, loop `GateRole`), not at a
clock. A writer is a fallback when delegate's answer says `fallback: true`; its first-choice lane is `first_lane`. Each
later write round reads `route.py status --json`: while that lane is out the fallback thread is resumed, once it is not
the engine asks fresh so the first choice takes over again (transition `fallback_retake`). The trace keeps each session's
`reason` and `context` and the run's lane manifest. A command the worker was denied shows as a warning; a `sandbox_limit`
denial never counts; denied with no answer, a second denied write in the bead (across lanes and runs), or a repeated
`secrets` stop blocks it "needs a human: <command>". `tl run-task` refuses the main checkout as a worktree (it holds the bead database and the config).

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
an answer filed on the open ask (or no ask open) lets it go. It stays blocked (`TAKEN: <why>`) while a person holds it, while an
ask waits unanswered, when a person commented after the block with no ask open (they may have parked it), when `tl hold` is set, or while
another bead blocks it. A `tl-` claim whose lease is live is another run-task of the bead, still running: `TAKEN`
names it and its engine log; wait for it, never start a second one.

A slot's git can only touch that slot: the engine's own git calls run with `GIT_DIR` and `GIT_WORK_TREE` pinned to the slot; workers and checks run unpinned (they may run git on other repos). The engine asserts before and after every node, and before the land, that ambient git agrees (`core.worktree` unset, `core.bare` not true); a worker or check that redirects git is caught before review or land, and the run stops with an owner ask. `tl doctor` warns when `extensions.worktreeConfig` is off.

The run stays on top of the base: before each stage after the first the engine fetches and, only when the base moved, rebases the task branch (a conflict gets one fix round, else the bead is blocked with the branch kept); no move, no rebase, so cached checks stay valid.
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

A plan check never runs a gate-only command either: every check of `engine.checks` that says `"run": "gate"`
(`{"id": "unity", "argv": ["just", "unity-check"], "run": "gate", "why": "fails on uncommitted client/"}`; `why` is told to the planner),
for commands red by design on the uncommitted tree a writer leaves (lifesim-fld.27.9: 68 min stuck on
`just unity-check`). The planner is told the list; a plan with one as a command (its argv starts with the prefix, wrappers like `env` aside;
`["just", "check-fmt"]` is another command) is sent back once with `<cmd> runs only in the gate at land:
<why>`, and a second such plan fails the run.

Dashboard Asks tab: open asks, most urgent first, each answerable in place. An answer is a typed record (`answer` on the ask file:
`{action, text, t, by}`, action one of `rerun`, `confirm`, `split`, `text`) and the bead is opened for the loop; first answer wins.
Answering needs no token from loopback or Tailscale (100.64.0.0/10), judged by the socket's peer address, never a header; a POST
from any other address (a container bound to 0.0.0.0, the LAN) needs the token in `~/.config/task-loop/dash.token`: `tl dash url`
prints `ANSWER LINK`s with it. The page never asks for a token up front; on a 401 it shows one inline hint. A red banner shows when
delegate says a subscription lane is out.

An ask is one record, `~/.config/task-loop/asks/<bead>.json` (`taskloop.contracts.ask.Ask`, `v` 2; an older or unknown `v` reads as
no ask), written only through `AskStore`. It has a class, one decision sentence (at most 120 characters, ends in `?`), at most 3
`tried` bullets and 2-5 options, recommended first, each with its consequence and a typed action; the card text is rendered from those
fields (`domain/asks/text.py`), never copied from a worker. The engine lints every ask before it files one; a failed lint files nothing
and the stop is an engine fault. Owner classes: open_question, external_fact, unproven, no_progress, cap_reached, over_budget,
missing_criteria, too_big. Infra trouble (lane failure, schema or bad request, sandbox denial, stale base, missing tool or recipe, a
wrong tree) is never an ask: the bead stays open with an engine fault.

The owner speaks in typed verbs only; prose never acts, and the engine reads no comment as input. `tl answer BEAD [--option N | --rerun |
--confirm | --split | --verdict confirm|work|decline | words]` (alias `tl ask answer`, `--amend` replaces an answer no run used) files the AskAnswer; `tl hint BEAD text`
sets the bead's `owner_hint` (the next brief carries it); `tl hold BEAD [--until T | --release]` sets `owner_hold` and `owner_hold_until` (neither the loop nor run-task takes the
bead before T; T is `+2h`, `90m`, `HH:MM` or ISO); `tl override BEAD replan-cap` sets `owner_override` (one more planner run past the cap);
`tl override BEAD --waive|--defer|--drop CRITERION --approval "<the owner's words>"` records the waiver in `owner_waivers` (an empty approval is refused);
`tl park BEAD` holds the bead and asks its live run to end at its next step boundary (branch and checkpoint kept; `tl hold BEAD --release`
lets it go); `tl note BEAD text` hands the live run's next worker a note (with no run going it is the hint). Both write the run's request
file (`app/run/requests.py`); the dashboard's stop writes it too and ends the run at once through its stop flag. Each verb also leaves an `Owner (tl)`
receipt comment for people. `tl ask list|show|withdraw|age`: the inbox, `tl ask show ID` (read-only) prints one ask's question, owner cause, blocking, default, similar asks, thread and outcome, ordered by what each ask unblocks, a dismissal, and how long each
ask has waited. An answer no run used within 30 minutes is an engine fault: `tl ask age` prints a `FAULT:` line and exits 1.
`app/asks/intake.py` is the one place comments are classified (`parse(comment) -> kind, fields, body`): only receipts and the engine's
own prefixes are told apart, everything else is a `note`.

Intake: a bead with no acceptance criteria is a ticket ask (class missing_criteria) before any AI step; a plan of more than
`engine.max_stages` (3) stages is a too_big ask (answer `confirm` keeps it whole, `split` stops it). A decision or ticket ask takes the
bead out of the unattended queue: with `engine.pick_label` set (lifesim: `auto`) the engine removes that label and adds
`engine.needs_info_label` (`needs-info`); answering does not relabel it, the owner does. An ask nobody answers in 3 days is parked
(status `parked`, a comment on the bead; it still waits and an answer un-parks it). Withdrawn, closed-bead and replaced asks are never
listed.

Asks come from facts, never from prose: a planner's, writer's or reviewer's question becomes an open_question ask unless an accepted
requirement already answers it (its `decided` field, quoted: the planner plans again once with the requirement quoted, a writer or
reviewer gets a fix round citing it; the engine never fills `decided` itself). A test that an accepted requirement makes fail is no
conflict between requirements: it is fixed to match the requirement, never weakened or deleted to make the code pass. What the workers
could not check is an external_fact ask; the stuck classes are unproven, no_progress, cap_reached and over_budget. A machine pause (a
`retry` answer past the wait, or `owner` for a login or setup) is no ask. A rerun with the ask open and the bead unchanged waits (no AI
step, the bead stays blocked); a filed answer starts it from its checkpoint. A `confirm` on an external_fact ask goes straight to land;
`rerun` keeps the plan; `text` goes to the planner with the answer in the brief (`## Owner answer`), keeping the accepted stages, and a
plan of no stages lands.
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
Every command (checks, gate, land, setup) is an argv list exec'd as given: no shell runs it, so there is no `&&`, pipe, redirect,
`$VAR` or `bash -c` in a check. A plan check is one of two things, parsed once from the planner's answer: `{"kind": "ref", "check": "<id>"}` (a repo check of `engine.checks`, named) or `{"kind": "adhoc", "argv": [...], "reads": ["<id>"]}` (a command of its own; `reads` declares the repo checks whose log it reads). A bare string or list, an adhoc argv that carries a shell operator word or a shell run on a command string, is sent back with a one-line message naming the allowed form, and the
dry-run checks that the program resolves on PATH (or is a file of the tree). `when` runs a
check only when the task changed a matching path; `retry` reruns a known flaky one, but never a check that timed out (exit 124: the engine's limit or the command's own; the log says "no retry: timed out after N min"). `wall_min` sets one check's time limit in place of `engine.check_wall_min` (60). `fix` (an argv list, e.g. a formatter's write mode) runs in the slot worktree before the round and what it changed is staged and checked, so the engine applies formatting instead of failing on it; a failing fix is that check's red, its output kept; the log notes "<ids>: the fix changed N files". A repo check that passed on the
same tree and base is reused; mark one `"cache": false` when it reads state git cannot see. Stage checks always run. A repo check that ran in this block exports its log and exit code to the checks after it as `TL_CHECK_LOG_<ID>` and `TL_CHECK_RC_<ID>` (id upper-cased, other characters `_`); an adhoc plan check asserts through a script that reads the variable from its environment (`{"kind": "adhoc", "argv": ["python3", "tools/assert_log.py", "TL_CHECK_LOG_UNITY_TESTS", "Passed: 12"], "reads": ["unity-tests"]}`); `reads` orders the check after that repo check and skips it when that check did not pass. An adhoc whose argv starts with a repo check's argv (wrappers like `env` aside, or `just <recipe>` with any arguments) is refused at parse: the plan is sent back naming the repo check id, and a rewrite that still has one stops the run; to require the check, name it with a ref. A quoted mention such as an echo's text is no run. A repo check may declare `"reads": [ids]` too; the profile load refuses a read of an unknown id, a cycle of reads (graphlib), a duplicate id and two ids that become one `$TL_CHECK_LOG_<ID>` name (`unity-test`, `unity_test`). **Resources.** `engine.resources` declares scarce tools, `{"unity": {"limit": 1}}` (at most `limit` at once per machine); a check says `"needs": ["unity"]` (the load refuses a need nobody declared, an unknown key, a limit under 1). A check holds one lease per need while it runs: a named lock of `~/.config/task-loop/locks`, so the limit holds across slots and loops, and a dead holder frees it. How long it queued is `waited` on its result and its `check_end` row (and a `resource` wait, outside `budget_min`). Which resources a machine has is `~/.config/task-loop/host.json`, `{"resources": ["unity"]}` (written by a person per machine; no file: the host has every declared resource; `[]`: none). On a host without a need, the check is not run: it is *deferred* (unverified, exit 86, `deferred` names the resource). The land goes on past a deferred check only when the diff did not touch what it reads (`inputs`, and unless `inputs_only` the justfile and lockfiles; a check with no `inputs` reads the whole tree, so any change counts), and says so in a note and in `gate_end.deferred`; otherwise the run ends `pause_moved`: the bead gets the label `needs:<resource>` (written under the claim's fence), is released and re-queued, and the branch is kept. **Affinity.** The pick skips a ready bead whose `needs:<resource>` label names a declared resource this host lacks (typed skip `needs`; `tl next` and `tl status` say why); the author may write the label by hand, the engine only adds it, never removes one. The plan does the same before any code is written: planned files that hit a repo check needing a resource this host lacks set the label and release the bead for a host that has it. Within one checks block each distinct command (whitespace stripped, same directory and time limit) runs once; a repeat gets the first result. Time spent waiting for a shared resource (a Unity slot, read from `unity-slot: ... got slot N after Ns` in a check's output and capped at that run's wall time; a lane wait; an editor-lock wait) is not counted in `budget_min`; the over-budget ask gives wall and waited minutes. `engine.budget_min_by_label` (`{"unity": 300}`) gives a bead with that label that larger budget. `engine.bead_token_cap` (tokens, 0 = none, the default) caps a bead over all its runs: once its earlier runs' `tokens_in + tokens_out` (cached counted in, from `traces.jsonl`) plus this run's reach it, no worker starts and the bead is blocked as a budget ask with the total (checked before every worker call). The gate runs once, on the rebased
tree at land (see **The gate**). **Repo git hooks do not run at land:** a `git push` land command is run with `--no-verify` (the engine inserts it), so every check belongs in the profile (the gate and the checks), never in a pre-push hook. A custom `land` command (not `git push`) is left as written: the repo's command owns its hooks, and the engine's LFS push below is skipped for it. **LFS and bd are the engine's:** when the worktree's `.gitattributes` has a `filter=lfs` line, the engine runs `git lfs push <remote> <ref>` for the pushed ref only, inside the land lock right before the push (git-lfs missing: the land fails, branch kept; a network error rests like the push's); after a landed bead and with the lock let go it runs `bd dolt push` (a failure blocks the bead with bd's words and the landed sha: fix the remote and rerun, the rerun finds the land and pushes again; a repo with no Dolt remote is a quiet no-op; never in a dry run). Both log their time as notes. **Work in progress is pushed:** after each accepted stage (committed as a wip commit) and only when the land is a `git push`, the engine runs `git push --no-verify --force-with-lease <remote> HEAD:refs/heads/task/<bead>` (never `-u`, never `git config`; never in a dry run), so the work survives a lost box and the other machine sees it. A failure blocks the bead with git's words (`PAUSE_NETWORK` for a network error, else `FAULT_LAND`). `tl prune` deletes that remote `task/<bead>` once the bead is closed and its land commit is on the checkout's HEAD.

**Check inputs (per-check cache).** A repo check may list `inputs`, globs over repo paths (`*` and `?` stay in one folder, `**` crosses folders, `{a,b}` is either; the same rules for tracked and gitignored files; `when` still uses shell-style matching, where `*` crosses `/`):
`"checks": [{"id": "unity-tests", "argv": ["just", "unity-tests"], "group": "tests", "inputs": ["client/**", "content/**", "src/**"]}]`.
A green result is then remembered by the key: command, the check's `env`, the hash of the tracked files matching `inputs`, the
contents of gitignored files matching them (read directly; keep the globs off build output such as `Library/`, which changes on
every run), the justfile, lockfiles (`*.lock`, `packages-lock.json`, `Directory.Packages.props`...) and `.task-loop.json`, and the
base sha. `"inputs_only": true` drops the last two groups, so only the globs count. `exclude` (same glob rules) drops matching paths from both the tracked and the ignored set, and the ignored walk is cut at excluded folders:
`"exclude": ["client/Assets/Features/*/Generated/**", "client/Assets/Views/*/Generated/**", "client/Assets/Kit/UI/Fonts/**"]`.
The ignored walk lists only under the globs' literal folders (`client/Assets/{App,Core}/**` walks `client/Assets/App/` and `.../Core/`), so a `Library/` the globs do not name is never read. An `inputs` glob that matches no tracked file switches the cache off for that check (logged `inputs glob X matches no tracked file; not cached`; `tl doctor` reports it). A hit is logged
`cached: unity-tests, inputs unchanged since round N`. No `inputs`: the key stays the whole tree plus the base. Only a pass is remembered.
**Checks in a container.** A check with `"in": "container"` (default `"host"`) runs in a Docker container on a copy of the worktree: its tracked files plus the untracked non-ignored ones go in as a tar on stdin and are unpacked on the container's own disk (never a bind mount, which is as slow as the host where an endpoint scanner taxes file access); the agent still edits the worktree on the host. `engine.container` names where: `{"image": "<name>"}` or `{"dockerfile": "<repo path>"}` (built once, tagged by the file's hash); exactly one, and a check that says `"in": "container"` needs it, or the config fails to load. What comes back is the output, the exit code and the files the check put under `$TL_ARTIFACTS`; nothing else it writes comes back, so a container check must not need to write the worktree, and it cannot read `$TL_CHECK_LOG_<ID>` files of the host. Each check's log starts with where it ran (`in container IMG` or `on host (docker not reachable)`). When `docker info` fails or times out (asked once per round) the round warns once and the check runs on the host. A stop or the wall limit kills the container by its name (`tl-check-<run>-<id>`). The base run of a red check (`base_red`) still runs on the host. Checks that need the host's tools (the Unity editor) stay `"host"`.

**Unverified (exit 86).** A check that ends with exit 86 could not run its proof (a tool, host or resource it needs is missing). The engine records it as `unverified`, never `passed`: it is not retried, never cached or reused as a pass, and not a red for the writer to fix (the round goes on to review as `checks_unverified`, not `checks_green`). Review and verify read it as not passed; the land refuses to land while a required check is unverified, naming the check, and keeps the branch. A gate step that exits 86 refuses the land the same way. The dashboard shows the word `unverified` in amber, apart from passed and failed. A check should exit 86 rather than print "skipped" or "cannot verify" and exit 0. (`taskloop.app.land.verified.deferred` is the one place a later resource rule may defer an unverified check.)

**Wall limit, no hang watchdog.** A check runs through stream-proc and is stopped only when it runs past its wall limit (or the engine itself is stopped): `wall_min` on the check, else `engine.check_wall_min` (60). The whole group is killed, descendants that called setsid too, the output so far stays in the log, the result is exit 124 and is never retried, and the bead parks at once (`check NAME timed out after N min (wall_min=N)`): the writer is not asked to fix a timeout. A check that prints nothing and uses no CPU is not stopped: it may be asleep, on a lock, on the network or Unity importing, so a really stuck one costs up to its wall limit (give a known-quick check a short `wall_min`). Each check leaves a `check_start` and a `check_end` under one id (`secs`, `exit`, `wall_hit`: the limit stopped it). `engine.check_idle_min` and a check's `idle_min` are retired: a profile that still has them loads, `tl` says `retired and ignored; safe to delete` once, and they do nothing. Renamed keys (`engine.check_timeout_min` -> `check_wall_min`, a check's `timeout_min` -> `wall_min`) fail with a message naming the new key.
**Producers and consumers.** A check that declares `reads` of a producer that was skipped (`when`), red, or left out of the round
is reported `skipped (producer X did not run)`, never failed, and costs no write round; a producer that is red
fails the round under its own name. The plan lint sends a plan back whose check reads a file of the evidence folder nothing writes.
**Red on the base.** The first red of a repo check is run once more on a clean checkout of the base commit (cached by base sha). Red
there too: the result is `base_red`, the writer is told it is not theirs, and the round does not count it (`engine.base_red: false` turns it
off). A failed check is run again (`retry`) only when its first two failures differ, never for a hang, a timeout or a compile error; a
slow check is bounded only by its wall limit. A project lock that stays after 5 min of waiting ends the check with that message, no
process is probed for the holder. The same red checks with the same output
`engine.max_same_red` (3) rounds in a row stop the run with one ask that names them. `engine.max_total_reviews` (12) counts reviews
over the whole run, replans included.
**Who runs a check.** A repo check is the writer's to run when its longest green run took at most `engine.writer_check_max_s`, or says
`"writer": true` (`false`: never) or its own `"writer_check_max_s"`; a `run: gate` check always is the engine's. `"tail_log"` names a log of the tree
whose first 20 `error CS` lines join a red's output when it shows none (the analyzers default to `client/Logs/unity-project-files.log`).
**Duplicates.** A plan check cannot be a copy of a repo check (a ref names it). Two identical adhoc commands in one block run once. 

**The gate (a registry of checks).** `engine.checks` is the one registry of the repo's checks, each named once. A check says where it runs
with `"run"`: `"stage"` (default: the round after each write), `"gate"` (a step of the gate at land; a plan check may not run its command),
or `"both"`. The gate is the checks with run `gate` or `both`, run on the rebased tree through the same machinery as a stage's round
(groups static, tests, acceptance in order; a red group skips the groups after it; `when`, `inputs`, `retry`, `env`, `in` as for any
check): a step green at its inputs (or, with none, on this tree and base) in an earlier stage round or gate run is skipped and logged
`cached`, each step has its own start and end record (seconds, exit, status) in the check log, and a red gate names the red steps
(`gate steps red: unit`) and hands their output tails to the fix round. Each step's limit is its `wall_min`, else
`engine.gate_timeout_min` (90). A step's argv may call a repo recipe (`["just", "check-dotnet"]`), so one step can be run alone by a person.
`engine.gate` and `engine.gate_only` are gone: a profile that still has one is refused at load with a message to move the steps into
`engine.checks` with `"run": "gate"`. `TL_CHECKS_GREEN` and the whole-gate cache entry are gone too: the per-check cache replaces them.

**The built-in `diff-check`.** Before any repo check, in every stage round, the gate and `tl check`, the engine runs `git diff --check <base> <tree>`
(the diff from the merge-base with `engine.base`, untracked files included; only changed files are read, `.gitattributes` decides what
counts as a whitespace error): leftover conflict markers and trailing whitespace on changed lines. It is a static check, so a red stops the
expensive ones, and it is cached by tree and base. Clean, it prints nothing and adds nothing to any prompt; red, the writer gets git's
`file:line: why` lines, the first 20, then `and N more in K files` (the full output stays in the check's log). There is no setting for it.

**`tl check [--repo DIR] [--all] [--list] [ID ...]`.** A person (or a session) runs the registry in the current worktree, with the profile
file of that worktree, through the engine's own runner and the same per-check cache (under `~/.config/task-loop/check-cache/`, the only
thing it writes there; no bd, no bead, no run folder). No ID: the gate's steps, those `when` makes due; `--all` ignores `when`; IDs run
just those checks, whatever their `run`. One line per step (id, `ok` / `FAILED` / `cached` / `skipped (why)`, seconds), then the tail of
each red step; exit 0 when all are green, 1 otherwise. `--list` prints the registry (id, run, group, when, argv), one line each, exit 0.
A repo's `just check` is then one line, `tl check` (`~/.config/task-loop/bin/tl` is the shim), and each step's own recipe
(`just check-dotnet`) stays available alone.

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

1. `tl prune` (its reconcile sweep returns the beads and slots of dead sessions, whose lease ended, to ready; the loop and `run-task` run the same lease rules).
2. Candidates: the profile's pick filter over `bd ready --json`, never a bead labelled `slot`, never `in_progress`,
   never an epic. `tl lint BEAD|--ready [--fix]` runs the bead rules (goal, acceptance criteria, Touches <= 8, no epic with
   children, no decision or output-less spike, nothing cited outside the repo); the loop refuses a failing bead once with the
   `needs-ac` label and one comment, `--fix` also drops `auto` from failing ready beads.
3. Order: beads whose `## Touches` overlap no `in_progress` bead's Touches first, by priority; overlapping ones after
   them, by priority. Overlap lowers the order, never skips a bead: the engine's rebase before landing resolves shared files.
4. Take the first one to the engine (step 2): it claims the bead as this session (`TAKEN`, exit 1 → the next
   candidate), continues `metadata.branch` when the bead was worked before, and keeps the claim alive while it runs.
   Nothing left after a fresh sweep → step 5.
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
bead. Engine settings: `.task-loop.json` → `engine` (checks, land, budgets). Every run appends one line to
`<config dir>/task-loop/traces.jsonl` (never pruned): bead, repo, branch, outcome, your session id, and every worker
session (Codex thread, `claude -p` session) with its transcript. `tl trace <id>` lists them; reflection and improvement
are done by hand from these traces for now.

Its output is verbose by default (`--quiet` for less): each step, the facts behind it (checks with exit codes, gaps,
findings, unmet requirements, cost) and **⚠ lines** for what you must look at. Read the output as it comes
(the job's output file, or the dashboard's bead page). Never do a step's work yourself; change what makes the
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

## 4. Stop

No candidate left: `tl bd dolt push`, the profile's close step; slots on: `tl slot release <name>`; slots off:
`tl worktree sunset --self-too` (removes your worktree if it is clean). One report to the owner: beads closed, beads
filed, beads blocked with their question, the dashboard address. Nothing else.

## Loop (no session per bead)

`tl loop` runs the queue by itself, one bead at a time, in the foreground of any shell (a background job, tmux, a
container); the session that starts it only watches it.

- **Start:** `tl loop [--repo DIR] [--max-beads N] [--until HH:MM] [--wait-slot-min M] [--wait-drained] [--pin]`. Several loops
  may run on one repo, each with its own actor (never its session's: bd lets an actor re-claim its own bead) and its
  own state; the race test (tl-bxk.11.1) runs two with a hand run, a hold and releases at once. Each pass: the reconcile lease rules give back tl- actors' lapsed claims and slots only (never a person's), take any free slot (none free: wait in the repo's slot line, first come first served, a line every M minutes;
  slots off: the loop's one worktree; never a held slot or one whose worktree has a live engine, see Slots), pick by the queue rule, check the bead's area and claim it under the area lock (area busy or taken → the next bead), `tl slot reset`, then
  `tl run-task` as a child with its own log, release the slot, record the outcome, next pass. `--until`: no bead
  starts after that time. No ready bead: `DRAINED`, exit 0 (`--wait-drained`: look again every 5 minutes). Every
  ready bead waiting for its area is not drained: the loop looks again every minute.
  Between beads (never mid-bead) the loop moves to the installed task-loop: the version `installed_plugins.json` names for
  task-loop (no entry: the highest version dir above its own; a dir the plugin manager did not install is never a target;
  `tl pin` / `tl rollback` decide first). Nothing is tested before the move; the loop logs
  `loop: moving to <ver> (was <ver>)` and re-execs itself (same pid; failure count, rests, `--max-beads` count and actor
  carry over in `TL_LOOP_STATE`, which is the loop's own `LoopState` JSON: one that cannot be read is dropped with one
  `reload` record and a clean pass starts). A loop or run that breaks within `loop.reload_fallback` seconds of a move goes
  back to the dir it came from, once, with a red line, and that version is skipped until it is installed again.
  `--pin` stays on the running version.
- **Constants:** the loop reads the `loop` block of `.task-loop.json` (as committed on the base branch, the working tree when
  that fails) every pass: `poll`, `heartbeat`, `drained_poll`, `pause_retry`, `fails_to_stop`, `pauses_to_rest`, `rest`,
  `area_poll`, ... A key left out keeps its default. `slots.count` is read the same way: a slot beyond it is taken no more
  (a run holding it ends normally).
- **Outcomes** (`run-task --outcome-file`, also its last stdout line as JSON): `landed` → next. `parked` (an ask was
  raised, or the bead is blocked for the owner) → next. `paused` (lane out, login, network; the bead stays open) → a
  lane back within an hour is waited for, otherwise the next bead first; either way the bead is retried at its
  `retry_after` plus a 30-90 s random margin, never a fixed step (no time: 15 min); a bead paused 3 times rests an
  hour; when every ready bead is paused the loop sleeps until the earliest is due. A hand run that pauses prints
  `PAUSED <bead>: the lane is back at <date time>; rerun then` above its outcome line (tl-bxk.10.6). `failed` (anything else, an engine crash included) → 2 in a row stop the loop
  (exit 2); a landing ends the run, parks and pauses never count. `taken` (another live session holds it) → the next
  bead, that one again in 15 minutes. A bead a gone run left assigned (a pause keeps the bead open and assigned) is
  released first, as run-task does.
- **Brief:** `tl status --brief [--json]`: first line says loop RUNNING or NOT RUNNING and when it last did anything, then asks, slots, versions and the last beads, at most 40 lines. `tl wait --bead ID|--any [--timeout S]` blocks until that run (or any live run of this repo) ends or an ask opens, prints one line and exits 0 landed/done, 10 ask, 11 parked/blocked/failed, 12 crashed, 13 no run, 14 timeout (read-only; polls the run logs). `tl handoff show` prints the handoff a compaction hands on (the plugin's hooks write and inject it).
- **Watch:** `tl loop status [--last N]`: per live loop its pid, the bead running now, its slot and since when, then one line per
  finished bead (outcome, minutes, rounds, tests added, ask, trace id). Each live loop also writes its `LoopState`
  (`<repo>-<hash>.<pid>.json`) every pass, with the queue it ranked and why each skipped bead was skipped; the dashboard's
  queue is that file. The log is `<config dir>/loop/<repo>-<hash>.jsonl`
  (fields `ts bead slot outcome minutes rounds tests_added asked trace engine_log run_log why`); each run's own output
  is beside it, one file per run. `tl next` prints what the loop would take next and why, claiming nothing.
- **Reflections into fixes:** `tl reflect digest [--since 24h] [--dry-run]` (the loop starts it once a day) clusters the last day's
  run reflections by cause and files or updates one bead per recurring cause in the repo that owns it, with run ids as
  evidence.
- **Stop:** `tl stop` writes `<config dir>/loop/<repo>-<hash>.command.json` (a `LoopCommand`: the action and the pids of
  the repo's live loops); each named loop ends after its current bead (a loop started after the stop is not named, so
  it does not read it). Slots off: each loop start reuses its session's worktree (`.worktrees/loop-<session>`); a second loop of
  the session at the same time gets its own. `tl stop --now` sends SIGTERM to the running bead (the
  engine's close step still runs, then the loop puts the bead back in the queue unclaimed and releases the slot).
  A stop during the push waits for it: a push that went through closes the bead landed, and the loop never reopens a
  bead whose land commit is on the base. Ctrl-C or SIGTERM to the loop itself is `--now`.
- **Disk:** the loop prunes at its start (`tl prune [--dry-run]`): run folders, check-round logs, engine logs and the event log older than
  `loop.keep_days` (14; beads not closed, parked ones included, keep theirs), worktrees under `loop.build_dir` (`~/Workspaces/wt`) whose HEAD
  is on origin/main, clean and idle that long, local `release/*` branches on origin/main, and local `task/*` branches of closed beads (`git branch -d` only: git's refusal keeps one); plain `git worktree remove`, never --force, and
  it says what it removed and what it kept and why. Below `loop.min_free_gb` (5) free on the config dir's disk the loop claims nothing and
  exits 0 (reason `low_disk`). A run keeps at most `engine.evidence_cap_mb` (200) of new evidence; a picture identical to one kept before is a link.
- **Leases:** the loop heartbeats the slot bead and the task bead from the slot take to the release (a slow slot
  setup included); run-task heartbeats both too (`TASK_LOOP_SLOT_BEAD`), so a loop killed with SIGKILL leaves its
  slot held until the running bead ends, then the lease lapses and the next sweep (the loop's step, `run-task`, `tl prune`) frees it.
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
folders, `{a,b}` is either; read from the base branch like the other engine keys; absent = none of the rules below). A stage whose planned files or diff match an include
and no exclude is visual: the writer is told to save a screenshot of every changed screen or state in
`.task/<bead>/evidence/` (descriptive names) or give a one-line `logic_only` reason; the reviewer gets the screenshot
paths, opens and judges them against done-when and linked decisions or reference images (`look`, one paragraph) and
sees any `logic_only` reason, which it may reject (medium finding). No screenshot and no reason is a medium finding the
engine adds. A verify item of the kind 'only the owner can judge the look' is never asked: the verifier judges it from
the screenshots; a mismatch is `wrong` (writer fix round), `open` counts as no mismatch (none saved: `wrong`). At land the
screenshots are copied into the bead's artifacts (config dir, shown on the dashboard bead page, one artifacts record) and
never committed to the repo; 'before' shots and the planner's references are the newest same-named pictures in other
beads' artifacts with the same id prefix. After the land one bead is filed: label `owner-look` (not `auto`), parent = the source bead's parent, title `Look review:
<title>`, body = each picture with a dashboard link (`/api/artifact?bead=<id>&name=<file>`) plus the reviewer's look paragraph, `related` to the source bead. No screenshots, no
bead. The Plan tab counts `owner-look` beads as 'waits on you'; add `owner-look` to `skip_labels` where `pick_label` is
unset. lifesim: `"visual_paths": {"include": ["client/Assets/Features/**", ...], "exclude": ["client/Assets/Tests/**",
"**/*.meta", "**/*.md"]}`.

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
`slot <host> <name>`: holding a slot is claiming its bead, so the lease and heartbeat come from bd and the sweep gives a lapsed one back. Leases are
local to one machine, hence the host in the title.

- A held slot belongs to one session; a dead session's slot returns through the sweep once its lease lapses.
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
  `tl slot take`) takes a ticket, `<config dir>/slots/<repo>/<seq>.json` (a `Ticket`: pid, seq, why, prio, since), made whole in
  one step (linked in, never replacing another's); numbers only grow. Only the first live ticket may take a slot, so a waiter with a
  ticket ahead of it never steals one. The line is ordered by bead priority, then arrival (tl-43k): the ticket's `prio` is the bead's priority when the waiter joined (a loop: the best bead it would run; `run-task`: its bead; P2 when unknown), so a P0 passes P2 waiters; `tl slot list` ends with the line as `WAITING N P<prio> pid why since`. A ticket whose process is gone is dropped by the next
  reader. A named take (`run-task --slot S`, `tl slot hold S`) does not queue. Every slot claim runs under one
  per-repo lock with a fresh look at the slot bead: bd lets an actor re-claim its own bead, and hand runs of one
  session share its actor. The locks are the vendored ProcessLock (the kernel drops one with its process); POSIX only.
- **Each slot has its own environment (tl-7y6.18).** Every command the engine runs for a bead (stage checks, the gate, the
  land command, shot methods, and the workers it starts through `route.py run`) gets: `TMPDIR`/`TMP`/`TEMP`,
  `DOTNET_CLI_HOME`, `NUGET_SCRATCH`, `NUGET_HTTP_CACHE_PATH` and `NUGET_PLUGINS_CACHE_PATH` under the slot's state folder
  (`<config dir>/slot-state/<repo>/<slot>/`: outside the worktree, made on use, kept when the slot is reused),
  `SharedCompilationId` and `MSBUILDNODEHANDSHAKESALT` = `<repo>-<slot>` (no shared compiler server or MSBuild node), and
  `TL_SLOT`. A run with no slot (a plain worktree) uses the worktree's name as the slot. `engine.slot_env` (str to str) adds or
  overrides keys; values may use `{slot}`, `{slot_dir}` (the state folder) and `{repo}`, any other `{name}` is refused when
  the profile loads. A check that runs in a container gets `TL_SLOT` only (host paths mean nothing inside).
  **Still shared:** the Unity licence, the user's NuGet package folder (`~/.nuget/packages`), and whatever a repo's own tools keep
  under `~/.cache` or the home folder; give those a `slot_env` key when they collide.
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
engine does, one `route.py run ROLE` per AI step (contract: `docs/contracts/worker-run-v3.md` in this plugin's repo).
Delegate picks lane, model and effort from its role table and live plan limits, and never spends API credit for the
engine. Its role names (reader → `light`, writer → `worker`, reviewer → `reviewer` with the writer's family, hard →
`hard`) are the Workers table's second column. The engine has no verifier
or judge: its own checks are the facts, and accept is a rule (checks green, nothing blocking in the review).
After every worker call, reader and reviewer included, the engine checks that the slot is still on the task branch and that the
slot gained no worktree inside it (other slots add theirs anywhere); a worker that moved either fails the bead (`FAULT_ENGINE`, naming what moved) and nothing is repaired.

The one thing the engine cannot do itself: read your Claude usage. Since delegate 0.18 Claude steps run without a
reading, but only a fresh reading keeps delegate's reserve for your own sessions, so while an engine runs feed it every
20 minutes: call `get_usage`, then `$TL usage '<plan.windows as JSON>'`.

## Beads are the record

Everything about a task lives in its bead, so any session or worker can pick it up: the plan, the named risks, every
review's findings, the reflect line with its stats, the provenance of who claimed, handed off and landed it. Chat and
worker reports are not the record.

## Context

The session runs task after task; its context window is the scarce resource. Keep in it decisions, plans and
verdicts; everything bulky goes through a worker that returns the conclusion. The task's thinking stays in the session;
move it to a per-task hard worker only if compactions start losing tasks.
