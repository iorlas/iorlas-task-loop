"""Print the account role module generated from the skill's authoritative node-to-role table."""

from pathlib import Path


def generate(skill: str) -> str:
    table = skill.split("| node | delegate role |\n|---|---|\n", 1)[1].split("\n\n", 1)[0]
    pairs = [row.strip("|").split("|") for row in table.splitlines()]
    roles = ", ".join(f'"{node.strip()}": "{role.strip()}"' for node, role in pairs)
    return (
        '"""Generated from SKILL.md\'s node-to-role table by dev/generate_account_roles.py; tests enforce parity."""\n'
        '\nfrom typing import Final\n\n'
        f'ROLES: Final = {{{roles}}}\n'
        'READ_ONLY_NODES: Final = tuple(node for node, role in ROLES.items() if role == "reviewer")\n'
    )


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    print(generate((root / "skills/task-loop/SKILL.md").read_text(encoding="utf-8")), end="")
