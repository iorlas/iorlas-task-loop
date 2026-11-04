"""Shared real/fake validation before remote commands can have side effects."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


def validate_remote(remote: str | None) -> None:
    if remote is not None and remote.startswith("-"):
        msg = "remote must not start with '-'"
        raise ValueError(msg)


def validate_delete_ref(ref: str) -> None:
    if not ref.startswith("refs/"):
        msg = "remote deletion requires a full refs/ name"
        raise ValueError(msg)


def validate_push(
    remote: str | None,
    refspecs: Sequence[str],
    *,
    options: Sequence[str] = (),
    force: bool = False,
    allow_delete: bool = False,
) -> None:
    validate_remote(remote)
    force_requested = any(spec.startswith("+") for spec in refspecs) or any(opt in {"--force", "-f", "--mirror"} for opt in options)
    delete_requested = any(spec.removeprefix("+").startswith(":") for spec in refspecs) or any(
        opt in {"--delete", "-d", "--mirror", "--prune"} for opt in options
    )
    if force_requested and not force:
        msg = "forced pushes require force=True"
        raise ValueError(msg)
    if delete_requested and not allow_delete:
        msg = "remote deletions require allow_delete=True"
        raise ValueError(msg)
