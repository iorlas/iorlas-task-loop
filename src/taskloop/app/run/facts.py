"""The run's facts and ports, taken from the engine once it is built (docs/design/facts.md, tl-e5t0.28): the new read path for the stages
that stop taking the engine. Nothing here changes the engine; every handle is the engine's own."""
from pathlib import Path

from tlkernel.stagefacts import RunFacts

from taskloop.adapters.check_files import repo_key
from taskloop.app.run.host import RunHost
from taskloop.stores.runports import RunPorts


class EngineRepoKey:
    """RepoKey over the engine's own memo (`artifact_repo`, which ask_flow also fills): taken at the first call, the same string after."""

    def __init__(self, e: RunHost) -> None:
        self.e = e

    def key(self) -> str:
        e = self.e
        e.artifact_repo = e.artifact_repo or repo_key(e.git, e.wt)
        return e.artifact_repo


def open_facts(e: RunHost, repo: str) -> tuple[RunFacts, RunPorts]:
    facts = RunFacts(
        bead=e.bead, wt=e.wt, cfg=e.cfg, home=e.home, run_id=e.run_id, run_dir=Path(e.run_dir), task_dir=Path(e.task_dir),
        brief_file=Path(e.brief_file), evidence_dir=Path(e.evidence_dir), repo=repo, dry=e.dry, fresh=e.fresh, claim=e.claim,
    )
    ports = RunPorts(
        clock=e.clock, env=e.env, git=e.git, spawner=e.spawner, steps=e.steps, log=e.log, checklog=e.checklog, store=e.store,
        stores=e.stores, checkpoints=e.checkpoints, checker=e.checker, repo=EngineRepoKey(e),
    )
    return facts, ports
