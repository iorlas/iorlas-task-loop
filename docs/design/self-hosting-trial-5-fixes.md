# Trial 5 fixes: environment, evidence, settlement (tl-8bh9.14.44-.53)

Decisions the owner may revisit. Each names the simplest safe default taken and the alternative.

## Agent and checks environment (.49)
`agent_credentials.scrubbed` is an allow-list: PATH, HOME, USER, LOGNAME, SHELL, LANG, LANGUAGE, `LC_*`, TERM, TZ, TMPDIR,
CODEX_HOME, the HTTP(S)/ALL/NO proxy names and SSL_CERT_FILE/DIR. Everything else is dropped, including every `GIT_CONFIG_*`
(the factory adds its own push bar). The person extends it by name in the factory's own environment:
`TASKLOOP_ENV_PASS=UV_INDEX_URL,REDIS_URL`. Alternative: a machine-config key; not taken (a new typed key and a reader for
one rarely used list). Proxy URLs can carry credentials; they stay because the agent's network is off and checks need them.

## Output cap (.45)
Stored `stdout.txt` / `stderr.txt` are capped at `LOG_CAP` (32 MiB) with one `[truncated]` line. The harness (`any-agent`
supervisor) still holds the whole stream in memory until it returns: bounding that needs an `any-agent` change (cap in
`_pump` while the summary parser keeps the tail). Open owner decision: do it in the shelf, or accept the memory bound.

## Settlement refusals (.46 .47 .48)
Unreadable listed file: `unsafe` naming the path (it joins repeat feedback). `unsafe` also lists the unlisted leftovers
beside the first path. `slot_dirty` (release, hold comment, guide) names `git -C <slot> status --short`; the factory still
resets nothing. `head_moved` lists tags and branches made beside the moved HEAD and the guide names
`release --abandon`, then `start`.

## Shared git state (.53)
Commits in a slot carry the factory's identity (`task-loop <task-loop@localhost>`) through environment variables, so the
agent-set `user.email` no longer becomes the author. Task commits were authored by the person's Git identity before: owner
impact. Not done: a snapshot of the shared git config and hooks at admission compared at verify. It needs a stored
snapshot (factory.db column) and a rule for what the person may change meanwhile. The sandbox blocks those writes (the
trial confirmed it); open owner decision whether the defence in depth is worth the column.

## Existing branches (.52)
`branch_unpublished` refuses admission when a local `task/<id>` has commits origin (else `main`) lacks that carry no
attempt trailer: the person's work. An abandoned attempt's own unpublished commit still resumes. A publish rejected for a
ref name collision names the colliding remote refs.

## Credentials in the sandbox (.50)
Not restricted: the harness sandbox allows reads of the whole file system (Codex `workspace-write`), and Codex itself needs
`auth.json`. Restricting reads needs Codex permission profiles with denied paths: a larger, version-specific change in
`any-agent` and an owner decision on scope. Taken instead (first acceptance option): verify refuses a listed file whose bytes
hold a PEM private key header or both Codex token names (`unsafe`, path named) so a copy is never committed or published.
Open owner decision: restrict sandbox reads of `~/.ssh`, `~/.codex`, the tracker db and factory.db through the shelf.

## Escaping processes (.44)
Not done. The stop proof checks the agent's process group only. A proof by "any process with cwd in the slot or session
begun inside the attempt" needs a cross-platform process-table field (cwd) that `stream_proc` does not expose (Linux
`/proc/<pid>/cwd`, macOS libproc); a Linux-only scan in the factory would silently pass on the owner's Mac. Open: add
`stream_proc.in_dir(path)` in the shelf, then refuse verify/release naming the pids.
