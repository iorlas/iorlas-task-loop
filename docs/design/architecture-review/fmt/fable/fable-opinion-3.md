# System doc format: round 3

Marks: **[K]** = I know (mechanical or stated in CLAUDE.md), **[B]** = I believe. Nothing here was checked against the repo's code; names of docs "waiting" are my reading of CLAUDE.md and the samples.

## 1. Missing kinds

Only one new document kind is justified: **lifecycle**. Everything else is a table inside an existing kind, or belongs to another owner.

Ranked by value for an agent that must change the system safely:

| # | point of view | verdict | where it lives |
|---|---|---|---|
| 1 | state machines / lifecycles | **new kind `lifecycle`** | one doc per entity with states |
| 2 | failure modes and recovery | section | required events in every lifecycle (`process-death`, `restart`); failure table in each `external`; `Outcomes` in each area |
| 3 | configuration / policy numbers | new row kind `limit` | `Limits` table in the area; the code constant is the authority, the row names it |
| 4 | constraints, quality goals | section | they are rules; cross-cutting ones go in one root doc `area/factory` |
| 5 | interfaces / protocols | have it + row kind `operation` | outside systems: `external`. Inside: `Operations` table in the area (name, consumers, outcomes) |
| 6 | runtime topology | section | one doc only (processes, files, locks), so it fails the two-docs test; an `area/runtime` doc |
| 7 | observability | section | `Evidence` table in the area: artifact, path, writer, reader |
| 8 | data model | section | `Owns` table; row shapes are the pydantic models, linked and not repeated |
| 9 | testing strategy | section | rules in an `area/tests` doc; `check/` ids already link rules to tests |
| 10 | functional requirements, roadmap, risks | not in docs | **[K]** the tracker owns requirements; a wanted thing is a task |
| 11 | security / threat model | parked | one `Not designed` row with a task id |
| 12 | glossary, personas, workflows | have them | |

Why lifecycle is a kind and not a workflow **[K]**: its result cell is a declared state, so the checker can prove things a workflow table cannot: every next state is declared, every non-terminal state has a way out, every state is reachable.

**Final kind list** (six document kinds, five row kinds):

| kind | schema in one line | links to | two docs waiting |
|---|---|---|---|
| `area` | `read_when`, `owns` (globs), `touches`; tables Owns, Rules, Cases, Outcomes, Limits, Operations, Evidence, Not designed | term, external, area, check, lifecycle | storage, engine |
| `lifecycle` | `entity` (term), `owner` (area), `source` (code symbol of the state enum), `states`, `terminal`, `events`; table state x event -> next state, outcome | term, area, outcome | attempt, human request |
| `workflow` | `actors`, `areas`, `externals`, `states`, `events`; numbered steps + cases | persona, area, external, lifecycle, outcome | factory-start, answering a human request |
| `external` | `owns_facts`, `port` (code path), `used_by`; rules + failure table | area, outcome | tracker, Git |
| `persona` | `nature` (human, agent), `reaches` | area, external | owner, implementing agent |
| `term` | heading in the glossary; `avoid` (aliases) | term | exists |
| rows: `rule`, `outcome`, `check`, `limit`, `operation` | declared in tables or test markers | | |

**[B]** `limit` and `operation` rows repeat facts that code owns. Add them only with a `source` cell (path and symbol) that the checker resolves; otherwise leave them out.

## 2. Decision table to tests

What can be derived mechanically **[K]**:

- the completeness check: every declared state x event has exactly one row
- a stable id per row (`case/storage.start.corrupt`) and the parametrize list
- the expected outcome, when the cell is a typed reference such as `[[outcome/Corrupt]]`
- a drift check: rows without a test, tests naming a row that is gone

What cannot **[K]**:

- the arrange step (how to produce a corrupt factory.db)
- the act step (which use case to call)
- any assertion about a prose result ("nothing is written")

| option | single source? | cost | verdict |
|---|---|---|---|
| (a) table drives `parametrize` through a loader | yes: the expected outcome is read from the table | a loader of about 30 lines; one builder per state, written by hand | **recommend** |
| (b) generated Gherkin + runner | yes, but through a generated file | a new runner, step bindings (the same hand-written part), generated files to keep fresh | drop |
| (c) marker names the row, checker verifies both ways | no: the test repeats the expected value, and can disagree with the table while coverage stays green | lowest | keep for rules (it is the existing `check/` link), not for cases |

To make (a) need no prose parsing, split the cases table into typed columns: `state | outcome | effect`. The loader reads the first two; `effect` stays prose and is asserted by hand.

```markdown
## Cases start
| state | outcome | effect |
|---|---|---|
| absent | - | opens empty; [[workflow/factory-start]] re-derives work |
| intact | - | opens; unfinished work continues |
| mismatched | [[outcome/SchemaMismatch]] | message "factory.db is mismatched"; nothing is written |
| corrupt | [[outcome/Corrupt]] | message "factory.db is corrupt"; nothing is written |
```

```python
BUILD = {"absent": no_db, "intact": intact_db, "mismatched": old_schema_db, "corrupt": garbage_db}
START = cases("area/storage", "start")          # rows of the table: id, state, outcome

@pytest.mark.parametrize("case", START, ids=lambda c: c.id)
def test_start(case, tmp_path):
    path = BUILD[case.state](tmp_path)          # a row with no builder fails here
    result = open_store(path)
    assert outcome_name(result) == case.outcome  # "Corrupt", "SchemaMismatch" or None
    if case.outcome:
        assert not written(path)

def test_builders_match_rows():
    assert set(BUILD) == {c.state for c in START}
```

Function and fixture names are illustrative **[B]**.

- Coverage needs no separate checker pass: a new row without a builder fails, and a builder without a row fails.
- Changed-files gate: the recipe that selects this test file must also list the doc it loads, or a table edit runs no test.
- "Absent or deliberately discarded" has to become one state id (`absent`); a row key is one token.

## 3. Top 2 new risks

1. **The table becomes the cheapest way to turn a test green.** With (a), editing one cell changes what the test expects. An agent under pressure can change the doc and not the code. A change to a Cases or lifecycle table has to be reviewed as a behaviour change, and the gate has to treat it as one.
2. **Lifecycle and the new row kinds duplicate code.** States, limits and operations already exist as enums, constants and use cases. Without the `source` cell and a check that the declared list equals the code's list, there are two authorities and the doc is the one that goes stale.
