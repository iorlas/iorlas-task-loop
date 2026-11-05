"""The shape of a decoded JSON value: what delegate reads from a vendor CLI, its config files and its own state, before a record narrows it."""

type Json = dict[str, Json] | list[Json] | str | int | float | bool | None
