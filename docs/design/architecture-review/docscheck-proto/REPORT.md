# docscheck prototype - report

Scratchpad only: `.../scratchpad/proto/`. Nothing in the repo, shelf or a2kay. No commits.

## Result
Built and run. 24 pytest functions pass. Full run on 15 real-derived docs against this repo: **17 active findings, 4 waived, exit 1**.
`ontology/` (27 kinds) passes a2kay's META_SCHEMA and `field_types.parse` (`scripts/verify_ontology.py`).

## What was built (src/docscheck, 18 files, longest 122 code lines; caps 400/80/800 held, no Any/cast/ignore; my own AST count, ruff/pyrefly not run: not available offline)
| file | job |
|---|---|
| ontology.py, schema.py | a2kay kind YAML -> typed fields -> JSON Schema 2020-12 (inline rows, enums, links, sets, maxLength) |
| docs.py | find docs by `file_pattern`, `any_frontmatter.read`, schema check, walk rows/links, `any_markdown` wikilinks in every string and body |
| index.py | id index (docs, global rows, owner rows, repo tests/contracts as `check/*`), dangling + wrong-kind + nearest-name, `task/<id>` by pattern |
| rules_docs.py | hedge words, case-table completeness/dups, lifecycle (declared states, exits, reachability, process-death+restart rows), workflow step events |
| rules_code.py, code_read.py, probes.py | owns globs match files, path/symbol resolve (ast, never import), limit value vs code constant, lifecycle states vs code (`Literal`/enum or SQL `CHECK(col IN ...)`) and vs the values the code writes, rule probes, test markers |
| waivers.py | named waiver = finding key + task; a waiver matching nothing is a finding (shrink-only) |
| changed.py, gitport.py, cli.py | changed-only scope, reverse refs, skip before heavy imports |
| generate.py | deterministic per-tier index and graph |
Not used: pydantic (jsonschema + dataclasses were enough). Shelf libs used: any-frontmatter, any-markdown, any-path-glob (found in passing; fits `owns` globs).

## Run
```
proto/run.sh check            # changed only (git merge-base vs --base main); "skipped" when nothing relevant changed
proto/run.sh check --all      # full; never automatic
proto/run.sh check --all --keys   # prints each finding's waiver key
proto/run.sh generate         # index + graph to stdout
```
Uses a2kay's venv python (3.12) with shelf `src` dirs on PYTHONPATH (no `-I`: it drops PYTHONPATH). Tests: `PYTHONPATH=src:tests:<shelf libs> python -m pytest tests`.

## Measurements (this machine, median of 15 runs)
| mode | time |
|---|---|
| nothing changed (skip, bare python is 13 ms) | **87 ms** |
| changed, 1 doc -> 6 of 15 rechecked (git port 37 ms) | 484 ms |
| `--all`, 15 docs against this repo | 873 ms (p90 2.2 s, noisy) |
Before two fixes the pass was 1.7 s: parsing every test and source file by `ast`. Now ids and probes read text; `tests_in` is cached. Docs themselves cost under 0.3 s. No cache is needed yet.

Size (chars/4): 15 docs = **3.9k tokens** total (storage 1064, glossary 879, engine 405, workflow 225, lifecycle 196). The round-28 prose sample of storage was 778 (it had less: no cases, outcomes with sources, limits, evidence). 24 glossary terms: 879 tok here vs 1898 for the same 21 matching rows in `docs/glossary.md` (36 vs 99 tok per term), at the price of the "Example / distinction" column. AGENTS.md is 1810 tok; its prose on storage/state is about 130 tok.

