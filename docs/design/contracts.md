# Stage data contracts (2026-10-24, tl-bxk.13.16)

Source: the review of 28 open lifesim asks (21 engine bugs, 3 bad tickets, 4 real; shared notes `asks-review.md`). Idea: each
stage ends with a data contract the engine validates before moving on, with a send-back on the same thread (not a counted
re-plan). Status: built on branch claude/contracts, after the visual work (docs/design/visual-work.md).

| bead | contract | what validates it | asks it would have prevented |
|---|---|---|---|
| 13.16.1 ledger | every plan case says `proved_by` (check, stage, leftover, engine_step) and `via` | `Engine.ledger`/`ledger_match`: a review `unmet`, a verify item or a fix-round item that is about a ledger entry (3+ words, 60% of the entry's) is settled (engine_step), lands for the owner (leftover) or is dropped; `ledger_fill` lists a deferred case the plan forgot in leftovers; `ledger_problems` sends back a test case with no check and no other proof. Replaces the wording regexes as the first rule | 22b3, d5f.34, fld.25.19, h1fw, iqad, gfr.38, d5f.61, fdyo |
| 13.16.2 executable | plan checks | `command_problems`: a check is an argv list; its program resolves (`shutil.which`, or a file of the tree), with no operator word or shell run as a literal argument; `just <recipe>` exists in `just --summary`; `promised_missing` on resume: an accepted stage whose evidence file is gone runs again | fld.10, ov3w, d5f.40 |
| 13.16.3 inputs | plan `unresolved` (what, kind, path) | `check_unresolved`: a file that exists drops out, an input a case defers is a leftover, any other is a decision ask (defer / provide / drop) before any work; `engine.planner_notes` carries what the factory lacks | gfr.38, d5f.61, fdyo, v5z |
| 13.16.4 infrastructure | land result, lane answer | `TRANSIENT_PUSH`: network failure on the push, 3 rests (30/120/300 s) then `paused:`; a delegate `crash` or no answer (not a timeout): 2 rests (30/120 s) then `paused:`; neither asks | l4ow, rl4s |
| 13.16.5 asks | ask records | `tl.close_stale_asks` (loop pass, `tl ask list`): an ask of a closed or missing bead is closed; an owner answer that is only "run again" is no amend | u3bx, demo, fld.10 |
| 13.16.6 version | engine log and trace | `plugin_version()` in a `note` record and in `traces.jsonl` | the review had to infer it |

Config: `planner_notes` (text, or `@repo/file`, 2000 characters). Not built: a check that a cited bead really holds a quoted
text (y7ll), post-land facts as a verify Right/Wrong (o67g): both stay owner-look items.
