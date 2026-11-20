Status: **evidence**. Historical architecture-review format/opinion specimen; its proposals are not adopted system authority.

# System doc format: independent opinion

Marks: **[K]** = I know (follows from the material or is mechanical), **[B]** = I believe (judgment, not measured).

## 1. One binary strength

Yes, with one step further: drop MUST as well.

- **[K]** MUST only has meaning next to SHOULD and MAY. With one strength the keyword carries nothing. Write rules in the present indicative: "a callee opens no transaction".
- **[K]** Variant C shows the failure: R11 is the only SHOULD, and nobody can say whether a change violates it.
- **[B]** Agents treat SHOULD as optional under pressure and as mandatory when idle. Both are wrong, and which one you get is unpredictable.

What replaces "optional" and "aspirational":

| kind | where it goes |
|---|---|
| wanted, not built | the tracker (bd), not the doc |
| direction of growth | rewrite as a binary admission rule (see S11 in the sample), or leave it out |
| undecided | `Open` section, declared non-binding, which the generator excludes from rules |
| priority between rules | not in the wording; if two rules collide, one scope is wrong, so fix the scope |

Keep one second axis, and keep it separate from strength: **checked or unchecked**. A rule with `check: none` is fully in force but nothing proves it. The generator should count these.

## 2. Exceptions

| option | verdict | reason |
|---|---|---|
| rule + exception list | drop | the rule reads as universal, the list drifts, and a test has to parse prose |
| scope inside the rule | **default** | a permanent exception is just a narrower scope; the rule stays total within it |
| exhaustive decision table | **use when there are 2+ cases** | forces every case to be named and exposes gaps |
| named waiver (owner, task id, ratchet) | **use, but outside the doc** | this is temporary debt; it belongs in the test's allowlist, which may only shrink |

- **[K]** The decision table already paid off here: rewriting rule 8 as cases shows the source never says what happens at start with a corrupt or mismatched DB.
- **[B]** Expiry dates on waivers work badly for agents; nobody acts when the date passes. A task id plus a shrink-only allowlist test works better.
- **[K]** A scope written as "everything except X" is an exception list in disguise. Allow it only when X is a glossary term or a path, and the test reads the same scope.

## 3. Formats

| idea | captures well | weak or missing | verdict |
|---|---|---|---|
| Diataxis reference (B) | entities, signatures | no rule ids, no test links, prohibitions vanish (B lost rules 1, 2, 5, 8 as rules) | not enough alone; keep only "reference, not tutorial" |
| RFC 2119 (C) | nothing extra once binary | invites SHOULD | drop |
| EARS (C) | conditions: when, while, if/then | ownership, structure; verbose with MUST | keep the idea as a scope column |
| decision table | conditional behaviour, exhaustiveness | structural rules | use for cases |
| graph edges (D) | binary relations, cross-area links | conditions, quantities, n-ary facts; the verb vocabulary grows without limit (D has 12 verbs in 15 lines) | use as generated output, not as authoring format |
| Gherkin | one example scenario | 5x the length; describes examples, not rules | drop; the tests are the scenarios |
| contracts / invariants | "always holds" state rules | architecture rules about who may import what | use the phrasing; put real asserts in code |
| policy-as-code (Cedar, Rego) | allow/deny over a fact base | needs a fact extractor; second language | drop; import-linter and AST tests already do this |
| Datalog-ish facts | ownership, derived queries | same cost as above | drop as authoring; the generator can emit it |
| typed schemas (pydantic) | row shapes, outcomes | behaviour, ordering, transactions | the code is the spec here; the doc links, never repeats |
| table + rules (A) | everything at low cost | no scope, no check status, no links | the base to extend |
| hybrid (E) | links in frontmatter | over-compressed ("R6 Lock wait 5 s MUST yield StoreBusy" loses who waits) | right skeleton, wrong rule form |

**[B]** The one addition worth making that none of the five has: the rule id is declared in the test (`@pytest.mark.rule("storage.S3")` or the import-linter contract name) and the generator checks both directions. A doc-only link rots.

## 4. Recommendation

Smallest set:

1. **Frontmatter**: `area`, `read_when`, `owns`, `terms`, `touches`. The generator builds the graph from these.
2. **Owns table**: n-ary ownership facts.
3. **Rules table**: `id | applies to | holds | check`. Present indicative, no modal words.
4. **Cases**: a decision table per conditional rule, exhaustive, with an explicit last row.
5. **Outcomes**, and **Open** (non-binding).

Generator checks **[K: all mechanical]**:

