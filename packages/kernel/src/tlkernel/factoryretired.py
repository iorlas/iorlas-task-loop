"""Retired factory.db ownership, shared without importing the live schema's records and stores."""
from types import MappingProxyType
from typing import Final

# Parts that existed once; a rw launch deletes their schema_part row and drops their tables; D-KV.
DROPPED_PARTS: Final = MappingProxyType({"kv": ("kv",)})
