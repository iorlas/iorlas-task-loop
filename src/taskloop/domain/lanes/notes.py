"""The short notes a worker is sent when its step goes on after a stop, and the gaps between probes of a git push retry."""

from typing import Final

NET_WAIT_CAP_S: Final = 600  # maximum wait for the lander's git push network retry
NET_BACKOFF: Final = (5, 10, 20, 40, 60, 120)  # seconds between the lander's git push network probes
NOTES: Final = {
    "apply_patch": (
        "\nAn earlier attempt at this step ran a command on a secret path and was stopped. Do not read or write "
        "secret files (.env, keys, credentials); change files with your editing tool, never through a shell redirect."
    ),
}
