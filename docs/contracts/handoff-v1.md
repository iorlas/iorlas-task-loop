# handoff v1: what a session that lost its context is given

One Markdown file per repo, made from the stores (never by a model), written by `tl handoff write` and by the PreCompact hook,
read back by `tl handoff show` and by the SessionStart hook after a compaction. Everything here is read from the code
(`src/taskloop/app/wire/handoff.py`, `src/taskloop/domain/brief.py`, `src/taskloop/app/wire/brief.py`).

## Where

`<config>/handoff/<repo key>.md`, `<config>` = `$XDG_CONFIG_HOME/task-loop` or `~/.config/task-loop`
(`ConfigDir.handoff`). `<repo key>` = `<main checkout folder name>-<first 8 hex of sha1 of its path>` (`contracts.ids.loop_key`).
A worktree or slot shares the file of its main checkout (`app/wire/hook.main_checkout`). One file, rewritten whole:
the writer makes `<file>.<pid>.tmp` beside it and `os.replace`s it, so a reader never sees half a file.

## Format

UTF-8 text, newline-terminated, at most 4096 bytes (`HANDOFF_BYTES`). No version field and no front matter; "v1" names this layout.
In order:

| lines | content | field |
|---|---|---|
| `# task-loop handoff of MM-DD HH:MM` | local time of the write | `Brief.now` |
| blank | | |
| `loop RUNNING (N) on <repo>, last activity <ago>` or `loop NOT RUNNING on <repo>, last activity <ago>[ (exit: <reason>)]` | `<ago>` is `never`, `N min ago`, `N h ago` (from 120 min) or `N d ago` (from 48 h) | `loops`, `last_beat`, `last_exit` |
| `standing rules:` then 6 lines `- <rule>` | the fixed `RULES` tuple (worktree, release only through dev/release.py, no pkill, quoted approval, fork limit, bd through tl) | constant |
| blank | | |
| one line per live loop: `  pid P since MM-DD HH:MM: <bead> in <slot or "its worktree"> \| between beads; task-loop <version>` | | `loops` |
| `versions: running V, newest installed V, pin P` | `?` when unknown, `none` for no pin | `version`, `installed`, `pinned` |
| `asks: N open` then `  <bead> [<kind>] <decision, first 90 chars> (<ago>)` per ask | live asks of this repo (or of no repo) | `asks` |
| `slots:` then `  <slot>: free \| claimed by X \| held by X` | only when slots were read | `slots` |
| `recent beads:` then `  <bead> <outcome> (<minutes> min)` | the last 5 rows of the repo's loop log | `recent` |

When the lines exceed 4096 bytes, the first lines that fit are kept and the last line is `... N more line(s)`; the status line and
the standing rules come first, so they are never the part cut.

## Who writes it

- `tl handoff write [--repo DIR]` (`cli/status.run_handoff`): prints the path. Reads slots from bd (one subprocess).
- PreCompact hook (`hook/session.precompact`, `hooks.json`, timeout 10 s): writes the file for the repo of the event's `cwd`, with
  no slots section (a bd call is too slow for the hook). Any failure is swallowed; the hook prints nothing and exits 0.

## Who reads it

- `tl handoff show [--repo DIR]`: prints the file; exit 1 and one line when there is none.
- SessionStart hook (`hook/session.start`): only when the event's `source` is `compact`, it prints
  `{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": <file text>}}`. A fresh start, resume or clear gets
  nothing. No file or a failure: nothing is added.

No reader parses the text: it is handed on verbatim as context for a model.

## Version 1 compatibility

The code has no compatibility machinery: no version marker, no parser, and the file is regenerated at every write, so a reader
never meets an older file's layout for long. Within v1 a change may add or reword lines and change `RULES`; it must keep the
first line (title), the status line and the `standing rules:` block first, the 4096-byte cap, the one file per repo key and the
atomic replace. A change that moves the path, the key or the file's content type is a new contract version.
