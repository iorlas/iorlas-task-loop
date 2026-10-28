"""Names of a check: its normal command text and the environment variables later checks read it by."""
from itertools import groupby

LOG_PREFIX = "TL_CHECK_LOG_"
RC_PREFIX = "TL_CHECK_RC_"


def norm(cmd: object) -> str:
    """The command with its whitespace collapsed: what two spellings of one command share."""
    return " ".join(str(cmd).split())


def mangle(check_id: str) -> str:
    """The id as an environment name: each run of non-word characters becomes one `_`, upper case."""
    out = []
    for word, run in groupby(check_id, key=lambda ch: ch.isalnum() or ch == "_"):
        out.append("".join(run) if word else "_")
    return "".join(out).upper()


def log_var(check_id: str) -> str:
    return LOG_PREFIX + mangle(check_id)


def rc_var(check_id: str) -> str:
    return RC_PREFIX + mangle(check_id)
