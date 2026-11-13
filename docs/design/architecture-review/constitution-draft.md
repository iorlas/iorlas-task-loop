# Draft: additions for CLAUDE.md and AGENTS.md (mirror both)

Place under "Architecture and design". Wording follows the file's terse bullet style.

- Names: a new term borrows GitHub's word first; otherwise it chains defined terms (retry attempt, check suite). Before a term enters the glossary or the code, put the options and the reasons to a human and wait for the decision. Delete a term that is plain English or derivable from defined terms.
- Closed vocabularies (outcomes, phases, reasons, step and check names) are enums or classes, never string literals. A string appears only at the edge that stores or prints it, through one codec per vocabulary.
- A backend's (task tracker, Git, harness) tool names, commands, error text and types stay inside its adapter. The factory's outcome types and messages are generic; the adapter supplies the explanation per outcome. A missing explanation fails a test.
- Models at the edges (database rows, agent answers, configuration) are pydantic v2 models. Enums stay stdlib. Adding another third-party library needs a stated reason that tests get smaller, not larger.
- A schema-changing upgrade drains running attempts first: the old entry processes cannot write to the new schema, and the old database is discarded.

- External actions (Git, tracker, process spawn) follow transactional outbox with reconciliation: a short transaction records the intent, the action runs outside any write transaction and is idempotent or observable, a second short transaction records the result; after a crash, reconciliation asks the world (does the ref exist, is the claim ours) and finishes or releases. No compensation chains; adopt what already happened. No new glossary term.
- Layout is vertical: one folder per feature, one module per use case (a transition with a typed outcome). A store or service module exists only where it hides something (deletion test). Only a slice's own store touches its tables; SQL and `sqlite3.Connection` never leave the store modules. One composition root per process.
- Test impact is a design goal: a use case's test imports only its slice and the small shared kernel, so a change runs only the tests its import closure reaches.
