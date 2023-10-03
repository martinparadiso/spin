"""Common types with no internal dependencies"""

from __future__ import annotations

import pathlib

from typing_extensions import Protocol

from spin.machine.machine import Machine


class SpinfileProtocol(Protocol):
    """Manage save and load of machinefile(s).

    The save and load functionality is simple, but it is centralized
    here to avoid code duplication.
    """

    def __init__(self, path: pathlib.Path) -> None:
        ...

    def load(self) -> list[Machine]:
        """Load the machines found in the machinefile."""
        ...

    def save(self, *machines: Machine, update: bool = False) -> None:
        """Save machine(s) in this folder.

        Args:
            machines: Machine(s) to save in this folder `Machinefile`.
            update: If set to ``True``, overwrite machines found with same
                UUID. If it is set to ``False``, ValueError will be raised
                when a machine with the same UUID exists.

        Raises:
            ValueError: If no machine is provided.
            ValueError: If the folder is not initiated.
            ValueError: If a machine with same UUID already exists.
        """
        ...


class SpinfolderProtocol(Protocol):
    """Represents a ``.spin`` folder. Not neccessarely created yet."""

    def __init__(
        self,
        *,
        parent: None | pathlib.Path = None,
        location: None | pathlib.Path = None,
    ):
        """
        Args:
            parent: Parent folder, where the new spinfolder is going to
                be created.
            location: Exact location of the folder.

        Both ``parent`` and ``location`` can be provided; only if
        ``parent == location.parent``. At least one must be present.

        Raises:
            ValueError: If both ``parent`` and ``location`` are ``None``.
            ValueError: If both ``parent`` and ``location`` are provided, but
                they do not match.
        """
        ...
