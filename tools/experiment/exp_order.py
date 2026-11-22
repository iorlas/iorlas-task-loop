"""Block randomization: one block per task holding one run of every arm, blocks and arms in random order."""

import random

from exp_spec import Run, Spec


def plan(spec: Spec) -> list[Run]:
    """Seeded, so the order is reproducible and is recorded with the results. The blocks come out in run order."""
    chance = random.Random(spec.seed)
    tasks = [task.id for task in spec.tasks]
    chance.shuffle(tasks)
    runs: list[Run] = []
    for block, task in enumerate(tasks, 1):
        arms = list(spec.arms)
        chance.shuffle(arms)
        runs.extend(Run(name=f"{task}_{arm}", task=task, arm=arm, block=block, position=position) for position, arm in enumerate(arms))
    return runs


def describe(runs: list[Run]) -> str:
    """`order.txt`: one line per block, the arms in the order they were launched."""
    blocks: dict[int, list[Run]] = {}
    for each in runs:
        blocks.setdefault(each.block, []).append(each)
    return "\n".join(f"{members[0].task}: " + " ".join(each.arm for each in members) for members in blocks.values()) + "\n"
