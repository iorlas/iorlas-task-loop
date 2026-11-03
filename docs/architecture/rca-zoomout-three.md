# RCA: three C4 findings (2026-11-02)

Scope: the C4 zoom-out findings as a set, the `--exec-allow` risk (Z11), and the pre-push profile source (Z02, with Z01 and Z03).
Static reading of `zoom-out-review.md`; nothing run. Beads in the last section.

## 1. The C4 findings as a set

**Symptom.** 26 findings; 5 are P1. They look unrelated.

**Root causes (three, each explains several findings).**

| Root cause | Findings it produces | Why it persisted |
|---|---|---|
| R-A: a fact has no single owner, so each reader builds its own view (profile, repo key, stop reason, delivery verdict, delegate path) | Z01, Z02, Z07, Z13, Z18, Z23 | Each hardening slice fixed the reader it was written for (HOOKPUSH, CHECKIDENT) and left the sibling reader. The import rules pass, so nothing flags a second reader. |
| R-B: shared state is written by several processes with get-then-put and no revision | Z04, Z14, Z15, Z19, Z20 | Single-writer was true when the files were introduced; every later writer (loop, dashboard, doctor, status poll) was added without changing the store. |
| R-C: the trust line is the sandbox, then punched through for convenience or delivered by prose | Z03, Z11, Z15, Z24, Z25 | Each hole saved one round or one deploy step; none had a test that fails when the hole opens. Fail-open defaults survived at edges hardened after the fact. |

**Contributing, not root:** docs that say "only the contract is shared" and "dashboard only reads" (Z08, Z09, Z26) hid the drift
from agents that read CLAUDE.md first. Release hops (Z05, Z21) are a design question for the owner, not a defect.

**Why the factory did not catch it.** Gates test the behaviour a slice added. No test asserts "exactly one reader of X" or "every
write path to Y is revisioned". The first is expressible as import-linter contracts and a rule test per fact.

**Fix order (unchanged from the review):** push path first (Z01-Z03, Z14), then contract/flag negotiation, then CAS store, then
the rethinks R1-R5 behind owner decisions.

## 2. `--exec-allow` (Z11)

**What it does.** The engine passes `engine.writer_exec_allow` argv prefixes; delegate writes Codex execpolicy `prefix_rule(...,
allow)` into an overlay `CODEX_HOME`; a matching command runs outside the sandbox with no prompt, network and full filesystem. A
shim refuses a guarded path that differs from the BASE commit and writes an audit row.

**Root cause of the risk.** The goal ("the writer must iterate on Unity") needs the writer to run code it just edited. A guard on
recipe files does not bound that: `unity-shot`, `dotnet test` and `just text` execute project sources the writer changed (test
projects, editor scripts, MSBuild targets, package scripts). Delegate's constitution already says a fixed-command whitelist does
not bound a build tool that runs repo code. The guard can name files; it cannot name what the tool loads.

**Analysis of the options.**

| Option | Bounds writer-edited code? | Cost | Verdict |
|---|---|---|---|
| (a) exec-allow for all, guarded | no | none | refuse: reopens the named hole |
| (b) engine runs every Unity/dotnet command | yes (host runs it after the write, as today) | one write round per iteration | accept as default |
| (c) exec-allow only for tools that run no writer-edited code (`typos`, `fmt-check-changed`, `design` lint, text lint) | yes for those tools | small | accept for those; they are the denials that block the writer today |
| (d) writer requests a declared engine command, engine runs it in the check round and feeds the result back | yes | M | the real fix for Unity iteration |

**Decision recommended (Denis to confirm): (c) now, (d) next; no `unity-shot`, `dotnet-test` or `tools-tests` entry in any
exec-allow list.** Also fix before any caller exists: reject `just -f`, `nice`, `timeout`, `command`, `uv`, `npx`, `make` as first
token or as wrapper; check the whole argv, not `prefix[1]`; delete the overlay after the call; never leave `auth.json` symlink
reachable beyond the run.

**State of the build.** Delegate side (UNITYD, UNITYG-D) and task-loop side (UNITYT, UNITYG-T) exist as wip commits and are not
released. They stay unreleased until the list is limited as in (c) and the guard review passes.

## 3. Pre-push profile source (Z02, with Z01 and Z03)

**Symptom.** `push_judge.push_profile` reads `<repo>/.task-loop.json` from the working tree; `if not cfg.gate_checks: ALLOWED`.
A writer that commits `"gate_checks": []` makes its own push pass.

**Root cause.** Three readers of one profile with three meanings: the loop reads the base-committed profile, delivery
authorization reads the judged tree, the push judge reads the working tree. The judge was written for the engine's own push, where
tree and base were assumed equal; the writer-edited tree was not modelled. An empty gate meaning "allow" is the second cause:
absence of a gate is treated as permission, not as a failure.

**Contributing.** Z01: the judge asks for ID-only evidence its own docstring forbids for delivery; CHECKIDENT fixed
`stackgate` and not this call. Z03: any unexpected exception in the git hook returns 0.

**Fix (PUSHKEY, GATESELECT).**
1. Resolve the profile at the base the push is judged against (`base_for(tip)`) through the same reader as the loop; never the working tree.
2. A candidate that changes `.task-loop.json` is judged by the base's gate; the change needs the owner label to land.
3. Empty or unreadable gate on a protected ref: refuse (fail closed), not allow.
4. Full-key authorization (`authorization.results` with the executed `CheckKey`) in the judge; `green_result` banned from `land/`.
5. Git hook: dispatch before the catch-all; `pre-push` exits 1 on any exception.
Test: a candidate committing `gate_checks: []`, a host receipt for a container-required check, an unimportable `prepush` module:
each refuses the push.

**Release note.** This changes push behaviour: announce the version before release.

## 4. Beads

Epic ZOOMOUT with the children listed in `zoom-out-review.md` section 5, plus: ZOOMOUT-INVARIANTS (one reader per fact enforced by
import-linter and a rule test, from R-A and R-B), ZOOMOUT-EXECALLOW-LIMIT (option c now, hardening list above), PUSHBASE-FAILCLOSED
(empty gate refuses). Existing beads reused, not duplicated: tl-1kox PUSHKEY, tl-3cl.4 GATESELECT, tl-auky UNITYCODEX, tl-br2.5
FENCE, tl-br2.7 HOPSAFE.
