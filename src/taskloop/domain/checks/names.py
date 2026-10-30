"""Names of a check: its normal command text and the environment variables later checks read it by."""
from typing import Final

from taskloop.contracts.ids import CheckId, mangle

LOG_PREFIX: Final = "TL_CHECK_LOG_"
RC_PREFIX: Final = "TL_CHECK_RC_"


def norm(cmd: object) -> str:
    """The command with its whitespace collapsed: what two spellings of one command share."""
    return " ".join(str(cmd).split())


def log_var(check_id: CheckId) -> str:
    return LOG_PREFIX + mangle(check_id)


def rc_var(check_id: CheckId) -> str:
    return RC_PREFIX + mangle(check_id)
