"""The one loose shape of the dashboard's timeline views: a JSON object whose keys the view code reads one by one (a run's node, a
block, an arrow, a live event). Records the dashboard owns are typed (taskloop.contracts); these are the views' working dicts."""
from typing import Any

type Json = dict[str, Any]
type Pair = list[Any]  # [cmd, exit, tail, secs]: a command and the exit note after it, filled in as the lines are read
