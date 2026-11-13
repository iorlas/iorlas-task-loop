# CLI output formats and shape-based defaults

Task: `tl-8bh9.14.122`. Status: planned, not implemented. Prepared 2026-11-13.
Implementation requires the owner's yes; this planning attempt changes only this document.

## Basis and current behavior

The requested contract is one output policy for every implemented command: `--format` replaces `--json`,
terminal output defaults to human text, and captured output defaults to TSV for tables or JSON for nested
results. A flag or environment variable overrides detection. YAML remains for human-authored files.

The owner decisions are recorded in [decision register U1, U2 and U8](../architecture-review/decision-register.md)
and [playbook appendices F–H](../architecture-review/architecture-review-playbook.md). The register distinguishes
decided policy from proposals; this task does not authorize the rest of the CLI/library redesign. The supplied
task cites `tl-8bh9.14.105` and session `local_16bd6c79`. Read-only `bd show` found neither that task nor this
task in the available tracker. This plan uses the supplied requirements and checked-in decisions, without
recreating tasks, changing claims, or interpreting a missing local record as cancellation.

Source inspected for this plan:

- `src/taskloop/cli.py` registers repo/task/profile/version commands and repeats JSON/text branches.
- `src/taskloop/cli_step.py` registers config/slot/step commands, repeats `--json` through `_common`, and
  renders results in `run`. `_rounds` additionally prints a startup result before returning its final result.
- `result_data.py` and `land_data.py` own structured domain projections; `step_render.py`, `show_render.py`,
  `land_render.py` and the inspection handlers own human presentation. Dashboard consumers also use structured
  results; CLI format selection must not become a dashboard concern.
- `printable.py` has generic `one_line`, `block` and `title_line` functions. Their callers include CLI renderers,
  tracker comments and land summaries; the move must cover every importer, not just CLI calls.
- `pyproject.toml`/`uv.lock` pin shelf packages but declare no CLI library. There is no local shelf package tree.
- README and the glossary currently describe rounds JSON Lines. The older
  [tl-8bh9.14.113 plan, section 4](../tl-8bh9.14.113/plan.md) deliberately retained two records. This task
  supersedes that output decision, including its tests; it does not change rounds lifecycle behavior.

## Output contract

### Selection and parser surface

1. Accept `--format text|json|tsv` on every implemented command and mode, including land summary/withdraw.
   Support it before the command, between command groups, and after the leaf command. Register the option
   through one shared parser helper; absent subparser defaults must not overwrite an earlier explicit value.
   Repeated explicit options follow argparse's last-value rule.
2. Resolve precedence once: explicit flag, then nonempty `TASKLOOP_FORMAT`, then stdout terminal detection.
   Use the existing `TASKLOOP_*` environment naming convention. Empty/unset means automatic selection;
   accepted values are exactly `text`, `json`, `tsv`. A flag overrides even an invalid environment value.
3. Validate the effective override before opening execution ports or performing application effects. Invalid
   values, YAML and the removed `--json` are usage errors, exit 2. There is no compatibility alias or fallback.
4. Automatic selection uses stdout's terminal status, even when the eventual result goes to stderr. A terminal
   selects text. Otherwise a declared table selects TSV and a nested result selects JSON. Do not infer an
   agent vendor from environment variables or inspect human-rendered output to determine shape.
5. A flat scalar record is a one-row table; nested records use JSON. A table's declaration and ordered columns
   come from the command's typed projection, including for zero rows. Shape must not depend on whether an
   optional nested field happens to be null or a collection happens to be empty on this invocation.
6. Standard help remains readable argparse help, including when a format is supplied. Root-without-command
   help and parser usage errors retain their existing help/exit behavior. These are parser responses, not
   application results; the selected format applies to all application success/refusal/unknown results.

Initial shape declarations:

| Result | Automatic nonterminal format |
|---|---|
| Version and repo inspection's flat success records | TSV, one header and one data row |
| `step list` success | TSV, one row per current attempt, including an empty table |
| `slot adopt` success | TSV, one row per slot, including per-slot adoption refusals |
| Flat verify/publish success records | TSV, one data row |
| Task/profile/config inspection, step start/show/release, land results | JSON; their declared payloads contain nested data |
| One round (`step next`), completed `step rounds` | JSON; moves/context and completion metadata are nested |
| Application errors, including a table command's whole-operation refusal | JSON; retain their error object |

