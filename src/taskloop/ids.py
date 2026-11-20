"""Fresh identifiers supplied explicitly to application operations."""

import secrets
from typing import Protocol
from uuid import uuid4


class Ids(Protocol):
    def hex(self) -> str: ...

    def session(self) -> str: ...

    def token(self, nbytes: int) -> str: ...


class NativeIds:
    def hex(self) -> str:
        return uuid4().hex

    def session(self) -> str:
        return str(uuid4())

    def token(self, nbytes: int) -> str:
        return secrets.token_hex(nbytes)
