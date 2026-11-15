# Folder privacy and SQLite ownership

Status: accepted owner decisions, enforced with exact migration exceptions.

Python feature folders define slice boundaries through two levels below `src/taskloop`.
Private modules have native protected contracts; `api.py` is public. Flat modules and
static-only folders do not define slices. Initializers cannot re-export internals.
Nested folders have independent boundaries, including against their parent folder.

Only literal `store.py` modules own direct SQLite imports, including connection types,
aliases and type-only imports. Suffixed stores remain migration exceptions. Indirect
access through stores is permitted. The current source tree has 228 modules and 34
noncanonical SQLite importers: completed SQL extraction left connection annotations
and error handling imports. Each surviving edge is listed explicitly, without moving
runtime code or weakening the delivered SQL-execution policy.

`tools/generate_import_contracts.py` prints deterministic `.importlinter` configuration
from the folder tree. Refresh the generated block after module changes. Generation
preserves reviewed exceptions and unrelated configuration; it never infers permissions
from violations. File-reading tests check freshness and independently verify complete
module coverage. Import Linter runs only through the existing pinned `just check` gate;
no checker dependency or pytest subprocess is introduced.

Exceptions follow [the ratchet decision](../tl-8bh9.14.98/adr-ratchet.md): exact edges,
strict unmatched-ignore errors and a paired ceiling that only shrinks. Protected
contracts use `unmatched_ignore_imports_alerting`; forbidden contracts use
`unmatched_ignore_alerting`. Remove a resolved SQLite edge, ceiling entry and Ruff
permission together. Generation leaves exception removal to the author.

Ruff bans `sqlite3` globally. Exact source-file permissions cover literal stores and
reviewed exception importers. Test fixtures have a separate `tests/**` permission.
AST checks enforce every other banned API in all exempt files so TID251 permissions
cannot permit process mechanisms.

Executable references are `tests/rules/test_slice_contracts.py` for tree freshness,
nested privacy, initializer bypasses and exception preservation;
`tests/rules/test_sqlite_contracts.py` for complete coverage and exact Ruff permissions;
`tests/rules/test_ratchet.py` for shrinking ceilings; and
`tests/rules/test_attempt_sql_ownership.py` for retained SQL-execution ownership.
