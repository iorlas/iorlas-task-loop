# Attempt-input measurement

Deployment measurement is pending. No later attempts using this change exist within
this implementation step, and no live attempt campaign was run. Unit and contract tests
do not establish the six-attempt acceptance criterion or the projected 6–8% saving.

The supplied baseline covers 18 attempts: 51.4M weighted input tokens, including 4.84M
from orientation reads (9.4%). This is the owner's supplied measurement, not a new
transcript audit performed during implementation.

For the current repository files, generation produces a 1,995-byte glossary extract
and a 3,150-byte shared context, including a 40-character source commit, the orientation
directions and both check commands. These are UTF-8 byte counts, not measured model
token counts. The extract's enforced ceiling is 2,000 bytes. The addition is smaller
than the reported 17–19K-token orientation burst, but weighted net savings depend on
actual later model calls and must still be measured.

After deployment, record at least six later plan/implement attempts, identifying repeats
when available. Each evidence row must contain attempt id, step and repeat kind, factory
revision, source commit, transcript reference, model-call count, added-context tokens,
orientation-read tokens and weighted total tokens. Preserve references to the admission
snapshot and `launched-input.txt`; the latter contains the actual source commit and
complete launched text.

Audit structured tool inputs, including compound commands and alternate file readers.
Each attempt must have zero reads of AGENTS.md, SKILL.md, justfile and .task-loop.json,
zero tracker invocations, and at most one glossary read command. Record any foundation
plan read and whether the task's own plan cited it. A violation fails the sample and
requires revised input and a new sample; omitted calls are not zero reads.

For comparable attempt kinds, charge each model call its full input, including repeated
tool output and this context. Report old orientation cost, new prefix size, remaining
orientation reads, call counts and net tokens. Keep plan-step accounting owned by .192
separate so its savings are not counted twice. Glossary compliance remains a review
check. There are currently zero qualifying post-change samples.
