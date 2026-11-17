"""The names of the factory's framed data blocks in an agent's input: the one owner of each marker's wording. A block
opens with `BEGIN <name>` and closes with `END <name>`; a workflow file may not contain a name (`workflow`), so its prose
cannot forge a block."""

from typing import Final

CONTEXT: Final = "FACTORY INPUT CONTEXT"
DISCUSSION: Final = "TRACKER DISCUSSION DATA"
EARLIER: Final = "EARLIER ATTEMPT DATA"
RESERVED: Final = (CONTEXT, DISCUSSION, EARLIER)
