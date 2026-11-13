# task-loop docs ontology (a2kay-format, temporary checker on shelf libs)

Status: **design**. Archived ontology prototype, not an installed checker or current domain schema.
See the [prototype report](../docscheck-proto/REPORT.md); its specimens and the format alternatives remain examples.
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