## Findings against the real code (checker-found)
17 active:
- **14** `sql-outside-store`: `admit`, `admit_chain`, `admit_rows`, `attempt_entry`, `attempt_loads`, `attempt_reads` (12 calls), `check_admit`, `composition`, `land`, `land_check`, `launch`, `publish`, `slot_release`, `slots` issue SQL outside a `*_store.py` module. Rule 1 as written is false today.
- **2** `one-writer-per-table` active: `attempt` (admit_rows, attempt_store), `slot` (admit_rows, slots). `reservation` (3 writers) is waived. The existing test `test_every_sql_write_has_its_one_owner` is linked as rule 2's check, but it maps (verb, table) -> module and allows 2+ modules per table: the check does not enforce the rule.
- **1** `limit-differs`: doc says writer-lock wait 5000 ms; `REGISTRATION_BUSY_MS` is 1500.
4 waived (task ids are placeholders `tl-unfiled-*`, not filed): StoreBusy, SchemaMismatch, Corrupt are target outcomes with no code symbol; reservation writers.
Checker-confirmed agreement: attempt phase states equal the SQL CHECK (`admitted, dispatching, registered, captured`) and the `UPDATE ... SET phase=` writes in `attempt_store.py` equal the declared transitions; owns globs, ports, symbols, 2 real import-linter contract ids and 3 real test names resolve.
Found by reading, not by the checker (unverified): (a) `attempt_status._stopped` returns `stuck:entry_lost` for dispatching/registered, so my `restart` rows for those phases (phase unchanged) describe the glossary's relaunch, not proven behavior; (b) today a mismatched DB is refused by words (`factory_schema.refusal`), nothing handles corruption, and no repair-agent path exists; (c) rule 7 (frozen strict models, no tuple indexing) is not true of code that passes `tuple` identities; no probe yet.
Also: 12 of 18 rules have neither a check nor a probe.

## Ontology changes (from scratchpad/ontology, 18 -> 27 kinds) and why
- Added doc kinds: `adr` (lens, statement <= 200, history rows), `runbook` (trial), `waivers` (trial).
- Added rows: `case_table` (declares states so completeness is checkable), `evidence` (artifact, path, writer, readers), `command` (trial: one command table), `change`, `runstep`, `waiver`.
- `lifecycle`: `initial` + `terminal` replace a2kay `classes`; `source` accepts `path::Symbol` or `path::sql:table.column`.
- `rule.probe` (named code probe: mutation-style truth check) and `outcome.source`, `limit.value`, `operation.source`.
- Extensions on top of a2kay keys (a2kay passes unknown keys; replace with its id config later): kind `scope` (global/owner), `keys`, `derived`; field flags `rigid`, `path`, `glob`, `symbol`, `max`.
- `check` is a derived kind: declared by repo tests/contracts, never by a doc.
- Rows are a2kay inline kinds: flow YAML in frontmatter, no table parser; 6% bigger than the markdown table.
Trials to cut first if the owner wants fewer: `command`, `runbook`, `waivers`, `evidence`.

## What did NOT work / limits
- Module named `types.py` shadowed the stdlib; renamed `values.py`.
- Banned-word lint hits scope words, correctly (`except` in a scope is an exception list in disguise); it also forces rewriting every real glossary definition that says "can/may".
- The reverse closure is one hop; code changes only map to docs through `owns`, path/symbol fields and check sources.
- The changed-only gate treats any change under repo `src/` or `tests/` as "run" (a full parse then finds 0 affected docs).
- `markers` (tests naming a rule) is tested only on a fixture: the real repo has no `@pytest.mark.rule`.
- Probes read source as text (regex) for speed; they are code reads, not workflow control.
- Runs on Python 3.12 (a2kay venv), not the repo's 3.15.
- Placeholder task ids in waivers and `not_designed` are not real tasks.

## Top risks
1. **Probes become the real spec.** Each probe is hand-written code beside the doc; too many and the checker is a second policy test suite (the repo already caps those).
2. **Target docs fail until built.** A doc stating target design (storage rules 1-2, outcomes) is red against today's code; waivers fix the noise but need real tasks, or they rot.
3. **Cost of rigid prose.** Rewriting definitions without can/may/except shrinks tokens 2.4x but drops the distinction column; judge on a sample of the real glossary before cutting.
