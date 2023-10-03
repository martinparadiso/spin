"""Utilities for cryptography manipulation.

No `real` cryptography involved, only shortcuts and quick
functions to save time.
"""

from __future__ import annotations

import base64
import hashlib

from typing_extensions import Protocol

from spin.errors import TODO


class _HasPubKey(Protocol):
    pubkey: str


class _PropertyHasPubKey(Protocol):  # Required by PyRight
    @property
    def pubkey(self) -> str:
        ...


def fingerprint(cred: _HasPubKey | _PropertyHasPubKey) -> str:
    """Return the sha-256, base64 encoded fingerprint of the given public key.

    Args:
        cred: An SSH credential, to extract the public key from

    Returns:
        The `base64` encoded, sha256 hash of the public key.
    """
    if not cred.pubkey.startswith("ssh-rsa"):
        raise TODO("Cannot fingerprint the requested key")

    key = base64.b64decode(cred.pubkey.split()[1])
    return base64.b64encode(hashlib.sha256(key).digest()).decode("utf8").strip("=")


def normalize(key: str) -> str:
    """Normalize the given --public-- key.

    The function removes unnecessary spaces and new lines.

    Args:
        key: The key to sanitize.
    """
    key = key.strip()
    return key
