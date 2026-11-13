
=============== 00-README.md ===============
# task-loop docs ontology (a2kay-format, temporary checker on shelf libs)
Kinds are a2kay type YAMLs (name, when_to_use, file_pattern, shape, id, fields, link[...] types).
Rows (rule, case, outcome, limit, operation, gap, transition, capability, failure, step_row, check) are a2kay
INLINE kinds: flow-style YAML lists in the owner's frontmatter. No table parser; any-frontmatter + schema check.
References: `[[kind/id]]` in prose, `link[kind]` fields in frontmatter. `task/<id>` is pattern-checked only.

## Graph (kind -> kind via link fields)
persona --can--> area | external
external --used_by--> area ; external.failures --> outcome
area --touches--> area | external ; area --terms--> term ; area.rules --check--> check
area.cases --outcome--> outcome ; area.outcomes --handled_in--> area | workflow ; area.not_designed --task--> task
lifecycle --entity--> term ; --owner--> area ; transitions --outcome--> outcome
workflow --actors--> persona ; --areas--> area ; --externals--> external ; steps --causes--> lifecycle (+event declared there)

## Lifecycle vs workflow
lifecycle = the state machine of ONE thing (noun): states, events, next state. Statechart. Checked: every next state declared,
  every non-terminal state has an exit, every state reachable, states == code enum.
workflow = steps toward ONE goal across actors and systems (verb): order, who does what. Use case / BPMN-lite
  (no gateways or swimlane XML; numbered steps + a cases table). A step names the lifecycle event it causes.
One workflow touches many lifecycles; one lifecycle is moved by many workflows. The link is step.causes + step.event.

## Checker rules beyond schema (changed docs + reverse refs only)
refs resolve | area.owns globs match files | check<->test marker both ways | case table complete (declared states) |
lifecycle: states==source enum, reachability, exits, process-death+restart events | workflow step.event declared by its lifecycle |
holds/definition cells: no modal/hedge words | limit/operation source resolves | ids stable, retire by status never delete

=============== area.yml ===============
name: area
when_to_use: a bounded part of the system with one set of rules; read before changing code it owns
file_pattern: "docs/system/area/{slug}.md"
shape: leaf
id: {type: slug}
body: none
fields:
  - {name: read_when, type: string, required: true}
  - {name: owns, type: "set[string]", required: true}        # path globs; each must match a file
  - {name: touches, type: "set[link[area|external]]", required: false}
  - {name: terms, type: "set[link[term]]", required: true}
  - {name: rules, type: "list[rule]", required: true}
  - {name: cases, type: "list[case]", required: false}
  - {name: outcomes, type: "list[outcome]", required: false}
  - {name: limits, type: "list[limit]", required: false}
  - {name: operations, type: "list[operation]", required: false}
  - {name: not_designed, type: "list[gap]", required: false}

=============== capability.yml ===============
name: capability
storage: inline
key: does
when_to_use: one thing a persona does, through which area or external system
fields:
  - {name: does, type: string, required: true}
  - {name: through, type: "link[area|external]", required: true}

=============== case.yml ===============
name: case
storage: inline
key: state
when_to_use: one row of an exhaustive decision table; the table drives a parametrized test
fields:
  - {name: table, type: string, required: true}             # table name, e.g. start
  - {name: state, type: string, required: true}             # one token
  - {name: outcome, type: "link[outcome]", required: false}
  - {name: effect, type: string, required: true}

=============== check.yml ===============
name: check
when_to_use: a test or import-linter contract that proves a rule; declared by the test, not by a doc
storage: inline
key: id
fields:
  - {name: id, type: string, required: true}
  - {name: source, type: string, required: true}            # path::test or contract name

=============== external.yml ===============
name: external
when_to_use: a system outside the factory (tracker, Git, code host, agent harness); read before touching its port
file_pattern: "docs/system/external/{slug}.md"
shape: leaf
id: {type: slug}
body: none
fields:
  - {name: owns_facts, type: "set[string]", required: true}
  - {name: port, type: string, required: true}              # code path; must exist
  - {name: used_by, type: "set[link[area]]", required: true}
  - {name: rules, type: "list[rule]", required: false}
  - {name: failures, type: "list[failure]", required: false}

=============== failure.yml ===============
name: failure
storage: inline
key: when
when_to_use: how an external system fails and the typed outcome that results
fields:
  - {name: when, type: string, required: true}
  - {name: outcome, type: "link[outcome]", required: true}

