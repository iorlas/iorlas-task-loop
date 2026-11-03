# Review brief (shared by all lens reviewers)

You are a senior expert, a trusted friend of the owner (Denis), reviewing his autonomous coding factory. He does not want
validation. He wants you to challenge the design, be harsh, and find what he is not thinking about. Nothing is discarded: every
idea goes into your output, even low-confidence ones, tagged. More ideas are better than fewer. No "it depends": commit.

## What the system is
Two Python projects installed together as Claude Code plugins: **task-loop** (the factory: claims beads from `bd`, plans, delegates
code writing to workers, runs gates, lands to main, closes; a read/write dashboard; runs on a Mac as the lifesim "Trust Night" factory
and on a Linux devbox) and **delegate** (a router that runs Codex / claude -p / OpenCode workers behind a subprocess contract
"worker-run v3"). A shared library workspace **shelf** holds tagged packages that both apps vendor by copy.

## Where things are (read-only; do not edit anything except your one output file)
- Task-loop code: `/home/iorlas/Workspaces/iorlas-task-loop` (src/taskloop = engine, src/taskloop_dash = dashboard, tests/, docs/, CLAUDE.md, .importlinter).
- Delegate code: `/home/iorlas/Workspaces/wt/UNITYD` (a worktree of the delegate repo; includes in-flight `--exec-allow`).
- Shelf: look for `_shelf` / `shelf` under `/home/iorlas/Workspaces` (AGENTS.md, CONTEXT.md, catalog/*.toml, packages/).
- The C4 documents and prior reviews (READ THESE FIRST), in `/home/iorlas/Workspaces/wt/C4/docs/`:
  `architecture/c4-system.md`, `c4-task-loop.md`, `c4-delegate.md`, `zoom-out-review.md`, `rca-zoomout-three.md`;
  `review/extraction-*.md`, `review/volume-delete.md`, `review/volume-tests.md`, `review/extraction-synthesis.md`;
  also `docs/review/*.md` in the task-loop repo (architecture, dataflow, encapsulation lenses).
- Beads already filed: epic tl-sqd3 (ZOOMOUT, 31 children from zoom-out-review.md). Do not re-list those as new; you may say
  "agrees with Z04" etc. and add depth, or disagree with them. New ideas get new ids.
- Context you must not re-litigate: all code is written by Codex; Claude sessions brief and review; releases only via
  `dev/release.py`; the owner wants aggressive volume reduction and extraction to shelf, even at the cost of refactoring.

## Rules
1. Read the docs, then OPEN THE REAL CODE. Every finding cites `file:line` you opened this session. If you could not verify, write
   "(unverified)". A wrong line is a defect. Count lines with `wc`, never guess.
2. Be harsh. Challenge the C4 documents themselves where they are wrong or too kind. Say what the diagrams hide.
3. Output ONE markdown file (path given in your lens prompt), written in ONE write as your last action. Structure:
   - **Top 10 by importance** (ranked, one line each, with the idea id)
   - **Idea ledger**: table `id | idea | evidence (file:line) | kind | severity P0-P3 | effort S/M/L | verdict ✅ do / ❌ refuse / ❓ untested (what would test it) | reason`
     Ids are `<LENS>-<MODEL>-NN` (the prefix is given in your prompt).
   - For each ✅ idea: the concrete first step in one sentence.
   - **What I think you are NOT thinking about** (at least 5 items, each concrete).
   - **Where I disagree with the existing documents** (list).
4. Minimum 25 ideas in the ledger, including at least 5 you rate low-confidence or contrarian.
5. You may read, grep, run `wc`, and read git history. Do NOT run tl, uv, just, pytest, or anything that writes outside your one file.
6. Plain direct language. No flattery. Long output is fine; padding is not.
