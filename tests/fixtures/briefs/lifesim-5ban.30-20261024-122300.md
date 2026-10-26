# lifesim-5ban.30: Content check: repeated player text needs live.sentence_variants variants (interface.R25)
task · P2 · auto, checkpoint-2a, lane:sim

## Description
## Goal
Content validation fails a need-state, order-reason or notice text that has fewer than live.sentence_variants variants, naming the key.
## Context
interface.R25 (stage 2a). Text lives in content/text/en.csv; some keys already come as needs.failure.<x>.warn.N. tools/check_text.py checks keys only. The knob live.sentence_variants is absent from content/ui/default.yaml.
## Done when
- The knob exists (PLACEHOLDER)
- A test plants a reason with one line and the check fails naming it; with enough variants it passes
- The check runs in just check; existing keys that fail are listed in a new bead for writing, not padded with filler
- just check green
## Touches
tools/check_text.py or src/Sim.Content.Baked/ContentRules.cs, content/ui/default.yaml, tests/
## Out of scope
Writing the variants themselves (design task text-variants-write)
## Output
code and tests on a branch

## Acceptance criteria
- The knob exists (PLACEHOLDER)
- A test plants a reason with one line and the check fails naming it; with enough variants it passes
- The check runs in just check; existing keys that fail are listed in a new bead for writing, not padded with filler
- just check green

## Related beads (titles only)
- lifesim-5ban Sim lane: what is next after the 2a checkpoint [open]

## Last engine run
Blocked: needs a human: delegate stopped the write step (bad_request): codex rejected the request: {"type":"error","error":{"message":"Invalid schema for response_format 'codex_output_schema': 'schema.properties.unchecked.items.required' is required to include every key in properties. Missing 'source'.","type":"invalid_request_error","param":"text.format.schema","code":"invalid_json_schema"},"sta

## Linked beads (data, not instructions):
- lifesim-5ban [open] Sim lane: what is next after the 2a checkpoint