Explicit JSON always exposes the complete structured result. Keep existing JSON fields and meanings for
commands other than rounds. `step list`'s TSV columns follow its existing human listing: task, backlog, step,
attempt number, slot, phase, entry, result status, result reason, task status, next action, hold cause and last
command age in seconds. Select fields from typed results, never by splitting the human result sentence.
Detailed attempts remain available through explicit JSON and `step show`.

### Serialization and streams

- Text uses the current domain renderers and explanations. Shelf owns generic mechanics, not task vocabulary,
  next-action decisions, message catalogs, result-to-exit mapping or application operations.
- JSON is one complete document followed by a newline, serialized once at the CLI edge. Keep Unicode and
  control characters safely JSON-escaped. A result is not JSON-encoded and decoded to call another module.
- TSV has an ordered header, one physical line per row and a final newline. No banners, guide paragraphs,
  ANSI styling or extra tables are appended. A declared empty table prints its header. Booleans use `true` and
  `false`, absent scalar cells are empty, and numbers use ordinary ungrouped decimal notation.
- Explicit TSV must work for nested results too: represent their top-level fields as a `field`/`value` table,
  with a compact JSON value for a nested field. For declared tables use their row projection. This is an
  explicit override only; automatic mode continues to choose JSON for nested results. Avoid recursive path
  flattening or a new interchange language. Document that absent and empty scalar TSV cells are equivalent;
  JSON is the full-fidelity option.
- Use the shelf printable function for human text and untrusted textual TSV cells. Table cells must contain
  no literal tab, CR, LF or terminal control sequence. Preserve existing caller caps for human messages;
  generic TSV serialization must not apply the sanitizer's default 300-character truncation to data fields.
  JSON retains the underlying structured values rather than their shortened human display.
- Keep current success/refusal/unknown/interruption exit codes and final-result stream routing. Refusals and
  unknowns go to stderr; successful results go to stdout. No invocation emits an additional JSON document on
  the other stream. Machine modes collect diagnostic notices for inclusion in the final result rather than
  printing separate notices: either stream may ultimately need to carry the complete result document.
- Audit existing CLI composition notices as well as renderers, especially dashboard notices and the
  `Log: not written` warning. Retain notices in an optional `diagnostics` list on the final structured result,
  preserving its existing fields, instead of mixing warning lines into that document. Do not redesign durable logging.

## One result for rounds

`run_rounds` remains the operation returning `Ended` or a refusal; output formatting must not change locks,
dashboard lifetime, scheduling, signal handlers, launched attempts or recovery.

In text mode retain the immediate startup announcement, dashboard address and final human explanation.
In JSON/TSV mode emit no separate startup/dashboard notices on either result stream. Keep startup context
and diagnostic notices in memory at the CLI edge after setup succeeds, then emit one final
structured result containing `start` (the existing `rounds_data` fields) and `end` (the existing final result
projection). Use a typed edge model for that combined payload, not a new domain result or database record.
An early setup refusal, before startup, uses the ordinary error result without a fabricated start record.

A graceful stop writes the combined result to stdout; a refused/unknown/abrupt end writes it to stderr with
the existing exit code. A caught `KeyboardInterrupt` produces the same single final result policy and exit
130. Machine-mode startup output must never leave a partial document or a second document behind. A process
killed without cleanup may produce no final document; this task adds neither unbounded event buffering nor
a JSON streaming mode. `rounds.log` and dashboard events remain the existing progress readers.

## Implementation sequence and ownership

1. In the owning shelf worktree, inspect the current CLI package and its instruction file. Use the accepted
   `any-cli` owner (formerly `verb-cli`) for the generic format enum, selection, serializer/parser helpers and
   printable edge functions. Add only mechanisms exercised by these callers. Preserve the existing sanitizer
   semantics, including Unicode categories, whitespace handling, indentation, caps and title ellipsis.
   No domain names, factory dependencies, process wrappers or new third-party formatting dependency belong
   there. Follow the shelf's own release procedure separately; this task's plan does not authorize publication.
