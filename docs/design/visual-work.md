# Visual work in task-loop: design (2026-10-23)

## Facts
- Writers cannot render Unity on any lane. The lane sandbox blocks Unity (listen EPERM, licensing IPC) and is offline
  (lifesim `docs/agents/codex.md`). Grok's sandbox has no network or localhost sockets either. The engine runs Unity
  outside the sandbox after each write: tests, play tests, the screenshot methods (`docs/agents/task-loop.md`).
- Despite that, `look_write` (engine.py ~3330) tells the writer to "save a screenshot of every changed screen" in the
  evidence dir. The writer is asked for something it cannot do.
- `look_verdict` settles a look item only when the evidence names a screenshot file; otherwise the item goes back to the
  writer once. Without shots, that round is wasted by construction.
- The reviewer and verifier open the screenshots in their own long context (1-2 MB images inline in fdyo).
- Visual feedback costs one full check round: about 11 min of Unity tests before the shot check (8 rounds in fdyo).
- The planner turned "owner approves" into a number (light-heavy contrast >= 2). The writer tuned blind against it:
  one turn, 5.98M tokens.
- Already built on `claude/stage-design-7716bd` (not released): no invented thresholds for owner-judged items; a check
  red 2 rounds in a row goes to `bad_checks`; fresh codex writer above 100k; the plan's check commands checked before
  the first write; acceptance checks before the slow tests after an acceptance-only failure.

## The rule
Rendering is the engine's job. Judging taste is the owner's job. The writer writes code and says what to render.

## Design
1. **Plan-time classes.** The planner gives every acceptance item one class:
   - `test`: a command proves it.
   - `look-objective`: a render can prove it. It shows, is not clipped or overlapped, has no error or magenta textures,
     and the state is visible.
   - `taste`: someone has to like it. "Owner approves", "reads well", "feels like the Sims".
   A number for a look item comes only from the bead, the owner, or a project standard file (for example design
   tokens or a contrast rule in `config/`). The planner may propose one, but a proposal is a plan-time question to the
   owner (revives 13.10), never a check.
2. **The writer asks for shots, never makes them.** Every write on a visual stage returns `shots`: shot method, args and
   names, picked from the project's shot table (lifesim `docs/agents/unity.md`, "Shot methods"). `look_write` stops
   asking for screenshots.
3. **A short render loop inside the stage.** After the write:
   - The engine runs the cheap checks.
   - It then runs only the requested shot methods (minutes, not the full Unity test round) into the evidence dir.
   - A **look judge** judges the shots. It is a fresh call with no repo context, from another family than the writer.
     It gets the shots (downscaled), each look item, and the reference images. It returns text findings per item:
     pass, or the defect and where.
   - The writer resumes with the findings as text and the shot paths. It opens an image only if it chooses to.
   - Up to 2 render rounds per stage for objective defects, then the item becomes a leftover.
   - The full Unity test round runs once, at the end of the stage.
4. **Taste never blocks.** When test and look-objective items pass, the bead lands. Taste items go to the owner-look
   bead (0.23.3) with before/after shots. The dashboard shows them as a gallery with two buttons: "good", or "redo"
   with a note. Redo files a follow-up bead carrying the note and the shots.
5. **Reference images.** A visual bead with no reference (mockup, target or previous shot) gets one plan-time question,
   "what should it look like?", and does not start on a guess. Previous shots of the same screen are attached
   automatically as "before".
6. **Fail fast.** When the same look check is red twice with the same defect, it is not a writer problem. It goes to the
   leftovers with the shots, and the bead does not spend a third write on it.

## Expected effect
- fdyo: the 5.98M blind-tuning turn and 3 red verdict rounds disappear. The stage costs about 1 write + 1 render round
  + 1 judge + 1 full test round. That is about 2M tokens and roughly 25 min less.
- Fewer parks on "verify could not prove an item" (5 of 34 in night 1), because look items are judged from real shots
  every time.

## Decisions for the owner
- A. Engine render loop on the writer's request (✅), or keep visual tuning out of the loop entirely (❌: then every
  visual bead parks).
- B. Taste lands and batches into an owner gallery (✅), or the bead waits for the owner (❌: blocks the loop overnight).
- C. Look thresholds only from the owner or a project standard; planner proposals become plan-time questions (✅).
- D. A separate look judge with fresh context (✅), or the reviewer keeps opening images in its long context (❌: 1-2 MB
  images re-read every turn).

## Owners if approved
- stage-design session: 1, 2, 3, 5, 6 (engine.py, planner and writer prompts, output contracts).
- dash-chain session: the gallery in 4.
- lifesim (sims qs): a machine-readable shot table next to `docs/agents/unity.md`, with method, args and names.

## Built (tl-bxk.13.15)

| design item | where |
|---|---|
| 1 plan classes | `SCHEMAS["plan"].cases[].class` (test / look-objective / taste); `VISUAL_PLAN` is added to the planner's rules on a repo with `visual_paths`; `plan_checks`/`case_checks` skip a case that is not `test` |
| 2 writer asks for shots | `SCHEMAS["write"].shots` `[{method, args[{name,value}], names}]`; `LOOK_WRITE_TABLE` replaces the old "save a screenshot" text when `engine.shot_table` is set |
| 3 render loop | `Engine.look_step` after a visual write: static checks, `render_shots` (the table's commands only, `looks.build`), `judge_shots` (node `look`, role reviewer, other family, cwd = `<run>/looks/rN/` with shrunk copies, references, before pictures), at most `engine.look_rounds` (2) per stage, then the full checks once |
| 4 taste | cases of class taste file into the owner-look bead; its metadata `looks` carries `[{id, bead, title, note, shots[{path, role before/after, label}], status}]` (`write_looks`); the gallery UI is dash-chain's |
| 5 references | `references_text`: image paths in the task and last landed shots go to the planner, or the planner is told to ask "what should it look like?"; `before_shot`: the newest landed picture of the same name under `engine.evidence_dir` |
| 6 fail fast | a defect of round 2 that says the same as round 1's (`looks.same_defect`), and every defect left after the last round, is filed as a leftover `Look: ...` with the pictures; no third write |

### The shot table (`engine.shot_table`, a repo path read from the base branch)

```
{"v": 1, "methods": [
  {"method": "CreatorShots", "summary": "named creator categories",
   "cmd": "Unity -batchmode ... -executeMethod Lifesim.Editor.CreatorShots.Run{args} -logFile client/Logs/creator-shots.log",
   "args": [{"name": "shots", "flag": "-shots", "pattern": "[\\w=,:-]+", "required": false, "about": "body=body,face=face"}],
   "out": "client/Logs/shots", "files": "*.png", "timeout_min": 15}]}
```
`{args}` becomes ` <flag> <quoted value>` per declared argument (flag `""` = positional); `{out}` a quoted folder the engine
creates. A method with neither writes to `out` and the engine copies what is new there. Nothing a writer says reaches a
shell except values matching an argument's pattern. Config: `shot_table`, `look_rounds` (2), `look_max_px` (1280).
Without `shot_table` a visual stage works the old way.
