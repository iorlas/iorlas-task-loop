# REVIEWBASE: the reviewer reads the base branch's instruction files (tl-7i9k.58)

Status: design, no code. Part of TRUSTROOTS (tl-7i9k.6): task-loop refuses an *unapproved* change to a trust root (AGENTS.md, CLAUDE.md,
.claude/, .codex/) before review. This note covers the *owner-approved* change: the reviewer must still be judged by the **base**'s rules, not
the candidate's, or an approved edit of AGENTS.md rewrites the rules of its own review.

## How instructions reach a worker today (read from the code)

| Harness | Instruction source | Where |
|---|---|---|
| Codex | reads `AGENTS.md` itself, walking from cwd up; `project_doc_fallback_filenames=["CLAUDE.md"]` | `app/decide.py:codex_isolation` |
| Claude (`claude -p`, restricted) | does not load `CLAUDE.md`; delegate pastes `repo_instruction_text(cwd)` into the prompt (cap 32 KiB) | `app/launch.py:repo_instruction_text` |
| OpenCode | reads `AGENTS.md` itself; CLAUDE.md pasted only when no AGENTS.md exists | `app/launch.py:~264` |

All three take the files from the **worktree** (`decide.repo_instructions(cwd)`: AGENTS.md else CLAUDE.md, per folder from root to cwd).
`RunRequest` (`contracts/delegate.py`) has no way to change that. Repo skills under `.agents/.codex` are already switched off for Codex by path
(`codex_isolation`); `.claude/` settings are not loaded by a restricted `claude -p`.

## Decision to make

How does the caller say "use the base's files"?

- **A. A git ref (recommended).** `RunRequest.instructions_ref: str` (a commit sha; empty = today). Delegate reads each instruction file with
  `git show <ref>:<path>` for the same folders it walks today (cwd relative to the repo root), never from the filesystem.
  One authority (the object database, immutable, no temp dir to clean), the caller names only a sha it already has (`engine.base` tip).
- B. A directory of copies. task-loop materializes base copies into a temp tree and passes the path. Two writers of the same facts, a
  cleanup duty, and a path the reviewer could in principle write to.

## Design (option A)

1. **Contract.** `RunRequest.instructions_ref` (task-loop `contracts/delegate.py`, delegate `contracts/wire.py`, `--instructions-ref` flag);
   new capability `instructions_ref` in `contract.json` (`wire.CAPABILITIES`). `to_argv` calls a `require_instructions_ref(contract)` exactly
   like `require_writer_exec_allow`: an older delegate **refuses at admission**, never silently drops it.
2. **Delegate loading.** One function `instruction_files(cwd, ref)` replaces `repo_instructions(cwd)`: with a ref it lists and reads through git
   (`git ls-tree` / `git show` on the cwd's repo), without one it reads the filesystem as now. `repo_instruction_text` uses it for Claude and
   OpenCode (already prompt-injected, so no harness change).
3. **Codex.** Native loading must be off or it would also read the worktree's AGENTS.md: with a ref, add `-c project_doc_max_bytes=0` and put
   the base text in the prompt the way Claude does. (To verify first with the installed codex: that `project_doc_max_bytes=0` really stops
   AGENTS.md loading; if not, run the reviewer with cwd in a sibling checkout of the ref.)
4. **task-loop.** The review step sets `instructions_ref` to the base commit it already resolves for the gate (`profile_at` source commit).
   Writers keep today's behaviour (a writer is *meant* to see the candidate's instructions, they are its task's rules).
5. **Out of scope / residual.** `.claude/` and `.codex/` *settings* (hooks, MCP) are not read by a restricted/isolated worker today; this note
   does not change that. A reviewer that opens `AGENTS.md` from the worktree with a Read tool still sees the candidate's text; the claim is only
   "the system prompt and project instructions are the base's".

## Tests (written first)

- Unit: `instruction_files(cwd, ref)` on a repo whose worktree AGENTS.md differs from `ref`'s: returns the ref's text; absent ref: the file's.
- Unit: `to_argv` with `instructions_ref` against a contract without the capability raises (older delegate refuses).
- Unit: for each of Claude and OpenCode the built prompt holds the base text and not the worktree text. Codex: argv carries
  `project_doc_max_bytes=0` and the stdin holds the base text.
- task-loop: the review call's `RunRequest` carries the base sha; the write call's does not.

## Size

M, in four slices (contract + capability; loading function and Claude/OpenCode; Codex; task-loop review wiring), one PR each.

## Built (owner chose A)

Slices folded into one PR: contract + capability; `decide.base_instructions` / `launch.repo_instruction_text(ref=)`; Codex
`project_doc_max_bytes=0` plus base text in the prompt; OpenCode refused (`launch.ref_problem`: it loads the work tree's AGENTS.md itself);
task-loop reviewer request carries `rev_parse(wt, engine.base)` (a base that does not resolve is warned in the run log, not silent).
The ref joins the call's identity digest only when set, so existing fingerprints are unchanged.
Unverified here: that the installed `codex` honours `-c project_doc_max_bytes=0`; the argv is asserted, the CLI behaviour is not.