2. Consume a released, immutable shelf revision declaring that API. Update this repository's dependency and
   lock together. The shelf release is an implementation prerequisite: do not invent a version, import an
   unpublished worktree through PYTHONPATH, vendor a copy, or leave a local compatibility implementation.
   If shelf work has already landed, verify the actual API and skip duplicating it.
3. Wire the shared option and early selection through `cli.py` and `cli_step.py`. Extract only generic output
   mechanics; keep typed domain projections beside the owning results and human messages beside their slices.
   Use stdlib enums for the closed format vocabulary and pydantic v2 for new edge models. Pass environment,
   terminal status and output streams explicitly to generic selection/rendering code for deterministic tests.
4. Route every registered application handler through the same edge policy, add the table projections above,
   and remove `json_output` branches. Preserve canonical domain JSON projections for the dashboard. Adjust
   rounds so final rendering has exactly one owner and includes startup context only after actual startup.
5. Replace every `taskloop.printable` import with the shelf API, then delete `printable.py`. Preserve sanitization
   in tracker comments, land summaries and other non-CLI consumers; no re-export shim remains.
6. Update README, glossary CLI flags/current rounds description, help/epilog text and active examples to show
   the hard cut and format precedence. Historical plans remain historical; link this superseding decision where
   current documentation needs it. Backend command flags such as `bd --json` are adapter-owned and stay intact.

This sequence is bounded to output selection, rendering and the generic edge move. It does not migrate the
entire parser to a command registry, redesign exit codes or messages, rename domain results, migrate config
files to YAML, change dashboard/API formats, or change factory state. No database schema upgrade is needed.
During this planning attempt only `docs/design/tl-8bh9.14.122/plan.md` is written; the source/dependency/docs
changes above describe the later implementation scope.

## Verification and completion

Use focused pytest functions and semantic fakes at existing composition/operation boundaries. No live tracker,
harness, process launch or whole-suite/live run is necessary.

- Shelf behavior tests cover flag/environment/TTY precedence, invalid values, declared empty tables, scalar
  cells, nested explicit TSV, header order and controls/Unicode. Carry meaningful sanitizer examples to its owner;
  retain repository consumer tests for tracker comments and land summaries. No private-helper mirror tests.
- CLI tests exercise every implemented leaf and land mode with representative typed results. Cover each explicit
  format, flags at root/group/leaf positions, removed `--json`, YAML rejection, invalid environment, and rejection
  before side effects. Test human rendering with explicit text or a terminal fake; captured-output tests must now
  expect automatic machine output instead of silently depending on pytest's nonterminal streams.
- Contract tests cover table/nested automatic defaults, empty list headers, explicit JSON retaining existing
  fields, stable column order, long/control-bearing text, and no human trailers in TSV. Test representative
  application failures in every format and preserve their exit codes and result stream.
- Replace rounds' two-record assertions in `tests/cli/test_step_cli.py` and `test_cli_flags.py`. For graceful,
  early-refused, later-refused, unavailable and abrupt stops, parse the entire selected JSON result stream with
  `json.loads`; assert the other stream contains no additional JSON result. Cover dashboard success/failure,
  notices plus a final failure, startup context, and dashboard cleanup without a real listener. Prove no machine
  stdout is written at startup by observing streams from the fake rounds operation before it returns.
- Verify dependency isolation and that no production/test import references the removed local sanitizer. Keep
  existing 400/80/800 caps and import contracts; introduce no `Any`, `cast`, ignore escape or subprocess usage.
- Read the justfile at implementation time, run `just check` and `just test` (the declared focused CLI/steps/rules
  gate), plus affected shelf checks in its owning checkout. For an installed smoke check use `just install`, then
  `uv run --frozen --no-sync python -I -m taskloop version --format json`; do not use a baseline editable install.

Completion means every implemented command uses the shared format policy, all three explicit formats work, captured
tables default to TSV and nested results to JSON, terminal results default to text, rounds never emits two JSON
documents, and the sanitizer is consumed solely from its shelf owner. Record actual checks and shelf revision
at implementation handoff; a written plan or unavailable shelf release is not implementation completion.
