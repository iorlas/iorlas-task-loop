"""The short notes a worker is sent when its step goes on after a stop."""

from typing import Final

NOTES: Final = {
    "apply_patch": (
        "\nAn earlier attempt at this step ran a command on a secret path and was stopped. Do not read or write "
        "secret files (.env, keys, credentials); change files with your editing tool, never through a shell redirect."
    ),
}
