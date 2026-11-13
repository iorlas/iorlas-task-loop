# Self-hosting real run 2: reflection (2026-11-13)

Status: reflection of the second real run; no decision here is implemented. Times are UTC from `rounds.log`.
Real run 1 is `self-hosting-real-run-1.md`.

## What ran

Run 2 put five beads through the factory on 4 slots: `.113` (docs and CLI consistency), `.111` (refusal guidance), `.112`
(vocabularies and ids), `.132` (`step list` hold cause) and `.135` (agent friction), plus a dashboard fix session and my
hand-merged PRs (#764 to #767) in parallel. Results at the time of writing: `.113` landed; `.111` and `.112` passed their
checks but could not land (conflict with `main`, caused by the hand-merged PRs) and were restarted; `.132` passed twice, held once;
`.135` and `.112` held (`needs_owner`, `answer:schema_invalid`) with dirty slots.

## What was good

- Restart with an intact factory.db continued; `--retake-lapsed` took over claims after a deliberate discard.
- `step show` told the cause of every hold in one command (the agent's explanation, the Held line, the next action).
- The dashboard found real problems within minutes of use (duplicate attempt keys, hidden verification) and each was fixed
  the same day.
- The checks and the land re-check caught two real breakages (a stale test, a red `main`) before anything was pushed.
- A 5-minute watch with a push notification turned "I check now and then" into "it tells me".

## What was bad

- **Work lost to conflicts**: `.111` and `.112` (about 45 agent-minutes) could not land because `main` moved under them: the
  factory and I both changed the same files. Failure: nothing coordinates a person's hand merge with running tasks.
- **Agent time lost to its environment** (`.135`): `just test` cannot pass in the sandbox (dashboard sockets), `bd` is absent, tools are
  offline, a path under `.agents/` cannot be written. Agents explore, fail and retry.
- **Plans demanding what the sandbox forbids**: `.112` planned on adding pydantic (offline), then on filing tracker follow-ups
  (`bd`); `.135` planned an edit of `.agents/skills/beads/SKILL.md` (blocked). Each cost a 20-minute attempt and a hold.
- **Failed check output is not fed back**: `.132` repeated the same failing test (the factory feeds back only unsafe, uncommitted
  and ignored paths).
- **A cross-field answer rule is reported as `schema_invalid`**: `.112` answered `incomplete` with 96 paths (rule: only `implemented`
  lists paths); the JSON schema was valid. 20 minutes of work were thrown away with no chance to correct the answer.
- **A held task with a dirty slot blocks the slot** (`held:slot_dirty`): capacity fell from 4 to 2 while two tasks waited.
- **My own mistakes**: merged a gitlink (#762, fixed #763); merged a dependency (#765) after `just check` only, which left `main` red
  (fixed #766); merged a schema bump (#767) while tasks ran, which forces a discard on restart; asked the owner the same question
  several times instead of acting on the recommendation.

## Waiting on the owner

Passed and waiting for `tl step land`: `.113` 15:42 to 16:10 (28 min, spent on my fix of `main`); `.111` 16:00 to 16:47 (47 min, then a
conflict); `.112` 16:37 to 16:47 (10 min, then a conflict); `.132` 17:01 to now. Held and waiting for a re-label or an edit:
`.112` 9, 9 and 5 minutes; `.132` 6 and about 35 minutes; `.135` since 17:07; `.112` since 17:16. The longest waits are not
decisions but **chains of questions**: land waits for a yes, and a yes can turn into a conflict. The factory never lands on
its own, so every green task idles at least as long as the owner takes to answer.

## Failure scenarios seen (catalogue)

| # | scenario | seen on | today's handling | cost |
|---|---|---|---|---|
| 1 | `main` moves after the checks passed (conflict at land) | `.111`, `.112` | refuse; abandon, restart at plan | whole task redone |
| 2 | the plan needs a resource the sandbox lacks (dependency, `bd`, a protected path) | `.112`, `.135` | `needs_owner` hold | one attempt, then a person |
| 3 | the agent's answer breaks a cross-field rule | `.112` | hold `answer:schema_invalid`, no retry | one attempt |
| 4 | a check fails and the repeat does not know why | `.132` | hold after the repeat | one attempt, same failure |
| 5 | an unsafe path | `.111` | repeat with feedback text | one repeat; the path is not named to the agent |
| 6 | a held attempt leaves the slot dirty | `.112`, `.135` | the hold stays pending; slot blocked | capacity |
| 7 | a schema change on a running factory | restart | discard `factory.db` | history |
| 8 | the base moved under a waiting task (old task branch) | `.112` | restart on the old branch fails again | one attempt |

## The owner's observations, answered

| observation | answer from the code and data | action |
|---|---|---|
| Checks seem to run in no slot | They run in a slot (`step list` shows `check ... s3`). The dashboard card shows a slot only while the task is held, so a passed or checking card shows none. | Show the slot on checking and landing cards. |
| "Quiet for 21 minutes" while waiting for the owner | The quiet banner counts time since the agent's last command, also while the task waits for a person. Same fact as `.14.70`. | Waiting states say what they wait for and since when; "quiet" only for running agents. |
| `needs_owner` with an underscore, `held` still shown | Raw typed words are printed. `held` is renamed by `.121`, not built yet. | Humanize outcome labels in the page; build `.121`. |
| "Paused 6 seconds" and "3 ms" | The verification row has no start and end of its own (`started_at: null`); the gap shown is the factory's own work between the agent ending and the next step starting (reads, commit, push); it is not the agent and not a person. | Give the factory's work its own timed rows. |
| Slots live in the trial's own slots folder, `<hash>/s1` | `slots_root` is a machine-config value I set for the trial; the hash is the repo id; slot names are incremental (`s1`..`s4`). No decision to move them was recorded. | Decide the default root and a readable repo folder name. |
| What is "verification"? Why try 2 after implement? | It is the factory checking the agent's committing answer (branch, paths, ignored, uncommitted, step rules). Its numbering is the task-wide order, not per step: the second verification is "try 2" because the first followed plan. Wording clashes with `check`. | Number per step after which it ran; glossary term (`.78`). |
| Lines tab cannot open check output | Right: the check rows are clickable only in the Result tab. | Open the same output from the line. |
| Do we need `paths` in the answer? | The factory commits exactly the listed paths so the agent never writes Git and unsafe or ignored paths can be refused; but the list is long, error-prone (96 paths) and the source of case 3. It could be derived from the slot's status and checked by the same rules. | Design question, filed. |
| What is `schema_invalid`? Tell the agent and ask again | It is a cross-field rule, not the JSON schema (see above). Re-asking in the same session fits the owner's idea and `.128`. | Answer repair turn, filed. |
| Why does it wait for me to land? | By design rounds never land (the owner's earlier rule); the Land row has no explanation or link. | Auto-land policy (profile `land` mode), clickable Land row that says what it waits for. |

## What to improve first (proposed order)

1. Stop the loss to conflicts: land automatically when the checks pass and `main` has not moved, and re-run the checks when it did.
2. Remove environment friction (`.135`): prompt text, skipped socket tests, no `bd` in the step.
3. Give the agent the failure it must fix: failed check output and answer-rule errors fed back in the same session.
4. Dashboard honesty: waiting is not quiet, the factory's own work has rows, the Land row explains itself.
5. Keep the slot from blocking: a hold with a dirty slot should save the work (a rescue commit on a side branch) and free the slot.
