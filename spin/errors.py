"""Errors and exceptions raised by the library
"""

from __future__ import annotations

from typing import Any, Generic, Protocol, TypeVar

from typing_extensions import TypeGuard


class TODO(Exception):
    """Raised instead of `NotImplementedError`.

    `NotImplementedError` is reserved for abstrasct methods (since
    it is already used by `abc`). For features yet to be implemented,
    please raise this instead so it is easier to track and
    differentiate from abstract methods.
    """

    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class ConnectionClosed(Exception):
    """Raised when a connection is closed.

    For instance, when a serial port is closed by the guest --due to poweroff--
    and the object user tries to read or write, this exception is raised.
    """

    def __init__(self, msg: None | str = None) -> None:
        """
        Args:
            msg: The exception message.
        """
        super().__init__(msg)


class CommandTimeout(Exception):
    """Raised when a command sent to a guest machine timesout"""

    def __init__(self, command: str, timeout: float, msg: None | str = None) -> None:
        """
        Args:
            command: The command `timedout`.
            timeout: The time waited for the command to complete.
            msg: The exception message.
        """
        self.command = command
        """The failed command"""

        self.timeout = timeout
        """The time waited for the command to finish"""

        if msg is None:
            msg = f"{command} after {timeout} seconds"
        super().__init__(msg)


class NoBackend(Exception):
    """Raised when there is no backend available to perform a task.

    Some tasks, such as starting a VM, require a 'backend', such as libvirt,
    QEMU. If there is no backend available, this exception should be raised.

    Args:
        msg (str): A helpful message to the user
    """

    def __init__(self, msg="No backend available to perform this task"):
        super().__init__(msg)


class MissingAttribute(Exception):
    """Raised when a machine object is missing a required argument"""

    def __init__(self, parent_obj: Any | None, *args: str) -> None:
        """
        Args:
            parent_obj: The object with missing attributes.
            args: List of missing attributes.
        """
        csv = ", ".join(args)
        super().__init__(f"{parent_obj} missing required attribute(s): {csv}")

        self.object = object
        """The machine with the missing attributes"""

        self.missing = [args]
        """A list containing the missing attributes"""


T = TypeVar("T")


class NotFound(Exception, Generic[T]):
    """Raised when a search for an element of type T is not found"""

    def __init__(self, search: None | T = None) -> None:
        """
        Args:
            search: The element not found during the search.
        """
        self.search = search
        if self.search is not None:
            msg = f"{search} not found."
            super().__init__(msg)


class CommandReturn(Protocol):
    """Protocol expected by `CommandFailed` as an argument"""

    cmd: list[str]
    returncode: int
    stdout: bytes
    stderr: bytes


class CommandFailed(Exception):
    """Raised when a command issued to guest fails"""

    def __init__(self, ret: CommandReturn) -> None:
        msg = f"External command failed: return code {ret.returncode}\n"
        msg += str(ret.cmd) + "\n"
        msg += f"stdout: {ret.stdout.decode('utf8')}\n"
        msg += f"stderr: {ret.stdout.decode('utf8')}"
        super().__init__(msg)


class BackendError(Exception):
    """Raised when something fails in the backend"""

    def __init__(self, msg: None | str = None) -> None:
        super().__init__(msg)


class Bug(Exception):
    """Internal bug or unexpected situation.

    If you encounter an exception like this, please consider
    reporting it.
    """

    def __init__(self, msg: None | str = None) -> None:
        super().__init__(msg)


class UnresolvedTasks(Exception):
    """After the creation process; there were unresolved tasks"""

    def __init__(self, args: list) -> None:
        super().__init__(*args)


class NoUserAvailable(Exception):
    """Raises when the user is not available to select an option"""

    def __init__(self, *args: object) -> None:
        super().__init__(*args)


AT = TypeVar("AT")


def require(attr: None | AT) -> TypeGuard[AT]:
    """Raise exception if the given object is None"""
    if attr is not None:
        return True
    return False
