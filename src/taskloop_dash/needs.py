"""Parts read by dashboard projections and their contract row readers. The `lease` table (slots part) is read too, but the dashboard
cannot import a stage package to declare that part; it joins here when the slots part is importable from the kernel or a public view."""
from types import MappingProxyType
from typing import Final

NEEDS: Final = MappingProxyType({
    "dash": 1,  # source, bead
    "pipeline": 1,  # run, wait
    "asks": 1,  # ask, ask_ledger
    "kv": 1,  # remaining shared documents
    "receipt": 1,
    "beadcache": 1,
    "repos": 1,
    "index": 1,
})
