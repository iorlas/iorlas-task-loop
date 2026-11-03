"""Failures of required bd operations, reported by the command line boundary."""


class BdCommandFailure(Exception):
    """A required bd operation failed; the exception text is the owner-facing diagnostic."""
