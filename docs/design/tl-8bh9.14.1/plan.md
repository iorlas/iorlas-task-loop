# tl-8bh9.14.1: the repository profile reader (block B3)

Status: **built** for this bounded successor slice. See [the as-built record](#7-as-built). The dated proposal and preparation statements below
are historical; they do not describe current availability. Historical `tl plan` commands were superseded by
`tl step`; use the current [README](../../../README.md) and CLI help for command syntax.

Block B3 of the [self-hosting roadmap](../self-hosting-roadmap.md): one reader and validator of a minimal repository
profile `.task-loop.json`, read from Git at a commit, and one read-only command that prints it. B2 (setup), B4 (checks)
and B6 (land target) will consume it; this slice runs nothing the profile names. Vocabulary: [glossary](../../glossary.md)
(profile, setup, check, required checks).

## 1. Schema (hard cut)

The baseline `engine` keys have no reader; the file in this tree is replaced with the new schema in the same change.

| Key | Value | When absent |
|---|---|---|
| `setup` | ordered list of argv lists, at most 32; `[]` means no setup | `[["just", "install"]]` |
| `checks` | list of at most 32 objects with exactly `name` (`[A-Za-z0-9._-]`, not starting with `.` or `-`, at most 64 characters), `argv` (1 to 64 non-empty printable strings: no control character, surrogate or NUL, so no tab or newline either; the program not blank; each at most 4096 characters) and `timeout` (whole seconds, 1 to 86400); names unique | `[]` |
| `required` | list of distinct check names (the same name rule), at most 32 | `[]` |
| `target` | the land branch, at most 255 characters, by `git check-ref-format` rules: no leading `-` or `/`, no `..`, `//`, `@{`, trailing `/` or `.`, no component starting `.` or ending `.lock`, none of ``~^:?*[\`` or whitespace or control characters | `"main"` |

The file is a JSON object of at most 64 KiB; any other key, at the top or in a check, is refused. A repeated JSON object
key and `NaN`/`Infinity` are not JSON here (the text is ambiguous or not portable).

## 2. Refusals and results

`profile.read_profile(files, commit) -> Profile | Refused | Unavailable` and
`profile.resolve(files, commit, target_ref) -> Resolved | Refused | Unavailable`. `Refused` carries a fixed reason word,
the offending key path (`checks[1].timeout`), a detail and the side (`commit` or `target`) whose profile it is.

| Reason | Meaning |
|---|---|
| `missing` | The commit has no `.task-loop.json`. There is no default profile: defaults apply only to keys absent from a profile that exists. |
| `no_commit` | The revision names no commit (or looks like an option). |
| `not_json` | Not UTF-8 JSON, a repeated object key, or `NaN`/`Infinity`. |
| `not_object` | Valid JSON that is not an object. |
| `unknown_key` | A key outside the schema, top level or in a check. |
| `bad_value` | A wrong type, an empty or blank argv item, a control character or surrogate in an argv item, a bad check name or target branch, a timeout outside 1..86400, a check missing a key, a repeated required name. |
| `too_large` | Over a bound: the file, a list's length, an argument or name's length. |
| `not_a_file` | `.task-loop.json` is a symlink (mode 120000), submodule (160000) or other non-regular tree entry at the commit; exit 1. |
| `duplicate_check` | Two checks share a name. |
| `required_undefined` | A required name the checks do not define: the target's own checks first, then the commit's. |

Refusal details never carry raw control characters: an unknown key or a revision is shown as is when short printable ASCII, else escaped and cut to 64 characters.

`Unavailable` means Git could not be read (no repository, a failed read): no verdict, reading again is safe.

## 3. Version rule (D11)

GitHub's model, as the roadmap's section 7 reads it: `setup` and `checks` come from the profile at the commit under test
(a `push`/`pull_request` workflow at its commit); `required` and `target` from the target ref's profile (branch
protection), so a commit cannot drop a required check (O1, an inference awaiting the owner's confirmation; built this
way). A required name the commit's checks do not define is `required_undefined`, as a required GitHub check that never
reports blocks the merge. Every read is of a Git object, never a working tree.

State enters through one port, `ProfileFiles.blob(commit, path) -> bytes | NoCommit | NotAFile | Unavailable | None`. The real
adapter, `composition.GitProfileFiles`, opens the hardened `checkouts` view and reads
`Repo.tree(f"{commit}^{{commit}}")`: its listing decides absence (`None`), then `Tree.read(path)` (`git cat-file blob`)
gives the bytes, but only for a regular-file entry (mode 100644 or 100755), else `NotAFile`; a listed file that cannot be read is unavailable, not missing. When the revision resolves to nothing,
`Repo.identity()` tells a missing commit (`NoCommit`) from a path that is no repository (`Unavailable`).

## 4. CLI

`tl profile show [--checkout PATH] [--at REV] [--target REF] [--json]` (defaults `.`, `HEAD`, `main`) prints the resolved
profile: human lines, or one JSON object `{at, target_ref, setup, checks, required, target}`. A refusal goes to stderr
(`tl profile show: refused <reason> (<side>[, <key>]): <detail>`, or `{"error": {kind, side, key, message}}`) with exit 1;
Git unavailable with exit 3, like the step commands' unknown.

## 5. Deliberately not done

- No execution of checks (B4) or of setup (B2, slice S5e); nothing stores a profile digest yet.
- No protected-file gate: B6's land summary is to list changed check configuration for the person instead.
- No reader for the baseline keys, no fallback to the working tree, no default profile for a commit without the file.
- The profile is not cached or written to factory.db.

## 6. Known limits and follow-ups (not implemented)

- The 64 KiB bound is enforced after the blob is read; a hostile multi-GB blob is loaded first. It needs a size check
  before the read (`ls-tree -l` or `cat-file -s` through git_porcelain): a shelf follow-up (the tl-8bh9.14.2 area).
- `--checkout .` works only at the checkout root, because the hardened discovery ceiling is the given path.
- `Resolved` does not record the shas it read; B4 must resolve both refs to shas once and pass the shas on.
- Nothing checks that the target profile's own `target` equals the ref it was read from.
- When both profiles are broken, the commit's refusal masks the target's.
- Bootstrap: until the new profile file is on `main`, the target side refuses `unknown_key` (the old `engine` file).

## 7. As built

| File | Code lines |
|---|---|
| `src/taskloop/profile.py` (new: schema, refusals, `read_profile`, `resolve`, the port) | 171 |
| `src/taskloop/composition.py` (`GitProfileFiles`) | 252 -> 272 |
| `src/taskloop/cli.py` (`tl profile show`) | 99 -> 140 |
| `tests/steps/test_profile.py` (new: 52 tests: refusal table, bounds, version rule over a port fake, adapter over the Git fake) | 164 |
| `tests/cli/test_profile_cli.py` (new: 3 tests: lines, JSON, exit 1 and 3) | 55 |
| `tests/steps/real/test_profile_real.py` (new: 1 test: the commit's value after the working tree is edited) | 27 |

`.importlinter` gains the contract `profile-is-domain` (the reader imports no command surface, composition, store or Git
library). `.task-loop.json` holds this repository's profile: setup `just install`; checks `check` (`just check`) and
`test` (`just test`), 1800 s each, both required; target `main`. Gates: `just check` (ruff, pyrefly, 8 import contracts
kept) and `just test` (1376 passed after the repair; 1323 and 56 new at the first commit) pass.
