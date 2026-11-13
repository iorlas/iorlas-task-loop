# Brief (for a bd brainstorming task): external task sources and the code host

Origin: owner's words in the architecture-review grilling, 2026-11-13. Retain all context; this is not yet a design.

## The situation
- One of the owner's teams uses **Jira for tickets** and **GitHub for pull requests**. They have **no MCP access to Jira**, but every developer reaches Jira from a browser.
- Today they copy ticket text into files and ask agents to work from the files.
- The factory runs locally on the developer's PC.

## Ideas on the table
1. A "gather ticket" operation that uses an agent-browser CLI on the developer's PC to read a Jira ticket and **import it into local beads**. The factory then works only against beads (the golden path: local beads is always the claim store).
2. At the end of the work, leave an **action item for the human** to update the Jira status (later: report back automatically where access allows).
3. Whether the factory should move things in Jira at all is undecided.
4. Glossary note: a step operates on an existing task, so importing (which creates the task) is probably a command or a round-driven action, not a step. Undecided.

## Questions to settle
- Command vs round-driven vs step; where does the external key live on the bead (not yet checked whether bd has a field for it).
- **Drift:** if the Jira description or a comment changes after import, nothing detects it. Re-fetch at each admission? Owner's long-term view: the claim store should ideally be a server (Jira, GitHub, Linear or similar) to avoid drift; for now keep code reusable so that move stays possible.
- **Cross-PC claims:** bd leases are local to one machine. Owner's idea for server trackers: claim via assignee plus a label or custom field carrying an expiry time, ignored once stale; not atomic. Owner expects pickup to be limited by assignee (not only the `auto` label), which mostly avoids two engineers taking one ticket. Same person on two PCs stays open.
- **Two abstractions, not one:** the work tracker (Jira) and the code host (GitHub: pull requests, review state, merge) are different systems for this team. Where does the "needs review" flag live: Jira, the PR, or both? Landing for this team means a PR, not today's direct push to `main`.
- **Multi-repo:** a task in repo A that needs work in `shelf`. Owner's vision: it files a task in shelf, blocks itself, and a second factory instance works the shelf repo; later a cross-repo dashboard. Alternative: one factory with access to several repos (the glossary already says a factory can serve several repos; profile and slots are per repo). Owner's concern: isolation, consistency, one repo's constitution affecting another.

## Constraints from the repo
CLAUDE.md: one owner per fact; no backward compatibility; Git through its shelf API; the factory has no subprocess use, so a browser CLI would need an owning shelf process API; no new dependency without need.

## Deliverable
A design note with decisions, then separate implementation tasks. Not code.
