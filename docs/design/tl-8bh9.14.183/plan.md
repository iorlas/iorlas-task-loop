# Explain unsafe paths and omit unchanged files

Task: tl-8bh9.14.183. Source reviewed: c414d0ac84fbe15eea463e4fdbadb5a78f4399e9.

## Identified predicate

The failing predicate for `tests/steps/test_verifier.py` is the credential-content
check, `secret(data)`, called by `factory_commit.unsafe_path`. The last branch
rejects a file when its read fails **or `secret(data)` is true**. Neither of the
current unsafe openings mentions this predicate.

The source file contains these deliberately synthetic test fixtures:

- Line 224 contains a complete OpenSSH private-key header. It satisfies both
  byte-substring tests in `secret`'s private-key branch.
- Line 225 contains the quoted `access_token` and `refresh_token` field names.
  Together they satisfy `secret`'s login-token branch.

Thus both credential signatures match the test source itself. The file is
42,668 bytes, tracked as mode 100644, and clean at the reviewed source commit.
The fixtures also exist at lines 223–224 of the parent of saved-work landing
245821b2dbf68245cb9e8267846e4a690cffca9e, and remain in the landed file. This
source diagnosis agrees with the supervisor's unchanged-file and chmod evidence;
changing permissions cannot remove a content-signature match.

`refusal` currently passes every declared path to `unsafe_path`, without checking
whether its content differs from HEAD. It reduces every failure to one pathname.
`implement_step.feedback` then supplies the same five-alternative message for
every failure, including the unmentioned credential predicate.

## Intended behavior

1. Before applying commit-content restrictions or staging, omit listed tracked
   regular files whose raw bytes equal HEAD and whose file type and Git mode have
   not changed. During ordinary settlement HEAD equals the attempt's base; retain
   the existing moved-HEAD and crash-adoption checks before this comparison.
   Compare through the owning Git tree and slot-file ports, with bounded safe
   reads. Do not infer byte equality from display text or a clean status alone.
   An unchanged file can be omitted even if its existing content matches the
   credential detector or exceeds the commit size cap. A changed executable bit,
   symlink, directory component or unreadable file must not disappear through this
   rule. Additions and deletions remain changes.
2. Use that same effective path list for refusal checks, relevant attributes
   checks, staging and staged-path ownership checks. Preserve the stored answer
   as evidence and retain the existing verdict rule that actual committed changes
   must belong to the answer's declared paths. Read-only leftovers must use the
   same decision as settlement. If every listed file is omitted, retain
   `nothing_written` with no empty commit or staging of an empty path list.
3. For each unsafe path reported, carry exactly the predicate that failed, with a
   nonempty explanation supplied where the Git/file check runs. Collect all
   failing paths within the existing display bounds. Explain baseline type/mode
   changes, missing or non-directory components, symlinks, missing/non-plain files,
   execute bits, the actual byte limit, unreadable content, credential signatures,
   and changed Git files separately. Name an offending ancestor when applicable.
   Where several predicates fail, report the first in a deterministic check order.
   Never quote credential content in a diagnostic.
4. Render the supplied per-path explanations in plan and implement refusal/repeat
   text. Remove the five-alternative guess. Preserve escaped path identities,
   bounded listings and unrelated leftovers so one repeat can address everything
   reported. Include the exact instruction: "leave files you did not change out
   of paths". It applies even when an earlier attempt committed nothing.

## Implementation boundaries

Keep path filtering and filesystem/Git decisions in `factory_commit.py`, shared
by its settlement and read-only refusal paths. Extend the existing `Unsettled`
diagnostic data with typed path/explanation pairs; keep control reason `unsafe`
and existing outcomes. The owning checks supply prose, and step feedback only
renders it. Missing explanations for produced unsafe results must fail a test.
No new glossary terms, persisted state, database migration or answer-schema change.

Update `implement_step.py` and `plan_step.py` feedback and their repeat guidance;
reuse the shared rendering boundary in `step_text.py` if needed. Keep pathname
listings as data rather than encoding predicates into paths for later parsing.
Preserve existing safe control-character rendering and output limits. Any refusal
consumer that displays the affected paths must retain their supplied explanation,
including `operations.verify_failure` for the CLI.

`merge/git.py` also consumes `unsafe_path`. Assess and adapt that caller if its
typed return changes, preserving its existing validation against the captured
automatic-merge tree. This task does not broaden merge-resolution path semantics.
Keep the credential detector for changed/new files; no test-directory exemption
or credential allowlist. Preserve Git-file, ignored-file, foreign-index, slot
pointer, worker/reservation and crash-reconciliation protections.

## Behavioral verification

Use pytest functions, the existing semantic Git fake and slot-file port. Put new
coverage in a bounded file such as `tests/steps/test_commit_paths.py`; avoid growing
the already large `test_verifier.py` or copying a test bootstrap. Construct synthetic
signature bytes from separate literals so the new test source does not trigger
its own credential check. Cover these three acceptance cases through the
refusal/settlement and feedback boundaries:

1. Reproduce the identified credential predicate with ordinary 100644 test source
   containing synthetic credential fixtures. When newly added or changed, it is
   refused with the credential predicate named, and no staging or commit occurs.
2. Exercise real failed predicates with a parameterized table and multiple unsafe
   paths: every displayed path has its own correct explanation, including an
   offending ancestor, size limit, unreadable content and nearby changed Git file.
   Check plan and implement repeat text, escaped path names, unrelated leftovers,
   and the exact unchanged-files instruction. Preserve existing feedback tests in
   `test_implement_feedback.py`, `test_repeat.py` and `test_check_repeat.py`.
3. List an unchanged tracked fixture-containing file beside a genuine edit. Verify
   success, a staged path list containing only the edit, and a commit changing only
   that edit. Include an ordinary unchanged file, an unchanged over-cap file,
   all-paths-unchanged behavior, changed modes and a deletion. Verify read-only
   leftovers agrees with settlement and a changed unsafe file is still refused.

Run focused tests for the touched behavior using the installed successor package.
The implementation gates are `just check` and `just test`, under the active
implementation verification instructions. This planning attempt changes only this
document; implementation checks are deferred until code changes exist.
