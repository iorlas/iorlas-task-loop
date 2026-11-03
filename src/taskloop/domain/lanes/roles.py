"""Generated from SKILL.md's node-to-role table by dev/generate_lane_roles.py; tests enforce parity."""

from typing import Final

ROLES: Final = {"plan": "planner", "write": "worker", "review": "reviewer", "verify": "reviewer", "look": "reviewer"}
READ_ONLY_NODES: Final = tuple(node for node, role in ROLES.items() if role == "reviewer")
