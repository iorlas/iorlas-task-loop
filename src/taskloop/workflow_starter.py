"""The generic starter workflow `tl init` writes."""

from typing import Final

_BEFORE: Final = """\
[[step.{kind}.prompt]]
text = \"\"\"\\
Follow the repository's AGENTS.md or README for how to work in it. \\
Assess the task, then {work}. \\
Run the repository's checks listed in the supplied context before you answer.
\"\"\"

[[step.{kind}.prompt]]
use = "task"

[[step.{kind}.prompt]]
use = "input_context"
"""
STARTER: Final = (
    "# A starter workflow: each agent step's prompt, in order. The factory appends its contract after these sections\n"
    "# (answer rules, plan template, Git and commit limits); it is not written here. An agent key (harness, model,\n"
    "# effort, compaction_token_limit) may be added under [step.<kind>.agent]; an absent key falls to machine configuration.\n\n"
    + _BEFORE.format(kind="plan", work="write the plan for the change")
    + "\n"
    + _BEFORE.format(kind="implement", work="make the change the plan describes")
    + """
[[step.feedback]]
text = \"\"\"\\
Failed check
The factory's check failed. Fix the reported failure and run the checks before answering.\"\"\"
"""
)
