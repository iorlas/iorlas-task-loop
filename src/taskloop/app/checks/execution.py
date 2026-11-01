"""Resolve execution before a receipt can be read or minted."""
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from taskloop.contracts.config import ContainerConfig
from taskloop.contracts.envvars import EnvVar
from taskloop.contracts.ports import Ran
from taskloop.contracts.runkey import Digest


class Runs(Protocol):
    def run(self, argv: list[str], *, cwd: str | None = None, extra: Mapping[str, str] | None = None,
            timeout_s: float | None = None) -> Ran: ...


@dataclass(frozen=True)
class ReadyExecution:
    identity: Digest
    image: str = ""


@dataclass(frozen=True)
class EnvironmentUnavailable:
    reason: str


HOST = ReadyExecution(Digest("host-v1"))


def check_env() -> dict[str, str]:
    """The admitted environment shared by standalone checks and delivery queries."""
    return {EnvVar.TL_SLOT.value: "check"}


def docker_ok(spawner: Runs) -> bool:
    try:
        return spawner.run(["docker", "info"], timeout_s=15).exit == 0
    except OSError:
        return False


def image_identity(spawner: Runs, image: str) -> str:
    ran = spawner.run(["docker", "image", "inspect", "--format", "{{.Id}}", image], timeout_s=15)
    identity = ran.out.strip()
    return identity if ran.exit == 0 and identity.startswith("sha256:") else ""


def resolve_container(spec: ContainerConfig | None, wt: str, spawner: Runs) -> ReadyExecution | EnvironmentUnavailable:
    try:
        if spec is None:
            return EnvironmentUnavailable("container configuration missing")
        if not docker_ok(spawner):
            return EnvironmentUnavailable("docker not reachable")
        image = spec.image
        if not image:
            path = Path(wt) / spec.dockerfile
            built = spawner.run(["docker", "build", "-q", "-f", str(path), str(path.parent)])
            image = built.out.strip() if built.exit == 0 else ""
        identity = image_identity(spawner, image) if image else ""
        return ReadyExecution(Digest(identity), identity) if identity else EnvironmentUnavailable("container image not available")
    except OSError as err:
        return EnvironmentUnavailable(str(err))
