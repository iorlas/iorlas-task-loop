"""Wait cap and probe gaps for the lander's git push network retry."""
from typing import Final

NET_WAIT_CAP_S: Final = 600  # maximum wait for the lander's git push network retry
NET_BACKOFF: Final = (5, 10, 20, 40, 60, 120)  # seconds between the lander's git push network probes
