"""The short, lowercase host name used in engine slot identities."""
import socket


def hostname() -> str:
    return socket.gethostname().split(".")[0].lower()
