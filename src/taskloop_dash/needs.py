"""Parts read by dashboard projections and their contract row readers, including the slots lease table."""
from types import MappingProxyType
from typing import Final

NEEDS: Final = MappingProxyType({
    "dash": 1,  # source, bead
    "slots": 1,  # lease
    "pipeline": 1,  # run, wait
    "asks": 1,  # ask, ask_ledger
    "receipt": 1,
    "beadcache": 1,
    "repos": 1,
    "index": 1,
})
