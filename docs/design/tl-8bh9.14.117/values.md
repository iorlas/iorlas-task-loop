# Values (proposal for AGENTS.md)

Status: revision 3, 2026-11-15. The owner said yes and asked for it shorter, tag-based and in plain words. The final text
is the "Values" section of AGENTS.md (uncommitted edit in this worktree); this file keeps only the sources below.

AGENTS.md holds the rules (what to do). Values are what every reviewer, subagent and factory agent weighs when rules run
out or conflict, and judges a decision by. Each line is the owner's own principle; sources are in the table below.

## Proposed text for AGENTS.md (a "Values" section, near the top)

Judge every design, change and review by these. When two conflict, the lower number loses.

1. **Architecture over code.** The structure decides the outcome; code only fills it. Fix the structure, not the symptom.
2. **Guardrails over discipline.** Make the wrong state impossible to write (types, closed vocabularies, typed outcomes,
   constraints, import contracts) rather than something to remember not to do. A rule only a person can break is a defect
   in the design.
3. **Simplicity.** Fewer concepts, files and lines. The simplest system, not the smallest diff. Complexity must earn
   its place with a stated reason.
4. **No redundancy: one way, one owner.** Every fact and every action has exactly one home. No duplicate, shadow copy,
   fallback or second reader.
5. **Do it right, then wipe.** Make the right design even when it deletes working things. No backward compatibility, no
   dual path, no alias for a retired name. Deletion is a normal, welcome change.
6. **No sunk cost.** Existing code, names, columns, plans or earlier work are never a reason to keep something wrong.
   Decide as if starting from scratch.
7. **Consistency.** The same thing is done the same way everywhere, with the same word. A new way for an old problem needs
   a reason, and then replaces the old way.
8. **Explicit over implicit.** State, time and I/O enter through narrow typed ports; no magic strings, no regex over text for
   control, no hidden defaults, no ambient environment.
9. **Fail fast and visibly.** A failure is a typed, readable result, never a silent default or a retry that hides it. Fix
   the root cause; add no monitoring layer to watch a symptom.
10. **Least authority.** An actor can do only what its job needs. An agent can never weaken the checks, rules or record that
    judge its own work.
11. **Evidence over opinion.** Claims are verified (file and line, output, a measurement) or marked unverified. Unknown is
    unknown, never zero. A decision names what would reverse it.
12. **The owner decides meaning.** Names, glossary terms, irreversible or outward actions and anything marked proposed wait
    for the owner, who is given options with reasons.

Briefs and reviews: a subagent brief says "judge by the AGENTS.md Values; for each finding name the value it serves; separate
verified from unverified; give the condition that would reverse your verdict".

## Where each value comes from

| value | source |
|---|---|
| 1 | owner 2026-11-15 ("architecture matters more than the code"); AGENTS.md "Architecture and design", vertical layout |
| 2 | owner 2026-11-15 ("guardrails, making it impossible to get into a problem"); AGENTS.md closed vocabularies as enums, typed outcomes, import-linter contracts |
| 3 | owner 2026-11-15 ("simplicity"; "less entropy"); owner principle 2026-10-29 (no extra monitoring or patches that grow the code base); AGENTS.md "no unused speculative features" |
| 4 | owner SINGLE PATH rule (2026-11-08); AGENTS.md "One owner per fact"; glossary diet |
| 5 | AGENTS.md "No backward compatibility, dual readers"; owner 2026-11-15 ("make things right at the cost of wiping stuff out") |
| 6 | AGENTS.md "Decide every name, meaning and structure as if starting from scratch ... sunk cost" |
| 7 | owner 2026-11-15 ("consistency"); AGENTS.md names rule, glossary "one meaning across the code, CLI, database and logs" |
| 8 | AGENTS.md "State/time/IO enter through narrow explicit ports", "No regex over display text", closed vocabularies |
| 9 | owner principle 2026-10-29 ("let the system fail fast, see the issue, fix the root cause"); typed outcomes |
| 10 | AGENTS.md ownership table; profile trust split (`required`, `target`, `land` from main) |
| 11 | owner 2026-11-15 ("everything we do should be evaluated"); glossary "Unknown cost is unknown, not zero" |
| 12 | AGENTS.md naming rule; "Proposed decisions remain proposed"; Git authority line |

## Open

- Which of 8 to 12 does the owner want as values (they are my additions, inferred from existing rules); which to cut.
- Order. 1 to 7 are the owner's own words in order of the owner's message; 8 to 12 are inferred. The conflict rule ("the
  lower number loses") makes order matter: for example 2 above 3 means a guardrail may add a little code.
- Placement. AGENTS.md is the only instruction file and is in every agent's context, so the section belongs there, about
  30 lines.
