"""Shared revision validation before real or fake operations can interpret options."""

from __future__ import annotations


def validate_revisions(*revisions: str) -> None:
    """Reject option-like revisions without starting a git process."""
    if any(revision.startswith("-") for revision in revisions):
        msg = "revision must not start with '-'"
        raise ValueError(msg)