=============== gap.yml ===============
name: gap
storage: inline
key: what
when_to_use: a part not designed yet; never a rule; points to the task that designs it
fields:
  - {name: what, type: string, required: true}
  - {name: task, type: "link[task]", required: true}

=============== glossary.yml ===============
name: glossary
when_to_use: the one file naming every domain term; read before using or inventing a word
file_pattern: "docs/glossary.md"
shape: leaf
id: {type: given}
body: none
fields:
  - {name: terms, type: "list[term]", required: true}

=============== lifecycle.yml ===============
name: lifecycle
when_to_use: the states one entity can be in and the events that move it; read before adding a state or an event
file_pattern: "docs/system/lifecycle/{slug}.md"
shape: leaf
id: {type: slug}
body: none
fields:
  - {name: entity, type: "link[term]", required: true}
  - {name: owner, type: "link[area]", required: true}
  - {name: source, type: string, required: true}            # path::StateEnum; declared states must equal its members
  - name: states
    type: "list[string]"
    required: true
    classes: {live: [], open: [], done: []}                 # a2kay lifecycle classes; terminal = done
  - {name: events, type: "set[string]", required: true}     # must include process-death and restart
  - {name: transitions, type: "list[transition]", required: true}

=============== limit.yml ===============
name: limit
storage: inline
key: name
when_to_use: a policy number; the code constant is the authority, this row names it
fields:
  - {name: name, type: string, required: true}
  - {name: source, type: string, required: true}            # path::symbol; must resolve

=============== operation.yml ===============
name: operation
storage: inline
key: name
when_to_use: a use case other slices or commands call
fields:
  - {name: name, type: string, required: true}
  - {name: source, type: string, required: true}            # path::symbol; must resolve
  - {name: outcomes, type: "set[link[outcome]]", required: false}

=============== outcome.yml ===============
name: outcome
storage: inline
key: name
when_to_use: a typed result other code branches on; never a parsed string
fields:
  - {name: name, type: string, required: true}
  - {name: carries, type: "set[string]", required: false}
  - {name: handled_in, type: "link[area|workflow]", required: true}

=============== persona.yml ===============
name: persona
when_to_use: a human or agent role that acts on the system; read to learn what a role can reach
file_pattern: "docs/system/persona/{slug}.md"
shape: leaf
id: {type: slug}
body: none
fields:
  - {name: nature, type: "enum[human < agent]", required: true}
  - {name: can, type: "list[capability]", required: true}

=============== rule.yml ===============
name: rule
storage: inline
key: id
when_to_use: one binary, present-tense requirement; true or the system is wrong
fields:
  - {name: id, type: int, required: true}
  - {name: applies_to, type: string, required: true}        # scope; uses glossary terms or paths only
  - {name: holds, type: string, required: true, standalone: true}   # lint: no modal or hedge words
  - {name: check, type: "link[check]", required: false, default: none}

=============== step_row.yml ===============
name: step_row
storage: inline
key: do
when_to_use: one numbered action of a workflow; an event on a lifecycle or an operation of an area
fields:
  - {name: do, type: string, required: true}
  - {name: actor, type: "link[persona|area|external]", required: true}
  - {name: causes, type: "link[lifecycle]", required: false}   # the lifecycle the step moves
  - {name: event, type: string, required: false}               # must be declared by that lifecycle

=============== term.yml ===============
name: term
storage: inline
key: name
when_to_use: a domain word other docs may reference as [[term/<name>]]
fields:
  - {name: name, type: string, required: true}
  - {name: definition, type: string, required: true, standalone: true}
  - {name: avoid, type: "set[string]", required: false}   # retired or confusable words

=============== transition.yml ===============
name: transition
storage: inline
key: from
when_to_use: one cell of the state x event table; every declared pair has exactly one row
fields:
  - {name: from, type: string, required: true}
  - {name: event, type: string, required: true}
  - {name: to, type: string, required: true}
  - {name: outcome, type: "link[outcome]", required: false}

=============== workflow.yml ===============
name: workflow
when_to_use: a goal reached by steps across actors and systems; read to see who does what in what order
file_pattern: "docs/system/workflow/{slug}.md"
shape: leaf
id: {type: slug}
body: none
fields:
  - {name: goal, type: string, required: true}
  - {name: actors, type: "set[link[persona]]", required: true}
  - {name: areas, type: "set[link[area]]", required: true}
  - {name: externals, type: "set[link[external]]", required: false}
  - {name: steps, type: "list[step]", required: true}
  - {name: cases, type: "list[case]", required: false}
