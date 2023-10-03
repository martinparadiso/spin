"""Minimal machine class to prevent circular dependencies"""

from __future__ import annotations

import re
import uuid as _uuid


class UUID(str):
    """`str` subclass that allows only UUIDs"""

    regex = re.compile(
        "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    )

    def __new__(cls, value: None | str = None) -> UUID:
        if value is not None:
            _uuid.UUID(value)
        else:
            value = str(_uuid.uuid4())
        return super().__new__(cls, value)

    @staticmethod
    def is_valid(value: str) -> bool:
        """Check if a string is a valid UUID.

        Args:
            value: The string to check.

        Return:
            ``True`` if the value is a valid UUID, ``False`` if not.
        """
        return UUID.regex.match(value) is not None


class CoreMachine:
    def __init__(self, uuid: None | UUID | str = None) -> None:
        self.uuid: UUID = UUID(uuid)
