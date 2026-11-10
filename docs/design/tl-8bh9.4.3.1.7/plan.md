# The agent chooses what to commit; the factory commits it and checks the tree is clean

Task: tl-8bh9.4.3.1.7 (proposed id; after [.4.3.1.5](../tl-8bh9.4.3.1.5/plan.md) and [.4.3.1.6](../tl-8bh9.4.3.1.6/plan.md)).
Design proposal, 2026-11-10, revision 4: revision 3 (independent review and the owner's answers applied) as implemented,
plus the repair round after the implementation review (section 16). No live agent has run it. It closes .4.3.1.5 section 9 and changes steps 4-5 of the [one-shot plan](../tl-8bh9.3.2.1/plan.md). Read:
CLAUDE.md, AGENTS.md, glossary, those plans, [.4.3.1](../tl-8bh9.4.3.1/plan.md), [.4.3.1.1](../tl-8bh9.4.3.1.1/plan.md),
[.4.3.1.4](../tl-8bh9.4.3.1.4/plan.md) and its [live smoke](../tl-8bh9.4.3.1.4/live-smoke.md), `src/taskloop/plan*.py`,
`composition.py`, `cli_plan.py`, `tests/plan`, git_porcelain 0.13.0 source, any_agent `protocol.py`, `~/tl-smoke`.

## 1. Evidence and the principle

Smoke 3 (`artifacts/attempts/*/stdout.txt`, events 9 to 12): the agent's `git commit` failed in the sandbox (`Unable to
create .../repo/.git/worktrees/s1/index.lock: Read-only file system`), then the same command succeeded. Under
`approval_policy=on-request` + `approvals_reviewer=auto_review` that is an approved command run outside the sandbox
(no approval event appears in stdout.txt; inferred). The sandbox did not bound the commit.

**Owner's principle:** the agent decides what its stage produces and what must be committed, not a fixed file list.
After the stage, `git status` must be empty; anything left over means the stage is not done, and it is **repeated** with
that status as feedback ("commit it or remove it"). The same mechanism is meant for implementation and review later.

**Decided (owner, C1): the agent selects, the factory commits mechanically.** Git is not the agent's concern; reading
Git inside the sandbox is fine, writing is not. A linked worktree's index, objects and refs live in the common `.git`
outside the slot, and adding them to `writable_roots` would let the agent rewrite shared config, hooks and every branch.
A blanket "commit everything" would be a mistake, so the answer lists the paths to commit and a commit message; the
factory stages exactly those paths and commits them outside the sandbox; the clean-tree check then decides whether the
stage is done. The same stage mechanism will serve the implementation and review stages (section 14).

## 2. The answer contract (no compat)

Schema (strict mode, as today: a plain root object, every property required, nullable by type list, no
`allOf`/`anyOf`/`oneOf` anywhere): `disposition` (enum), `plan_path` (string|null), `paths` (array of string),
`message` (string|null), `explanation` (string). `commit` is gone everywhere (`ANSWER_SCHEMA`, `PlanAnswer`,
`AnswerState`, `plan_execution.reported_commit`); an answer that still has it is `schema_invalid`.

`decode_plan_answer(value, rules)` stays the only owner of the cross-field rules and bounds. `rules` is a per-stage
`StageRules(root, max_paths=32, file_cap=1 MiB, deletions=False)`; the plan stage passes `root = "docs/design/<task-id>/"`,
so implementation and review can reuse the decoder with another root later.
The `disposition` enum is `planned`, `unchanged`, `incomplete`, `needs_owner`. The choice between a new plan and an
existing one is **stated by the agent**, never inferred from "nothing changed" (F4, section 8):
- `planned` (the agent wrote or changed the plan; a replan edits it in place, the old version stays in Git history):
  `plan_path` is the expected path; `paths` is non-empty, unique, includes `plan_path`, at most 32; `message` is 1 to
  500 chars with no NUL and no `Task-Loop-Attempt:` (the factory's trailer cannot be forged).
- `unchanged` (the plan already at the slot's start is still valid; the agent changed no file): `plan_path` is the
  expected path, `paths == []`, `message` null.
- `incomplete`/`needs_owner`: `paths == []`, `message` null, `plan_path` null or expected.
- Each path: at most 255 bytes, relative, no NUL, newline or backslash, no empty, `.` or `..` component, no component
  that starts with `.git` in any case, and under `rules.root`. The `.git*` rule also refuses `.github/`, `.gitkeep`,
  `.gitignore` and `.gitattributes`: harmless for a plan; the implementation stage will need its own decision there.
A path that breaks these makes the whole answer `schema_invalid` (stored, terminal as today; section 7 on repeats).

**What the agent is told.** `plan_admit.task_text` today is the task prose alone ("no prompt template"). The admitted
input gains fixed closing words (stored in `input.txt` under its digest): *"First read
`docs/design/<task-id>/plan.md` if it exists. If it is still valid for the task and the code as they are now, change
nothing and answer `unchanged`. Otherwise write the plan there (rewrite it in place if it exists) and answer `planned`;
other files only under `docs/design/<task-id>/`. You may read Git; do not run `git add`, `git commit`, `git push` or any
other Git write; they will fail. With `planned`, list in `paths` every file you want committed and give a one-line
commit `message`; the factory commits exactly those paths. Remove any other file you created. Anything left uncommitted
is reported back to you as a failed stage."*

## 3. Sandbox flags (decided)

`CODEX_ACCESS`: `approval_policy=never`; `approvals_reviewer=auto_review` removed (it only reviews escalations, which
`never` never makes). `writable_roots=[]`, `network_access=false` and the push bar stay. A blocked command fails back to
the model; nothing runs outside the sandbox. Checked by strings only (codex 0.167.0, never run): `approval_policy`
takes `untrusted`, `on-request`, `never` or granular; the binary also says `never` falls back to read-only when
requirements forbid `danger-full-access`, which would stop the plan write: the smoke checks it. Smoke 3 ran on Linux
(OrbStack, aarch64-musl 0.167.0); `plan.py` names 0.162.1; macOS Seatbelt is unobserved.

## 4. The slot pointer check (before any Git call on the slot)

A rewritten `<slot>/.git` would aim every factory Git call (git_porcelain pins `GIT_DIR` from that file on **every** call,
`real_env.pinned`, as `(slot / text).resolve()`) at another Git directory: the person's own `.git` (a commit lands on
their branch) or a fake Git directory the agent made, whose `config` and `info/attributes` define a `filter.<x>.clean`
command that `git add` runs outside the sandbox. The check therefore judges the pointer with **the same resolution Git
and the pin use**, never a lexical one (revision 3's `normpath` let `gitdir: L/../../../repo/.git/worktrees/s1` with `L`
a symlink inside the slot pass while Git resolved it into the slot; reproduced with real Git in review). Through a
narrow file port (plain reads plus `resolve`, in composition; the domain gets bytes, entries or resolved paths):
1. The slot path has no symlink: `resolve(<slot>) == <slot>` (decided: a symlinked slot path is refused rather than
   compared through the listing; `tl slot adopt` stores resolved paths).
2. `lstat(<slot>/.git)` is a **regular file** (a directory, symlink or FIFO is refused before any open), at most 4 KiB;
   it parses as `gitdir: T`.
3. `G = resolve(<slot> / T)` (a relative T, as `git worktree add --relative-paths` writes it, resolves against the slot,
   exactly as the pin does) exists, is a directory, and is **not inside the slot**.
4. `C = resolve(G / <G/commondir>)` (git_porcelain's `common_of` rule) is not inside the slot, and G's parent is
   exactly `C/worktrees`.
5. `resolve(G / <G/gitdir>)` (Git's back-pointer, absolute or relative to G, outside the slot) is exactly `<slot>/.git`.
6. Then Git, from the root (C's parent when C is `.git`, else C), never from the slot: `identity().key == repo_id`,
   `identity().common_dir == C`, and `worktrees()` lists the slot path with HEAD and branch.
Failure: `unsettled:redirected` (before dispatch `refused:slot_redirected`), nothing staged. The check runs in
`observe_slot` (dispatch, verify, commit and `plan show` all get it) and **again right before `stage` and before
`record`**.

**Residuals.** (a) A swap between a check and the Git call: the library re-reads `.git` on each call, so the agent can
still race it; only an explicit pinned Git directory in git_porcelain (`RealRepo(..., git_dir=G)` that never re-reads
the pointer) closes it. That is a shelf change, **not made here: follow-up** for git_porcelain. (b) A FIFO (or a slow
file system) put at `.git`, `G/commondir` or `G/gitdir` between the `lstat` and Git's own read makes the Git call hang:
local Git reads have no timeout. Accepted for v1; the bound belongs in git_porcelain (a per-call timeout), with (a).
(c) Whether codex protects a `.git` file inside the writable root was not observed (the binary has gitdir-pointer code).

## 5. The factory commit and the clean-tree check

**Where and when.** The first part of `PlanVerifier.verify(key)` ("commit, check clean, then judge"), so the entry
(once, after `execute`/`publish`) and `tl plan verify` run one operation, and re-running it finishes any crash. Facts in
order: `captured` -> answer `valid` `planned` or `unchanged`, run clean (`rc=0`, not timed out) -> publication
`complete` -> `plan_attempt.plan_commit` = X -> clean tree at X -> verdict. The Git write lives in a new `plan_commit.py`
(Git and the file port only, no factory.db), the only factory module that calls `stage`/`record`.

**Steps** (`settle_commit`; outside any transaction; every `GitUnavailable` is unknown and stores nothing):
1. A stored `plan_commit`: skip to step 6.
2. Section 4. Let `H` be the slot HEAD from the root's listing. HEAD unborn or attached: `unsettled:branch`.
   **`unchanged`:** H must be B (else `unsettled:head_moved`); no stage, no commit; X = B; go to step 6, where `plan_commit`
   = B is stored only after the tree is clean (a file the agent left contradicts its "changed nothing").
3. **`planned`, H != B**: adopt H only if `history([H], not_on=[B])` (H passed as a sha, read from the root; `history` runs at
   `repo.path`, `real_read.py:105`) is exactly one entry H whose body has the line `Task-Loop-Attempt: <attempt_id>`:
   this factory's commit from a crash before recording. Else `unsettled:head_moved`.
4. **`planned`, H == B. Pre-stage file check**, each listed path through the file port: no component is a symlink (`lstat` per
   component), the path is a regular file, no exec bit, size at most `file_cap`. Then one
   `dirty(B, ignored_under=(".gitattributes", "docs/.gitattributes", "docs/design/.gitattributes", root))`:
   - any tracked or untracked changed path with a component that starts with `.git` (any case: `.gitattributes`,
     `.gitignore`, `.gitmodules`, `.github/`) in a folder on the way to a listed path or under the stage root is
     `unsettled:unsafe <path>`: it would change how Git stages the listed paths, and the agent may not commit it;
   - an ignored file there (an attributes file status does not show, or a listed path itself ignored by `.gitignore`,
     `info/exclude` or the global excludes, on which `git add` would fail forever) is `unsettled:ignored`.
   Failure of the file check: `unsettled:unsafe <path>`.
   This replaces revision 1's snapshot/index pre-check, which is **dropped**: the verdict already rejects bad paths and
   modes from the commit itself; the only point of a pre-check is to refuse a symlink or oversize file before it is
   staged, and plain `lstat` does that without hashing the whole tree.
5. Section 4 again, `stage(paths, literal=True)`, section 4 again, `record(message + "\n\nTask-Loop-Attempt: <id>",
   paths="staged", hooks=False)`. `Recorded.sha` is X. `NothingToRecord` is `rejected:nothing_written` (stored with
   `plan_commit` NULL, so a failed write never reads as success) **only after HEAD is read again and is still B**: a
   verifier racing this one may have committed the same index first, so a moved HEAD goes back to step 3 (adopt this
   attempt's trailer commit, else `head_moved`). This is the one verdict taken from the working tree rather than a commit; it is repeatable
   (staging the same tree again gives the same answer). `HookRejected` cannot occur with hooks off; it is unknown. Then
   `PlanStore.plan_commit(admission, X)` (section 6).
6. **Clean-tree check at X:** HEAD == X, detached, and `dirty()` (tracked and untracked; ignored files are not counted)
   is empty. Leftovers: `unsettled:uncommitted` carrying a bounded listing (at most 50 `XY path` lines, then `+N more`;
   control words fixed, the listing is data, never parsed). Nothing is stored. For `unchanged`, `plan_commit(admission,
   B)` is written here, after the clean check.
7. Clean: the verdict of section 8, stored once.

**Author and message.** The agent's message plus the trailer. Author and committer: the person's configured identity
(no `identity=` override; decided, F2); a missing identity is `unavailable:git:*`.

**Hardened Git environment (`composition.checkouts`, every factory Git call).** Entries appended after any ambient
`GIT_CONFIG_*` (the `push_bar` pattern, generalised; a malformed count refuses `git_config`), passed through
`RealRepo(..., env=...)`, a parameter the library has: `core.hooksPath=/dev/null`, `core.fsmonitor=false`,
`commit.gpgSign=false`, `maintenance.auto=false`. Why: `--no-verify` skips only `pre-commit` and `commit-msg`;
`prepare-commit-msg`, `post-commit`, `post-index-change` and `reference-transaction` still run, and a `core.hooksPath`
like `.husky` points into files the agent wrote. fsmonitor runs a program on every status read. Signing can prompt
(pinentry) in a detached process with no timeout. Auto-maintenance after a commit can start a long `gc`. **Scope:** the
same `checkouts` will serve the later publication push, so `pre-push` hooks will not run either; slice 3 must accept
that or build its own repo. **Signed-commit repositories are unsupported in v1:** X is stored once and is what gets
pushed, so re-signing would make a different commit.

**Residual (named, not closed).** A clean/textconv driver in the person's own Git config whose command is a script in
the repository would run the agent's edited copy during `status` or `add`; the verdict still judges the committed blobs.
Not adopted: `GIT_ATTR_SOURCE=<B>` (untested). Agent descendants have no stop proof (.4.4); late writes are leftovers.

## 6. Storage: schema v3 -> v4 (`current()` refuses v3; the smoke DB is discarded)

```sql
-- plan_attempt gains: plan_commit TEXT CHECK(plan_commit IS NULL OR length(plan_commit) IN (40,64)),
--                     CHECK(plan_commit IS NULL OR phase='captured')
-- plan_execution: reported_commit -> commit_paths TEXT (a JSON array, as validated), commit_message TEXT
-- ANSWER = "answer_kind,disposition,plan_path,commit_paths,commit_message,publication"
-- plan_verification: unchanged columns; RULES gains 'nothing_written' and 'file_size' and loses 'merge'
```

`plan_commit` means exactly: the commit the stage ends at. `planned`: the factory's commit X (X != B). `unchanged`: B
itself. NULL: not settled yet, or never (`rejected:nothing_written`, non-planned answers).
`PlanStore.plan_commit(admission, X) -> str`: one `begin_immediate`, fenced: `UPDATE plan_attempt SET plan_commit=?,
rev=rev+1 WHERE attempt_id=? AND plan_commit IS NULL AND phase='captured' AND EXISTS (valid, rc=0, timed_out=0,
publication='complete', and either disposition='planned' AND ?<>base_commit, or disposition='unchanged' AND
?=base_commit) AND NOT EXISTS (a plan_verification row)`, then a read-back; so a stored `nothing_written` (no commit)
is never contradicted by a later X, and a verdict is never stored against a different `plan_commit` (the verdict
insert binds to it). A different stored value is `unavailable:inconsistent`; a refused gate is
`StoreRefused`. `verdict()` binds to `p.plan_commit` instead of `e.reported_commit`, except `nothing_written`, which
requires `plan_commit IS NULL` and `disposition='planned'`; `reused=1` requires `disposition='unchanged'`. `AttemptRecord`
gains `plan_commit` (not `Admission`, so `_fence` is unchanged). DDL stays in `plan_schema.py`; `WRITERS` needs no new
row (`UPDATE plan_attempt`, `UPDATE plan_execution` are already `plan_store.py`). The `unsettled:uncommitted` listing is
**not stored** (section 7).

## 7. The repeat: this slice reports it, a named slice launches it

**What a repeat is.** A new attempt of the same task, launched with `LaunchInputs.resume = <native session>` (the field
exists in any_agent `protocol.py`) and a fixed feedback prompt: the listing of section 5 step 6 (or the `unsafe` /
`schema_invalid` reason) and "commit it (list it in `paths`) or remove it". .4.3.1 already says a correction
or resume launch is a new admitted attempt, never hidden inside the first one.

**Why not in this slice.** It needs UNIQUE(adapter, backlog, task_id) widened by a round and a `previous_attempt_id`,
admission that takes over the held reservation (`reservation.attempt_id` is UNIQUE) without releasing the slot, resume
intent in the admitted input, and the cap: a schema and admission change of its own.

**This slice:** the status operation (`plan_ops`, through the read-only `PlanVerifier.leftovers`; `plan.collect` stays
store-only) maps a captured `planned`/`unchanged` attempt whose verify would be `unsettled:uncommitted | unsafe` to
`pending("repeat")`; `tl plan show` prints `Next: repeat (deferred)` with the listing read fresh (every control
character, newline, escape or ANSI sequence printed as `?`, each line at most 300 characters; `tl plan list --stuck`
never reads it, since a repeat is never stuck), and the entry log
says `verify=unsettled:uncommitted`. The listing is not stored: the tree can change before a repeat, so the repeat
must read `status` again at its launch; a stored copy would have no reader until then. A person may still tidy the slot
and run `tl plan verify`. Storing the feedback was asked for and is not done, for that reason (C2).

**Cap (decided, F3):** at most 2 repeats (3 rounds); at the cap the task becomes `needs_owner`. Enforced by the repeat
slice; this slice only names it.

## 8. Verification changes

- X is `plan_attempt.plan_commit`. `_chain` shrinks to one step: X's first parent is B (`tree(f"{X}^").sha == B`) and
  `relate(B, X) == (ahead 0, behind 1)`; else `not_descendant` / `chain_length`. `CHAIN_CAP` and the `merge` rule go.
- One diff B..X: each change is A or M, passes the decoder's path rules, is in the answer's `paths`
  (else `paths`), has mode `100644` (else `mode`), and every committed blob is at most `file_cap` (new rule `file_size`,
  full reads, at most 32 MiB). Then the plan rules as today.
- **Reuse only on an explicit statement (F4, section 13).** `planned`: X != B, judged as above. `unchanged`: X = B,
  clean tree; `judge` skips the chain and applies the plan rules to the plan at B (path, mode `100644`, content floor,
  `file_cap`): `verified` with `reused=1` (`collected reused`), or `rejected:plan_missing`/`plan_empty`. This restores
  Q2 of .4.3.1.5, but only on the agent's statement, never inferred from "nothing changed".
- Agent commits: with `never` they cannot happen; one that does is `unsettled:head_moved` (slot state, never a verdict).
- Verdict rows stay insert-only; a stored verdict is returned with no Git read.

## 9. Slot preconditions

Before dispatch: as today (born, detached, clean) plus the pointer check in `observe_slot`. After the run, dirt is
expected until step 6. `slots._clean` and `_base` need no change: a captured attempt's slot stays held.

## 10. Failure and unknown table (every row keeps the reservation and the claim)

| Situation | Stored | Result | Next |
|---|---|---|---|
| Answer `incomplete`/`needs_owner`, invalid (incl. a bad path), or the run failed | nothing new | as today; nothing committed | cleanup / repeat slice |
| `planned`, but every listed path equals B (`NothingToRecord`) | `rejected`, no X | `collected rejected:nothing_written` | terminal (Q6) |
| Leftovers after the commit, or `unchanged` with files left (incl. late writes by live descendants) | X (`planned`) or nothing | `unsettled:uncommitted` + listing | repeat (after stop proof, .4.4) |
| `unchanged`, clean, plan at B passes | X = B, `verified` `reused` | `collected reused` | slice 3 publishes B |
| Agent rewrites `<slot>/.git` (file, dir, symlink, FIFO, other gitdir, a symlink inside the slot that resolves G or C into it, a symlinked slot path) | nothing | `unsettled:redirected` | owner inspects; never commit |
| A changed `.git*` file on the way to a listed path or under the stage root | nothing | `unsettled:unsafe <path>` | repeat / tidy |
| Listed path is a symlink, under one, not regular, exec, oversize | nothing | `unsettled:unsafe` | repeat / tidy |
| Ignored attributes file on the plan's path, or a listed path ignored | nothing | `unsettled:ignored` | tidy |
| HEAD moved, not this attempt's trailer commit | nothing | `unsettled:head_moved` | owner inspects |
| `index.lock`, identity unknown, Git missing or failing | nothing | `unavailable:git:<Type>` | re-run verify |
| Crash after `stage`, before `record` | nothing | next verify stages again, commits once | re-run |
| Crash, or store unavailable, after `record` and before `plan_commit` | nothing (HEAD = X) | next verify adopts X by its trailer | re-run |
| Commit made, then `plan_commit` refused (stale reservation, changed answer) | nothing | refused; X is held only by the slot HEAD | owner; no ref pins X |
| Two verifiers at once | at most one X | `index.lock` and the HEAD old-value check let one commit; the other fails unknown, or finds nothing to commit with HEAD moved, then adopts | re-run |
| Two different X for one attempt | the first | `unavailable:inconsistent` | defect; owner |
| Clean at X, every rule holds | X, `verified` | `collected verified` | slice 3 pushes X |
| A rule fails over X | X, `rejected` | `collected rejected:<rule>` | terminal (Q6) |

## 11. Tests (pytest functions; no subprocess in factory code; caps 400/80/800)

Contract, then consumer: `stage`, `record`, `dirty(ignored_under)`, `history` bodies belong to git_porcelain's contract
suite; the factory tests its consumer on `FakeRepo` plus a fake file port, and one real wiring test.
- `test_answer_contract.py`: the five-key schema keeps the strict rules and its enum has `unchanged`; a `commit` key is
  `schema_invalid`; table of bad paths (`..`, `.GIT`, `.github/x`, outside root, 33 paths, duplicate, missing plan,
  forged trailer in `message`); `unchanged` with paths or a message, or without the expected `plan_path`, is invalid.
- `test_verify.py` (rewritten table; the fake agent writes files and answers `paths`/`message`): plan only and plan
  plus a note -> `verified`, one commit with the trailer; an unlisted file -> `unsettled:uncommitted` with a listing;
  `planned` listing an unchanged plan -> `rejected:nothing_written`, no commit; `unchanged` with a valid plan at B ->
  `reused`, no commit, `plan_commit` = B; `unchanged` with no plan at B -> `rejected:plan_missing`; `unchanged` plus a
  stray file -> `unsettled:uncommitted`; empty plan -> `rejected:plan_empty`; a trailer commit made before verify
  -> adopted, still one commit; a foreign commit -> `head_moved`; pointer fakes (dir, symlink, FIFO, wrong back-pointer)
  -> `redirected` with no Git call (counted `checkouts`); `lock_index` -> `unavailable:git:*`; a second verify after
  `drop_checkout` returns the stored verdict. Chain rows (`chain_of_three`, `chain_of_eight`, `modified_away`) go;
  the `reused*` rows become `unchanged` rows. **Direct `judge()` rows** (the verify path cannot reach them): `not_descendant`, `chain_length` (two
  commits), `paths` (a change not listed), `file_size`.
- `tests/plan/real/test_commit_real.py`, real layer, 1 s: a real repo whose `core.hooksPath` holds `post-commit`,
  `prepare-commit-msg`, `post-index-change` and `reference-transaction` hooks that write marker files; a detached
  worktree slot; commit through `composition.checkouts` -> no marker, trailer present, slot clean; plus a row with a
  symlink under the allowed root -> `unsafe`, HEAD unchanged. Set-up through `git_porcelain.testing`'s runner. The
  successor has no `tests/plan/real/` and no layer guard yet (`tests/` holds `cli`, `plan`, `rules`): check before adding.
- Revision 4 adds (section 16): in `tests/plan/real/`, the two redirect attacks (the person's `.git`; a fake Git
  directory with a `clean` filter) refused with no marker and the person's branch unchanged, a `--relative-paths`
  worktree accepted, and trailer adoption through real `history` (one trailer commit adopted, two commits `head_moved`);
  in `test_verify.py`, pointer rows judged by resolution (symlinked slot, G or C resolving into the slot, unresolvable),
  the pointer rewritten during the pre-stage read (nothing staged) and during `stage` (no commit), the racing verifier
  adopting instead of `nothing_written`, the verdict fence on `plan_commit`, `.git*` rows, an ignored listed path,
  `unchanged` never adopting, and the safe listing; in `test_ops.py`, `list --stuck` reading no slot.
- `test_entry_store.py`/`test_attempt.py`: `plan_commit` written once, refused unless `captured` and clean, refused
  for `planned` with X = B and for `unchanged` with X != B; `report` maps `unchanged` to verification like `planned`;
  `CODEX_ACCESS` has `approval_policy=never` and no `approvals_reviewer`. `test_ops.py`: refused versions `[1, 2, 3, 5]`.
  `test_credentials.py`: the four entries appended after ambient `GIT_CONFIG_*`. `test_admit.py`: the closing words.
- `tests/rules`: no new `WRITERS` row; a new rule that only `plan_commit.py` calls `.stage(`/`.record(`.
- Left to the smoke: codex `never`, macOS, filters, a real rewritten pointer under the sandbox.

Size: `PlanVerifier`/`_applicable` move from `plan.py` (413 lines) to `plan_verifier.py` (~150); `plan_commit.py` ~160
(new); `plan_store.py` +25; `plan_types.py` +30; `composition.py` +30; `plan_admit.py` +12.

## 12. What else changes

- `.4.3.1.5/plan.md`: section 9 rows "Commit refused"/"approved escalation" -> resolved here; sections 3 (chain, cap 8,
  merge; Q2 reuse now only through `unchanged`), 5 (`reported_commit`, `RULES`), 8 ("the sandbox is not a boundary")
  -> sections 3-8 here. `DISPOSITIONS` in `plan_types.py` and `plan.report`/`outcome` gain `unchanged`.
- `.3.2.1/plan.md` steps 4-5 and the rows "Agent reports success without a committed plan" / "Commit exists but
  acknowledgment was lost": the agent selects, the factory commits the listed, checked paths; a leftover is a repeat.
  The ban on a blind factory stage-all stays true (also delivery-publication line 54).
- `.4.3.1.1/plan.md` lines 114 and 204-212 (answer fields); `.4.3.1.4/plan.md` lines 120-124 and 249 (`CODEX_ACCESS`).
- `.4.3.1.6/plan.md` line 194 and `cli_plan.py` line 33, the `unsettled` hint, -> "The slot has files the stage did not
  commit (listed), or the slot pointer or HEAD changed. Remove the listed files or wait for a repeat; for `redirected`
  or `head_moved` inspect first. Then `tl plan verify`." Line 99: "Commit the stage's listed files and verify them".
- `live-smoke.md`: section 2 bead -> "write the plan; try `git commit` and `git push` once each, report both errors;
  list the plan in `paths`", then a second bead with the plan already on the slot, expecting `collected reused`;
  section 5 selects `plan_commit,commit_paths`; section 6 "Commit in a linked worktree" passes when the agent's commit
  fails and the slot shows one trailer commit = `plan_commit`, clean; "Escalations approved" passes only with none; new
  rows "plan file written" (read-only fallback) and "no hook marker". Reset: delete the v3 `factory.db`.
- `plan_admit.task_text` docstring; `ANSWER_SCHEMA` and `PlanAnswer` comments.

## 13. Decisions and the one open confirmation

Decided by the owner: C1 (agent selects, factory commits), F2 (the person's Git identity plus the trailer), F3 (2
repeats, then `needs_owner`). Decided here: `never` without a reviewer; the hardened environment, including the future
push; the pointer check; per-stage `StageRules`; no snapshot pre-check; `CHAIN_CAP`/`merge` removed; C2 (the leftover
listing is read fresh, not stored).

- **F4, to confirm.** Plain words: the agent reads the old plan and says either "I rewrote it" (`planned`, must commit
  a change) or "it still holds" (`unchanged`, must change nothing); the factory checks whichever it said. A restart
  reuses a good plan, a drastic change gets a replan, and neither a failed write nor a stray file passes as success.
  Recommend: confirm.

## 14. Idea, not built: richer Git needs later

- **The same stage mechanism for implementation and review.** Each stage gets its own `StageRules` (allowed root,
  deletions, caps). The agent lists what to commit; the factory commits and checks the tree is clean; leftovers repeat
  the stage. Review may write reports or larger outputs: whatever it writes must be committed or removed, so review is
  not made read-only.
- **History analysis and reverts.** The agent may already read Git. A revert or undo could become a typed factory
  operation the answer requests (for example `revert: <sha>`), done by the factory like the commit, never by the agent.
- **Several checkpoints in one stage.** The answer could later carry an ordered list of commit groups
  `[{paths, message}]`. Today's `paths` + `message` is one group; the decoder, pre-stage check and "changed set within
  the listed paths" rule work per group, and the verdict's one-step chain would become one step per group (the removed
  chain walk, bounded by the group count). No compatibility is promised; this only avoids painting into a corner.

## 15. Not verified

Run since revision 3: the unit tests and the real-Git wiring tests of sections 11 and 16, on Linux, git 2.54. They
proved that without the hardened environment `--no-verify` leaves `prepare-commit-msg`, `post-commit`,
`post-index-change` and `reference-transaction` running (and that with it none runs), that real `history` bodies carry
the trailer as written, and that `--relative-paths` pointers pass the check. Still from reading only: codex flag values
(binary strings) and whether `never` falls back to read-only; whether codex protects a `.git` file in the writable
root; that `git commit` refuses to move a HEAD changed since it read it (git's ref transaction, believed); whether strict
mode accepts `maxItems` (bounds therefore live in the decoder only); how a resume launch behaves; macOS (Seatbelt,
`/private` paths). **Residual risk classes:** a clean/smudge/textconv driver or other command from the person's own Git
config (or a repository config the person wrote) still runs during `status`/`add`/`diff` (section 5); the pointer race
and the FIFO hang of section 4; and everything codex-dependent (the sandbox actually bounding the agent).

## 16. Revision 4: the implementation review's repair round

- HIGH: the pointer was judged lexically (`normpath`) while Git resolves it; fixed as section 4 (resolution as Git's,
  G and C outside the slot, back-pointer resolved, `common_dir` equality, no symlinked slot path; relative paths kept).
  Real-Git tests reproduce both attacks (a pointer redirected to the person's `.git`; a fake Git directory in the slot
  with a `clean` filter) and show them refused with no hook or filter marker and the person's branch unchanged.
- MEDIUM: the racing-verifier `nothing_written` (section 5 step 5) and the `plan_commit` fence (section 6); the `.git*`
  file rule (section 5 step 4); tests that kill the mutations "no pointer check before `record`", "no pointer check
  before `stage`", "`unchanged` may adopt", "no race re-read", "no verdict fence", "no `.git*` rule"; a real-Git trailer
  adoption row.
- LOW: the listing is made safe to print; `list --stuck` reads no slot; a listed ignored path is `ignored`; the FIFO
  residual and the git_porcelain follow-ups are named (section 4); `Admission.plan_path` (unused) removed; stale lines in
  .4.3.1.4 and .4.3.1.5 rewritten; the Git-write rule (tests/rules) also catches a reference of `stage`/`record` on any
  receiver, a bare call, and the name as a string (`getattr(slot, "record")`); it cannot see a name built at runtime.
