"""Objects for storing shell commands for later execution"""

from __future__ import annotations

from typing_extensions import TypeAlias, TypedDict


def sanitize_multiline(multiline: str) -> str:
    """Parse a multiline string, removing unnecessary spaces

    The function removes the spaces commonly found in 'aligned' multiline
    strings. This avoids sending extra spaces when feeding multiline commands
    to a shell.

    If the received string has less than 3 lines, no processing is done.

    Args:
        multiline: The multiline :py:class:`str` to remove the leading spaces.

    Returns:
        The processed string. Or the same string if the input has less than 3
        lines.

    Examples:

        The function is designed to make the following conversion::

            a = \"""
                A multiline
                string
            \"""

            b = "A multiline\\nstr\\n"

            assert sanitize_multiline(a) == b
    """
    lines = multiline.splitlines()
    if len(lines) < 3:
        return multiline

    def leading_spaces(line: str) -> int:
        acc = 0
        for char in line:
            if char != " ":
                break
            acc += 1
        return acc

    if lines[0] == "":
        # First line is empty due to format style::
        #
        #   multiline = """
        #       ...
        #   """
        lines = lines[1:]

    if leading_spaces(lines[0]) != len(lines[0]):
        lspace = leading_spaces(lines[0])
    else:
        lspace = leading_spaces(lines[1])

    if leading_spaces(lines[-1]) < lspace:
        # Last line is also an empty line due to formatting
        lines = lines[:-1]

    return "".join(line[lspace:] + "\n" for line in lines)


class Script:
    """Wraps a script (or single-line command)"""

    class Serialized(TypedDict):
        content: str
        ignore_errors: bool

    def __init__(self, content: str, ignore_errors: bool = False) -> None:
        self.content: str = content
        """The content of the shell script or command"""

        self.ignore_errors: bool = ignore_errors
        """If set to ``True``, the library won't stop if command returns non-zero code."""

    def summary(self, max_length: int = 30) -> str:
        """Generate a single line, command summary; for pretty printing"""
        multiline = self.content.splitlines()
        if len(multiline) > 1:
            append = "..."
        elif len(multiline[0]) > max_length:
            append = "..."
        else:
            append = ""
        return multiline[0][: max_length - len(append)] + append

    def dict(self) -> Serialized:
        """Serialize the script into a JSON friendly ``dict``"""
        return {"content": self.content, "ignore_errors": self.ignore_errors}


class ShellInput:
    """Manages shell input in a sugary way

    Examples:

        Send the ``date`` command, to print the time at the moment of
        execution::

            shell = ShellInput()
            shell <<= "date --iso-8601=seconds"

        Multiline commands, in this case update packages on debian-based
        machine::

            shell = ShellInput()
            shell <<= r\"""
                export DEBIAN_FRONTEND=noninteractive
                apt-get update
                apt-get upgrade --yes
            \"""
    """

    Script: TypeAlias = Script

    class Serialized(TypedDict):
        commands: list[Script.Serialized]

    def __init__(self, commands: None | list[Script.Serialized] = None) -> None:
        self.commands: list[Script] = []
        """List of commands, stored as strings"""

        if commands:
            self.commands = [Script(**s) for s in commands]

    def __ilshift__(self, cmd: str) -> ShellInput:
        self.add_command(cmd)
        return self

    def __len__(self) -> int:
        """Return the number of commands to execute"""
        return len(self.commands)

    def add_command(self, cmd: str, ignore_errors: bool = False) -> None:
        """Issue a command to the guest machine

        Args:
            cmd: The command to send.
            on_fail: Action to perform when a command fail.
        """
        self.commands.append(
            Script(sanitize_multiline(cmd), ignore_errors=ignore_errors)
        )

    def __eq__(self, __o: object) -> bool:
        return isinstance(__o, ShellInput) and self.commands == __o.commands

    def dict(self) -> Serialized:
        """Serialize the script into a JSON friendly ``dict``"""
        return {"commands": [c.dict() for c in self.commands]}
