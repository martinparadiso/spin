"""User interface utilities (does not mean graphical nor TUI)

The library contains utilities for communicating with the user. This removes
the need to manually check how the library is being called, and implement
common operations.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Iterator, Protocol, Sequence, TypeVar

from typing_extensions import ContextManager, Literal

DEFAULT_FG = "\x1B[39m"
DEFAULT_BG = "\x1B[49m"

COLORS_LITERAL = Literal[
    "black",
    "red",
    "green",
    "yellow",
    "blue",
    "magenta",
    "cyan",
    "white",
    "gray",
    "bright_red",
    "bright_green",
    "bright_yellow",
    "bright_blue",
    "bright_magenta",
    "bright_cyan",
    "bright_white",
]


class Formatter(Protocol):
    """Format a string of text."""

    def color(self, color: COLORS_LITERAL | str, string: str) -> str:
        """Colorize *string* with the given color.

        Results may vary.
        """
        ...

    def strong(self, string: str) -> str:
        ...

    def emph(self, string: str) -> str:
        ...

    def underline(self, string: str) -> str:
        ...

    def _colorize(self, color: COLORS_LITERAL | str) -> Callable[[str], str]:
        def _colorize(string: str) -> str:
            return self.color(color, string)

        return _colorize

    @property
    def black(self):
        return self._colorize("black")

    @property
    def red(self):
        return self._colorize("red")

    @property
    def green(self):
        return self._colorize("green")

    @property
    def yellow(self):
        return self._colorize("yellow")

    @property
    def blue(self):
        return self._colorize("blue")

    @property
    def magenta(self):
        return self._colorize("magenta")

    @property
    def cyan(self):
        return self._colorize("cyan")

    @property
    def white(self):
        return self._colorize("white")

    @property
    def gray(self):
        return self._colorize("gray")

    @property
    def bright_red(self):
        return self._colorize("bright_red")

    @property
    def bright_green(self):
        return self._colorize("bright_green")

    @property
    def bright_yellow(self):
        return self._colorize("bright_yellow")

    @property
    def bright_blue(self):
        return self._colorize("bright_blue")

    @property
    def bright_magenta(self):
        return self._colorize("bright_magenta")

    @property
    def bright_cyan(self):
        return self._colorize("bright_cyan")

    @property
    def bright_white(self):
        return self._colorize("bright_white")


class Progress(ContextManager, Protocol):
    """Indicate progress of a lengthy static process (such as download)"""

    def __enter__(self) -> Progress:
        ...

    def __exit__(self, *args) -> None:
        ...

    def update(self, percentage: None | float) -> None:
        """Indicate the current progress of the operation.

        Percentage:
            The current progress, in the range ``[0, 1]``. `None`
            indicates *unknown*.
        """
        ...


DEBUG: Literal[0] = 0
INFO: Literal[1] = 1
NOTICE: Literal[2] = 2
WARNING: Literal[3] = 3
ERROR: Literal[4] = 4
FATAL: Literal[5] = 5

LEVEL_LITERAL = Literal[0, 1, 2, 3, 4, 5]

LEVEL_STRING = {
    0: "DEBUG",
    1: "INFO",
    2: "NOTICE",
    3: "WARNING",
    4: "ERROR",
    5: "FATAL",
}


class UI(Protocol):
    """User interface *interface*; available library-wide to avoid using print"""

    level: int
    verbose: bool
    """Return `True` if the logging is set to verbose mode.

    Note: should only be used to call external dependencies with a
        verbose flag (i. e. ``curl -v``). To log optional messages
        use `debug` or `info`.
    """

    def message(self, level: LEVEL_LITERAL, *values: str | Any) -> None:
        ...

    def debug(self, *values: str | Any) -> None:
        """Print a debug message."""
        self.message(DEBUG, *values)

    def info(self, *values: str | Any) -> None:
        """Print an informational message"""
        self.message(INFO, *values)

    def notice(self, *values: str | Any) -> None:
        """Notify a relevant message to the user."""
        self.message(NOTICE, *values)

    def warning(self, *values: str | Any) -> None:
        """Notify a warning."""
        self.message(WARNING, *values)

    def error(self, *values: str | Any) -> None:
        """Notify an error."""
        self.message(ERROR, *values)

    def fatal(self, *values: str | Any) -> None:
        """Notify a fatal error."""
        self.message(FATAL, *values)

    def progress(self, title: str) -> Progress:
        """Start a lengthy task section and periodically indicate the progress."""
        ...

    def guest(self, guest_name: str, *values: Any) -> None:
        """Print a serial/SSH message sent by the guest"""
        ...

    def section(self, title: str) -> ContextManager:
        """Indicate the start of a program 'section'.

        For instance, 'Building image', or 'Powering down machine'.

        Examples:

            To use the nesting functionality, simply write::

                # ... some high level functionality
                with ui.section():
                    # ... sub-functions with lower level of importance
        """
        ...

    def items(
        self,
        *values: str | tuple[str, str],
        separator: str = ": ",
    ) -> None:
        """Print a list of items.

        Args:
            values: If a sequence of strings is given, the list is printed
                itemized with the default icon. If a list of pairs of strings
                is given, the first element of the pair is used as an icon.
            itemize: If set to ``True``, the function may prepend an item icon
                before each element of the list.
            separator: String to insert between the first and second element of the
                pair (if a pair is supplied, otherwise is ignored).

        Examples:

            Print a checklist:

                >>> ui.items([("[x]", "Boot machine"),
                ...           ("[ ]", "Wait for SSH"),
                ...           ("[ ]", "Execute commands")], itemize=False)
                [x] Boot machine
                [ ] Wait for SSH
                [ ] Execute commands
        """
        ...

    I = TypeVar("I")

    def select(
        self,
        *elems: I,
        default: None | I,
        no_user: Literal["default", "raise", "none"] = "default",
        fmt: Callable[[I], str] = str,
        prompt: None | str = None,
    ) -> I | None:
        """Ask the user to select one of *elems*.

        Args:
            elems: The available elements.
            default: Value pre-selected and return if user is not available.
            no_user: The action if the user is not present.

        Returns:
            The element selected by the user, or `None` if the user quited
            the selection (for instance by pressing CTRL-C), or no option
            was selected.
        """
        ...

    T = TypeVar("T")

    def iterate(
        self,
        iterable: Iterable[T],
        fmt: Callable[[T], str] = str,
    ) -> Iterator[T]:
        """Iterate over *iterble*, while pretty printing the iteration status.

        The function is design to notify the user about the execution of a
        known number of steps.

        Args:
            iterable: An iterable containing all the elements that are going to be
                processed.
            fmt: Function to use to string-ify the each value.

        Examples:

            To use the functionality wrap the iterable in ``ui.iterate(...)``::

                for i in ui.iterate(range(10)):
                    pass

                # [ 1/10]
                # [ 2/10]
                # ...
                # [10/10]
        """
        ...

    def tabulate(
        self,
        data: Sequence[Sequence[Any]],
        headers: None | Sequence[str] = None,
    ) -> None:
        """Output information as a table.

        Args:
            data: A *list* of *lists*, where each inner list is a row.
                Same as ``tabulate.tabulate()``.
            headers: A list of headers. This may be converted to uppercase for
                consistency.
        """
        ...


_ui: UI


def instance(new: None | UI = None) -> UI:
    """Get or override the current instance"""
    global _ui
    if new is not None:
        _ui = new
    return _ui
