"""The verifier's prompt."""
from typing import Final

from taskloop.domain.prompts.common import KIND_LINES

VERIFY_PROMPT: Final = """Before a task lands, you check what its workers could not check themselves. Do not edit files.
<task>
{brief}
</task>
The work (files the task changed, with line counts):
{work}
Proof the workers saved (command output, logs, pictures) is in {evidence}/.
{checks}{where}
Nobody has checked these items yet:
{items}
Settle each one yourself where you can: read the code, its call sites, sibling files, the saved proof and the engine's check
results above, and run
read-only commands (search, list, compare, count). Answer one entry per item, n its number:
- settled: you proved it right; evidence quotes exactly what proves it (the file and lines, or the command and its
  output).
- wrong: you found a real defect; why says what is wrong and where, so a writer can fix it.
- open: only a person can judge it (taste, a device or a screen you cannot reach, the owner's call); why says what they
  must look at.
When in doubt, it is open: never settle an item you did not prove.
Also give each item its kind (the engine routes by it; an open item of the wrong kind is asked or lands unseen):
- """ + "\n- ".join(KIND_LINES) + """
- other: none of these."""
