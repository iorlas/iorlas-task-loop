"""An exhausted review call can leave the stage without a usable review."""


class ReviewUnavailable(Exception):
    """Delegate returned schema_invalid after the review's bounded retries were exhausted."""
