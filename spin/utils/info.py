"""Retrieve information from various sources"""

import getpass
import os
import pathlib
import platform

from spin.utils.constants import ARCHITECTURE_CODES


def host_architecture() -> str:
    """Return the current host architecture"""

    arch = platform.machine()
    if arch not in ARCHITECTURE_CODES:
        raise Exception(f"Unknown architecture: {arch}")
    return arch


def host_user() -> str:
    """Return the host username.

    Warning: this *may* not be the real user; since it uses
        environment variables and such to determine the user.
        Still useful if the host is trusted and it is used for
        non-security applications.

    Returns:
        The name of the current user.
    """

    return getpass.getuser()


def can_write(file: pathlib.Path) -> bool:
    """Check if a given file is writable by the current user.

    Returns:
        ``True`` if the file is writeable; ``False`` otherwise.

    Raises:
        ValueError: If the path does not exist.
    """
    if not file.exists():
        raise ValueError("File not present")
    return os.access(file, os.W_OK)