- every word in `terms` is in the glossary; every area in `touches` exists and links back
- every `check` id exists as a test or contract, and every tagged test names a real rule
- lint the `holds` column for: must, should, may, could, usually, prefer, where possible, except
- report the count of `check: none` rules

### Sample

```markdown
---
area: storage
read_when: SQL, a store module, a transaction, factory.db, a row type
owns: src/taskloop/*/store.py; factory.db schema fragments; sqlite-store (shelf)
terms: slice store Tx reserve release attempt reservation slot step
touches: engine step human_requests dashboard
checks: tests/rules/test_storage_policy.py; .importlinter
---
# storage

## Owns
| owner | tables | writer | readers |
|---|---|---|---|
| engine (engine/attempt, engine/slot) | attempt reservation slot execution verification slot_release | engine use cases | engine, status |
| step (its own store) | checks_attempt check_result land_candidate setup_run published_branch | that step | that step, status |
| human_requests (human_requests/store) | request rows | human_requests | dashboard history |

## Rules
| id | applies to | holds | check |
|---|---|---|---|
| S1 | every module outside a slice's store.py | contains no SQL and no sqlite3.Connection; it calls typed use cases | sqlite-only-in-store |
| S2 | every table | has exactly one writing slice, derived from the path of the writing module; an engine table has no step-specific column; a step writes no engine table | table-ownership |
| S3 | a transition that crosses slices | runs in the starting slice inside one caller-passed Tx; the callee opens no transaction | no-nested-tx |
| S4 | an open write transaction | contains no Git, tracker, spawn, file or network call and no sleep; external work is: record intent (tx), act, record result (tx) | no-external-in-tx |
| S5 | every reserve and release write | is a guarded write (UPDATE ... WHERE precondition), explicit SQL in the store, named for the rule | none |
| S6 | a write waiting for the single writer lock | Cases: lock | none |
| S7 | every row crossing the store boundary | is a pydantic model (frozen, strict, extra=forbid), mapped in store.py by the shelf helper; callers index no tuple | none |
| S8 | factory.db at start | Cases: start; no backup, restore or file fallback exists | none |
| S9 | an upgrade that changes the schema | drains running attempts first, then discards the old DB; an old entry process writes nothing to the new schema | none |
| S10 | the dashboard | calls the same use cases as the CLI; read-only is a connection mode, not a second module | none |
| S11 | every helper in sqlite-store (shelf) | is used by two or more slices (today: row mapping, Tx, guarded update) | none |

## Cases
lock (S6)
| lock acquired | result |
|---|---|
| within 5 s | the write proceeds |
| not within 5 s | StoreBusy |

start (S8)
| factory.db | result |
|---|---|
| absent or deliberately discarded | work is re-derived from Git and the tracker |
| intact after a crash | unfinished work continues |
| any other state | a typed outcome below; behaviour not stated in the source (gap) |

## Outcomes
StoreBusy, StoreUnavailable, SchemaMismatch(found, expected), Corrupt. Each has a catalog entry (sentence + next action) in the owning slice; raw sqlite text is detail only.

## Open (not rules)
- attempt evidence and grow-only tables: deleted only by an explicit person-run operation, never by age
- history growth (quick_check on first open, attempts() scanning all history, board rebuild every 2 s): measure before designing
- golden source: only when a second machine or a server tracker exists
```

### Lost versus the earlier sample

- `status`, `date`, and the request-row columns (kind, facts, raw detail).
- Rule 5's reason ("carry the safety of reservation and release"); only the obligation remains.
- Rule 6's "transactions are short": dropped as unmeasurable.
- Rule 11 changed meaning: from "the shelf grows by absorbing" to an admission gate. The pointer to the shelf README is gone.
- Reading flow: a table row is harder to read than a sentence for rules S2 and S4.

Gained: scope per rule, explicit unchecked status (7 of 11), and one exposed gap.

## 5. Top 3 risks

1. **False rigidity.** Seven of eleven rules have `check: none`. Indicative wording states them as fact while nothing proves them. If that number does not fall, the doc is a wish list in a stricter voice.
2. **Link checks prove existence, not meaning.** The generator confirms a test named `no-nested-tx` exists, not that it enforces S3. A test can be weakened and the graph stays green. **[B]** Only review or mutation-style checks close this.
3. **Scope becomes the new escape hatch.** Narrowing "applies to" is how exceptions come back quietly, and each narrowing looks reasonable alone. Scopes need to use glossary terms or paths, and a scope change needs the same review as a rule change.

Not verified: I did not check that the four test ids exist in the repo.
