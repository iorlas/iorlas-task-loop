# Visual work in task-loop: design (2026-10-23)

## Facts
- Writers cannot render Unity on any account. The account sandbox blocks Unity (listen EPERM, licensing IPC) and is offline
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
   - `show`: the task demands an artifact (a picture, video, PDF or audio file). The case lists `shows: [{name, role}]`; the engine
     checks mechanically, by role and name, that each is registered for the last stage's write (tl-jvpm.25). A miss is one retry
     round for the writer, never a park. Whether it is good is the owner's.
   A bead is visual iff some case is `look-objective`, `taste` or `show`; `visual_paths` only checks that (a visual path touched with
   no such case sends the plan back once). The plan stage runs on any host; the write and look stages need the host that has the
   picture resource (`needs:<resource>`, host.json).
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
| 4 taste | cases of class taste file into the owner-look bead; its kv row `look:<bead>` (compare-and-set; no bead metadata) carries `[{id, bead, title, note, shots[{path, role before/after, label}], status}]` (`write_looks`); the gallery UI is dash-chain's |
| 5 references | (tl-jvpm.26: the guessing is deleted) the planner is told to assume the look when the task does not say; the worker registers its own before picture with role `before`; pictures are never committed to the repo |
| 6 fail fast | (tl-jvpm.26: `same_defect` is deleted) every defect left after the last round is filed as a leftover `Look: ...` with the pictures; no third write |

### The shot table (`engine.shot_table`, a repo path read from the base branch)

```
{"v": 1, "methods": [
  {"method": "CreatorShots", "summary": "named creator categories",
   "argv": ["Unity", "-batchmode", "-executeMethod", "Lifesim.Editor.CreatorShots.Run", "{args}", "-logFile", "client/Logs/creator-shots.log"],
   "args": [{"name": "shots", "flag": "-shots", "pattern": "[\\w=,:-]+", "required": false, "about": "body=body,face=face"}],
   "out": "client/Logs/shots", "files": "*.png", "timeout_min": 15}]}
```
The `{args}` word becomes `<flag>`, `<value>` per declared argument (flag `""` = positional: the value alone); `{out}` inside a word
is the folder the engine creates. A method with neither writes to `out` and the engine copies what is new there. The table's
`argv` is exec'd as given, no shell: nothing a writer says reaches a program except values matching an argument's pattern. Config: `shot_table`, `look_rounds` (2), `look_max_px` (1280).
Without `shot_table` a visual stage works the old way.

## Decisions recorded (Denis, 2026-11-05, VISUALS epic tl-jvpm)

Factory-wide artifact pipeline: a picture, PDF, video or audio made by the work is registered, stored globally and shown on the dashboard. These rows supersede the older design above where they differ (.14 and the baseline part of .18 are superseded by .21).

