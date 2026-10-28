"""Which delegate role runs which node. The only delegate vocabulary in the engine (the Workers table of SKILL.md is the same map)."""

from typing import Final

ROLES: Final = {"plan": "planner", "write": "worker", "review": "reviewer", "verify": "reviewer", "look": "reviewer"}
READ_ONLY_NODES: Final = ("review", "verify", "look")  # reviewer rungs: they read the writer's work
