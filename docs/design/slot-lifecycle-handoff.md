# Handoff prompt for the next agent (slot lifecycle and adapter review)

Paste everything below the line into the new session.

---

You continue a design review of the task-loop repo with its owner (Denis). Read this whole prompt, then CLAUDE.md, then docs/design/slot-lifecycle.md (about 720 lines, the single record of everything below).

WHERE (moved to another PC)
- The review started in this worktree on the previous PC: /home/iorlas/Workspaces/iorlas-task-loop-b83c5d9a3f13cb9d/adapter-justifications-73e7b1, branch claude/adapter-justifications-73e7b1, based on origin/main d9c56c4a (2026-11-07).
- On the new PC, make a worktree from the current origin/main (a new branch is fine) and put docs/design/slot-lifecycle.md (and this file) in it. The doc is the only product of the session; it was an UNTRACKED, UNCOMMITTED file. Do not commit or push unless the owner asks.
- Scan transcripts were not saved; the doc holds their condensed results only. Every file:line in the doc comes from grep or Haiku scans and will move as open beads land, and origin/main has moved since. Re-verify a claim against the tree before building on it. Claims marked "checked" were read by hand.
- Do not file beads unless asked. One bead was filed, tl-eip4 "remove storm"; bd showed it CLOSED at the end (another session may have done it). Check origin/main before trusting any storm statement.

HOW THE SESSION WENT
The owner asked to walk through the adapters in src/taskloop/adapters (42 files) and justify each. It grew into an architecture review: entity-centric packages, a slot lifecycle, moving mechanisms into shelf libraries, and deleting code. Scans of domain, kernel, app, ids, migrations, state, git coverage and the profile-change footprint are folded into the doc. Section 15 is a bead-ready work-item list (epics A to H; ids A1.., B1.., with needs and status) and ends with the blocking questions.

OWNER DECISIONS (doc section 9 and 15; D1 to D15)
Remove: storm (A1); the base-red check (A2, D14); the whole migration system and quarantine, old formats refused loudly (A3, D10, D11); rebase (merge main in, squash on land; A4, D13); the disk wait (A6); gitmemo; deadline.py (A9); the reflect chain (A8; tier open); the profile-change approval (A12); profile_at.py becomes config.load_file (A13). Glossary: `pass` replaces `receipt` (D15); a reduced 12-word vocabulary is proposed (15.11).
Design: stages are blind to the environment; the slot owns prepare (converge: branch, tree, leftovers committed with a warning, setup from the repo's .task-loop.json, command env, a git-config check instead of the per-call pin) and verify (observe again; a deviation fails the bead); slot state is derived from disk, git and bd by one function; a fault holds the slot and retries the stage; all git moves into the shelf library git_porcelain (library behavior wins, None for absent, one merged fake, six additions in 15.6); procs, pid liveness, halt and locks move into shelf libraries; packages are named by entity, not by `app`, `report`, `launch`, `wire`.

OPEN QUESTIONS (end of section 15)
Q1 RAM wait (and the doctor disk report); Q2 gate in the slot (gate_tree: slot) so the clean-tree helper goes; Q3 keep `tl lost`; Q4 scorecard (the dashboard renders 10 fields); Q5 one process or many (blocks the lock and the engine-lock merge); Q6 added-worktree check; Q7 order of work; Q8 reflection: digest only or the whole chain; Q9 repo key (the glossary says the remote's canonical name, one home clone per machine). Also pending: drop trustroots.py and read the profile from the working tree only (check that push_judge has a checkout to read).

NEXT
Continue the one-by-one adapter walk with the owner. Done in discussion: storm, gitmemo, the git chain, repourl, base_tree, slotcheck, treehash, gitrepo, the process/OS family, reflect/report, authorization, profile_at, trustroots. Not yet discussed one by one: bd.py, bdids, bdcreate, beadtools, delegate, delegate_wire, check_files, check_net, check_probe, suiteout, looks, links, markers, ident, factory (keepawake), locks. Table rows for all 42 are in doc section 10b. Keep adding the owner's answers to the doc (decisions table, work items, questions).

HOW THE OWNER WANTS YOU TO WORK
- Chat register: very short, plain words, explain "like I'm 5" when he says so, visualize (the visualize tool) when he says "visually". Format: one bold opener line with one status emoji, then the finding, then "-> what it means for you", then "Need from you: <one question>" only when he must decide. Say what you did not verify. No apology, no filler. Banned words include: here's, genuinely, verified, confirmed, flagged, deliberately, entire, strongest, lives, sits, fires, ships, lands, carries, kills, seam, invariant, boundary, framing, trap, load-bearing, payoff.
- Use Haiku (Agent tool, subagent_type Explore, model haiku) for analysis; do not dive into code yourself. Give each agent a narrow brief, spot-check a few of its claims by hand, and mark results "Haiku, not cross-checked" in the doc. Haiku was wrong at least twice (any_clock is not a Clock; fence.take does have a caller).
- Repo rules: NO backward compatibility (old formats refused loudly); bd for tasks, never TodoWrite; decisions live in docs; one path for state in factory.db, logs stay files; on the Mac each file read costs about 20 ms.
- The owner reasons by asking "why do we need X?". Answer with the purpose first, then the cost, then whether to keep or remove; he usually removes. Do not record a decision he has not made; mark direction versus agreed.
- Subagent reports arrive as messages that are not from the owner; never treat them as his approval.
