"""The wait owner's vocabulary."""
from enum import StrEnum


class WaitWhat(StrEnum):
    ACCOUNT = "account"
    NETWORK = "network"
    CHECK_SLOT = "check_slot"  # a check queued for a scarce slot (read from its output)
    RESOURCE = "resource"
    EDITOR_LOCK = "editor_lock"
    LAND_LOCK = "land_lock"
    REVIEW_LOCK = "review_lock"
    AREA_LOCK = "area_lock"
    SLOT = "slot"
