"""The typed supervisor stop shared by run budgets and their callers."""
class DeadlineExpired(BaseException):
    """A supervisor stop: worker catch-all Exception handlers must not consume it."""

    def __init__(self, scope: str) -> None:
        super().__init__(f"{scope} deadline exceeded")
        self.scope = scope
