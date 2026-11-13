# ADR count and hierarchy

Status: **design**; proposed evaluation plan. The hierarchy, token budget and adoption are undecided.
Task: `tl-8bh9.14.130`. Prepared 2026-11-14 from the supplied owner requirements and repository
`3787e45427de45fedda96d078fe03f5d4348dc63`. This plan does not start the deferred trial or approve a structure.

## Authority and current evidence

The owner worries about index tokens paid in every session: even twenty ADRs may be too many. Trial
`work | requirements | design | code` lenses first, then consider hierarchy, domain, stage or point of view.
ADRs contain living meta decisions about how work is done; product behavior belongs in system design.
Brainstorming/design is deferred; nothing is adopted for the factory by this task's planning step.

Sources to retain with the later evaluation:

- [Review playbook, appendices Q and R](../architecture-review/architecture-review-playbook.md#appendix-q---owner-rulings-round-30-2026-11-13):
  living records rewritten in place, short history plus Git, meta scope, per-tier indexes and the open count concern.
- [Prototype ADR schema](../architecture-review/docscheck-proto/ontology/adr.yml) and its
  [four specimens](../architecture-review/docscheck-proto/docs/system/adr/): trial lenses, statements,
  read conditions and history. These are historical evidence, not production rules or tools.
- [Prototype generator](../architecture-review/docscheck-proto/src/docscheck/generate.py): indexes by
  tier and ID; it does not implement selective reading by lens. A lens field alone therefore proves no savings.
- [Documentation task .119](../tl-8bh9.14.119/plan.md#as-built) and [current inventory](../INDEX.md):
  ten extracted ADRs with provenance and enforcement links. They mostly describe product behavior;
  their existence does not approve treating them as the future meta-decision collection.
- [Foundation boundary](../tl-8bh9.8.7/plan.md), [glossary](../../glossary.md) and repository instructions:
  tracker owns requirements and owner answers; Git owns plans and selected design artifacts.

Origin: owner decisions relayed by architecture-review session `local_16bd6c79`, 2026-11-13.
Local `bd show` found neither this task nor `.119`; use the supplied task as the requirements source,
without creating replacement tasks, inferring completion or changing claims.

## Scope and timing

This is a bounded documentation experiment and owner decision, when the owner resumes the deferred design
work. Produce reviewable evidence before requesting a structure decision. Planning now does not lift that
deferral. Preserve the distinction between proposing an experiment, running it and adopting its result.

Keep subsequent trial artifacts under this task directory: `trial.md` for the candidate inventory,
classification, options, reading scenarios and results; `trial/` for exact index specimens and any small
reproducible measurement input; `decision.md` for the eventual linked owner answer and accepted scope.
These paths are proposed deliverables, not files required in this planning step.

No factory runtime, prompts, configuration, database, dependencies, CLI, agent instruction changes or
installed generator are part of the experiment. Preserve existing ADR paths, source links, tests and review
evidence. Reorganizing the live documentation, changing the global INDEX or adopting a shelf tool belongs
to a separately authorized bounded task after the decision. Introduce no factory vocabulary or glossary terms.

## Evaluation sequence, after resumption

1. Refresh the evidence against the then-current repository and requirements. Inventory existing ADRs and
   candidate meta decisions with a source, authority/date and current scope for each. Classify product,
   meta and mixed records; split mixed statements in the trial inventory without changing their originals.
   Map product content to its current owning design source; do not manufacture a second authority or lose
   the `.119` enforcement links. Do not choose an ADR count in advance.
2. Build the first comparable index specimen using the four trial lenses. Use the prototype's four
   examples as a starting sample, then cover the supported meta-decision candidates found in the census.
   Record ambiguous classifications and cross-cutting decisions. Each decision has one owning record;
   navigation can link to it from several places without repeating its statement as another authority.
   Keep records living, with a short change history; avoid supersession chains and one new ADR per edit.
3. Define the reading scenarios before measuring. Include worktree/session preparation, requirements
   clarification, design, code changes and a change crossing lenses. For each, list the actual navigation
   and indexes read, the decisions required and how the reader discovers another relevant group. Include
   a conservative session that needs every group. These are documentation scenarios, not factory steps.
4. Measure the lens trial against a flat one-line index of the identical candidate set. Then compare the
   alternatives below on the same scenarios and content. Hold wording and decision coverage constant
   where possible; separate savings from removing product decisions from savings due to grouping.
5. Present the specimens, measurements, coverage failures and recommendation together. Ask the owner to
   select the structure and acceptable per-session index cost, or retain/defer the trial. Do not call a
   proposal owner-approved because a test passed or a previous review endorsed the general direction.

## Alternatives to compare

| Option | Question to resolve with evidence |
|---|---|
| Flat meta-decision index | Is filtering to meta decisions already small enough to avoid another hierarchy? |
| Four lenses first | Can sessions discover applicable decisions while reading fewer entries, including cross-lens rules? |
| Hierarchical split | Does a short root plus selected child indexes save tokens after navigation and overlap are counted? |
| Domain split | Can a change crossing product areas find shared working rules without duplicated decisions? |
| Stage split | Does grouping by when a decision applies help discovery? Use ordinary documentation grouping; no new factory execution entity. |
| Point-of-view split | Do actor/reader views improve selection enough to justify their navigation and upkeep cost? |

These are comparisons to put before the owner, not a proposed new taxonomy to install. Prefer the smallest
structure that meets the owner's reading needs. A count of twenty is a concern to investigate, not an accepted cap.

## Measurement protocol

Retain the exact UTF-8 index specimens, candidate set, repository revision, selected paths and ordering for
each scenario. Specify whether a specimen is the real current inventory or a constructed trial index;
the complete historical file inventory is not automatically a mandatory per-session ADR read.

For every scenario and option report:

- Root/navigation index tokens, selected child-index tokens, total index tokens and index files read.
  Include repeated navigation text actually read; do not report only the smallest leaf.
- Additional decision-body tokens separately, alongside the required decisions found or missed. Selecting
  fewer index entries is insufficient if the session loses applicable rules or must read every ADR body.
- Tokenizer identity/version and counting command or callable, input file paths and content digests.
  Use the tokenizer for the evaluated session model where available; compare options with the same one.
  If unavailable, label byte/character counts as estimates and leave measured-token acceptance pending.

Report each scenario, the worst case and the read-all case. If a mean is useful, state the scenario weights;
do not imply measured traffic from invented frequencies. Do not use prototype `chars/4` figures or total
document tokens as measured per-session index cost. Recount changed specimens before seeking approval.
No new project dependency or factory instrumentation is needed for this documentation trial.

## Owner decision and completion

Completion requires an explicit owner choice linked from the task tracker and `decision.md`: selected
structure, where each meta decision lives, discovery/read conditions, living-record update convention,
and accepted measured per-session index cost with its model/tokenizer and scenario scope. Record any
budget the owner chooses; do not invent a numeric threshold. A deferral or rejected trial remains open
work rather than an approved structure. Any requirement change belongs on the task or its linked design.

Before seeking that decision, verify every trial index target resolves, every candidate has one owner,
applicable decisions remain discoverable, the same inputs reproduce the counts, and product decisions
and prototype specimens are clearly distinguished from adopted meta decisions. Preserve a source mapping
for `.119` rather than silently deleting or reclassifying live records.

This planning step is complete when this plan is reviewable; it does not satisfy the eventual owner-approved
structure acceptance. There is no runtime test change. For the documentation experiment, use focused link,
coverage and measurement checks, without adding a documentation test framework. If a later adoption task
changes code, first read the then-current justfile, install the declared successor package, run `just check`
and the authorized focused `just test` gates, and avoid whole-suite/live tests.
