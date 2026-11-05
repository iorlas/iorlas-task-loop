"""`tl artifact-server`: the artifact_add tool as a stdio MCP server, started by a worker's harness for one call. Not a session command:
the binding comes from argv (the factory writes it, the model cannot), and stdout carries only protocol lines."""
import sys
from argparse import Namespace
from collections.abc import Callable
from pathlib import Path

from taskloop.app.artifacts import server
from taskloop.contracts.artifact import ArtifactSlot
from taskloop.contracts.paths import ConfigDir


def run(a: Namespace, cfg: ConfigDir, now: Callable[[], float]) -> int:
    slot = ArtifactSlot(repo=a.repo, bead=a.bead, run=a.run, stage=a.stage, attempt=a.attempt)
    return server.serve(sys.stdin, sys.stdout, cfg.artifact_store(), slot, Path(a.cwd), now)
