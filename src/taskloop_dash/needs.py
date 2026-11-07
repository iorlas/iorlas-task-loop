"""Parts read by dashboard projections and their contract row readers."""

NEEDS: dict[str, int] = {
    "dash": 1,  # source, bead
    "pipeline": 1,  # run, wait
    "slots": 1,  # lease
    "asks": 1,  # ask, ask_ledger
    "kv": 1,  # freshness, loops, looks and repository records
}