| id | decision | date |
|---|---|---|
| tl-jvpm.1 | An artifact is a picture, PDF, video or audio (any other file only as a download) that the AI or engine made as an intermediate or final result and registered through the factory tool. A file nobody registered is not shown. The step-end sweep that copies every file is removed. | 2026-11-05 |
| tl-jvpm.2 | No regular expressions or text guessing in the visuals path. Pairing before/after, deciding which beads are visual, finding image names in prose, settling a look item by file-name substring and the word-overlap same-defect test are replaced by declared, structured fields (adapters/looks.py same_defect, domain/look/matchers.py, domain/review/matchers.py and visual.py, app/look/shots.py before_shot, app/write/newfiles.py). | 2026-11-05 |
| tl-jvpm.3 | AI registers an artifact through a factory tool, never the CLI. The worker writes the file where it can, calls the injected tool with the path; the tool copies it into the store (original stays, scratch, never committed) and returns an artifact id. Tools are injected by the factory; task-loop does not name the harness. | 2026-11-05 |
| tl-jvpm.4 | Artifacts live in one global store keyed by bead, never in a slot or worktree: `<config>/artifacts/<repo>/<bead>/<run>/<stage>-<attempt>/`. The dashboard finds pictures by bead id. No LFS. Retention by age is a later change. | 2026-11-05 |
| tl-jvpm.5 | The directory is the index; no artifact table in factory.db. Attribution to run, stage and attempt is the path; caption and role sit in a sidecar next to the file. | 2026-11-05 |
| tl-jvpm.6 | The bead page shows a scroller of all the bead's artifacts on top; on the timeline each stage attempt shows its own artifacts (zero included). Nice to have: on the Slots timeline a new picture pops up as an image and opens on click. | 2026-11-05 |
| tl-jvpm.7 | Asks carry visuals when a decision needs them: an ask references artifacts and the ask card shows them. The card field `shots` is renamed `artifacts`. | 2026-11-05 |
| tl-jvpm.8 | A ticket may demand visuals in its acceptance criteria. Items of a show class are checked mechanically (the named artifacts exist); taste stays with the owner. The class lives in the shared task schema and template. The capability belongs to the factory, not to lifesim. | 2026-11-05 |
| tl-jvpm.9 | Anyone may take pictures. Capture is a capability every worker environment must provide (Unity shot methods via the whitelisted table, a browser for web, or self-made files registered through the tool). A host or account without it is not given such a ticket. | 2026-11-05 |
| tl-jvpm.10 | Artifacts are registered by the injected tool `artifact_add(path, caption, role, name)`, served by a per-call tool server bound to bead/run/stage/attempt. delegate.api's request gets a typed optional `tools` field. A spike proves it on claude, codex and opencode first. No capture tool: shots stay request-in-answer plus engine render. | 2026-11-05 |
| tl-jvpm.11 | Gallery and timeline list known directories (run, stage-attempt levels), never a tree-wide wildcard. The Slots timeline lists only the folder of each visible stage pass. Sort by sidecar time. | 2026-11-05 |
| tl-jvpm.12 | `<config>/runs` keeps its layout; the artifact path carries the same run id (no merge now). The ask-card field `shots` is renamed `artifacts`; "artifact" means any registered file; "shot" survives only as lifesim's own shot method. Old flat `<config>/artifacts/<bead>/` folders are not migrated (hard cut). | 2026-11-05 |
| tl-jvpm.13 | Each artifact has a JSON sidecar holding caption, role, logical name and timestamp, read by a typed record, never by a pattern. Kind comes from a fixed suffix table. | 2026-11-05 |
| tl-jvpm.14 | (Superseded by tl-jvpm.21 for baselines.) Kept: the word-overlap same-defect test is deleted (adapters/looks.py same_defect and words removed); the look loop stays capped at 2 rounds and defects left after round 2 become leftovers. | 2026-11-05 |
| tl-jvpm.15 | A bead is visual if and only if some plan case has class look-objective, taste or show. `visual_paths` and VisualWords stop deciding; a touched visual path with no such item sends the plan back to the planner once. The plan stage runs on any host; only write and look stages need the picture-capable host (`needs:<resource>`). | 2026-11-05 |
| tl-jvpm.16 | `artifact_add` is injected for every worker call, visual or not. Its description says pictures, video, PDF or audio of progress are welcome even when no acceptance item demands them. Only show items are mechanically required. | 2026-11-05 |
| tl-jvpm.17 | The dashboard keeps a per-bead gallery cache keyed by directory mtime. No `index.jsonl`. Bead card lists never touch artifacts; counts come from state or run records. | 2026-11-05 |
| tl-jvpm.18 | One store writer for engine renders and `artifact_add` (file first, sidecar last, atomic rename; sidecar records size and sha256; keep.py folded in). The sidecar is the only record; the log gets one debug line, never read by views. The baseline-folder part is superseded by tl-jvpm.21. | 2026-11-05 |
| tl-jvpm.19 | Spike `artifact_add` before building: a stdio MCP child per call, binding in argv/env, on claude, codex and opencode. Pass matrix: tool listed, tool called, file arrives, ids not model-passable, `../` or absolute name rejected, errors returned to the model. Store, dashboard and ask work wait for it. | 2026-11-05 |
| tl-jvpm.21 | `artifact_add` takes role before\|after\|progress\|result. The worker takes its own before picture and registers it with role=before, the after picture with role=after; the gallery pairs by role within one bead. No per-repo baseline folder, no replace-at-land, no name matching. A before picture is encouraged, never required. | 2026-11-05 |

tl-jvpm.20 is the spike for tl-jvpm.19 (its result: docs/design/spike/artifact-add.md), not a decision.
