"""Fancy UI with progress, animations and colors"""

from __future__ import annotations

import dataclasses
import os
import re
import sys
import warnings
from contextlib import contextmanager
from typing import (
    Any,
    Callable,
    ContextManager,
    Iterable,
    Iterator,
    Literal,
    NamedTuple,
    Protocol,
    Sequence,
    Sized,
    TextIO,
    Type,
    TypeVar,
)

import tabulate

from spin.utils import ui

ANSI_FG_COLOR: dict[ui.COLORS_LITERAL | str, int] = {
    "black": 30,
    "red": 31,
    "green": 32,
    "yellow": 33,
    "blue": 34,
    "magenta": 35,
    "cyan": 36,
    "white": 37,
    "gray": 90,
    "bright_red": 91,
    "bright_green": 92,
    "bright_yellow": 93,
    "bright_blue": 94,
    "bright_magenta": 95,
    "bright_cyan": 96,
    "bright_white": 97,
}

ANSI_BG_COLOR: dict[ui.COLORS_LITERAL | str, int] = {
    "black": 40,
    "red": 41,
    "green": 42,
    "yellow": 43,
    "blue": 44,
    "magenta": 45,
    "cyan": 46,
    "white": 47,
    "gray": 100,
    "bright_red": 101,
    "bright_green": 102,
    "bright_yellow": 103,
    "bright_blue": 104,
    "bright_magenta": 105,
    "bright_cyan": 106,
    "bright_white": 107,
}

ANSI_ESC = "\x1B"
ANSI_CSI = ANSI_ESC + "["
ANSI_END_SGR = "m"


@dataclasses.dataclass
class State:
    foreground: int = 39
    background: int = 49
    bold: bool = False
    italic: bool = False
    underline: bool = False


def transition(from_: State, to: State) -> str:
    """Generate a sequence of escape codes to move from *from* to *to*"""
    seq = ""

    def _toggle(key: str, activate: int, deactivate: int):
        nonlocal seq
        if getattr(from_, key) is False and getattr(to, key) is True:
            seq += ANSI_CSI + str(activate) + ANSI_END_SGR
        if getattr(from_, key) is True and getattr(to, key) is False:
            seq += ANSI_CSI + str(deactivate) + ANSI_END_SGR

    _toggle("bold", 1, 22)
    _toggle("italic", 3, 23)
    _toggle("underline", 4, 24)

    if from_.foreground != to.foreground:
        seq += ANSI_CSI + str(to.foreground) + ANSI_END_SGR
    if from_.background != to.background:
        seq += ANSI_CSI + str(to.foreground) + ANSI_END_SGR

    return seq


class FancyFormatter(ui.Formatter):
    def __init__(self) -> None:
        self.state_stack = [State()]

    def state(self, new_state: State, string: str) -> str:
        pre = transition(self.state_stack[-1], new_state)
        post = transition(new_state, self.state_stack[-1])
        return pre + string + post

    def color(self, color: ui.COLORS_LITERAL | str, string: str) -> str:
        if color in ANSI_BG_COLOR:
            state = dataclasses.replace(
                self.state_stack[-1], foreground=ANSI_FG_COLOR[color]
            )
            return self.state(state, string)

        # TODO: warn about unknown color
        return string

    def emph(self, string: str) -> str:
        state = dataclasses.replace(self.state_stack[-1], italic=True)
        return self.state(state, string)

    def strong(self, string: str) -> str:
        state = dataclasses.replace(self.state_stack[-1], bold=True)
        return self.state(state, string)

    def underline(self, string: str) -> str:
        state = dataclasses.replace(self.state_stack[-1], underline=True)
        return self.state(state, string)


_priority_mod: dict[ui.LEVEL_LITERAL, State] = {
    ui.DEBUG: State(foreground=ANSI_FG_COLOR["gray"]),
    ui.WARNING: State(foreground=ANSI_FG_COLOR["yellow"]),
    ui.ERROR: State(foreground=ANSI_FG_COLOR["red"]),
    ui.FATAL: State(foreground=ANSI_FG_COLOR["red"], bold=True),
}


class Size(NamedTuple):
    width: int
    height: int


class Widget(Protocol):
    @property
    def size(self) -> Size:
        ...

    def draw(self) -> None:
        """Draw the widget. The cursor will start at the column 0."""
        ...


class _ProgressWidget(Widget):
    chars = {"downloaded": "─", "missing": "─"}

    def __init__(self, progress: Progress) -> None:
        self.progress = progress
        self.height = 3
        self.width = 80

    @property
    def size(self) -> Size:
        return Size(self.width, self.height)

    def draw_header(self) -> None:
        clear_line()
        if self.progress.percentage is not None:
            progresstr = f"{self.progress.percentage * 100:3.1f}%"
        else:
            progresstr = "?"

        header = f"{self.progress.title:<{self.width - 20}}{progresstr:>20}"
        self.progress.ui.print(header, end="\r\n")

    def draw_bar(self) -> None:
        clear_line()
        if self.progress.percentage is None:
            complete_bars = 0
        else:
            complete_bars = int((self.width) * (self.progress.percentage))
        missing_bars = self.width - complete_bars
        bar = self.chars[
            "downloaded"
        ] * complete_bars + self.progress.ui.formatter.gray(
            self.chars["missing"] * missing_bars
        )
        self.progress.ui.print(bar, end="\r\n")

    def draw_footer(self) -> None:
        clear_line()
        self.progress.ui.print(self.progress.subtitle)

    def draw(self) -> None:
        self.draw_header()
        self.draw_bar()
        self.draw_footer()


class Progress(ui.Progress):
    def __init__(self, ui_: FancyUI, title: str, subtitle: str = "") -> None:
        self.ui = ui_
        self.percentage: None | float = 0
        self.widget: None | _ProgressWidget = None
        self.title = title
        self.subtitle = subtitle

    def __enter__(self) -> Progress:
        self.widget = _ProgressWidget(self)
        self.ui.add_widget(self.widget)
        return self

    def __exit__(self, *args) -> None:
        if self.widget is not None:
            self.ui.pop_widget(self.widget)
        self.widget = None
        return

    def update(self, percentage: None | float) -> None:
        self.percentage = percentage
        self.ui.progress_update()


def clear_down() -> str:
    return ANSI_CSI + "0J"


def clear_line() -> str:
    return ANSI_CSI + "2K"


def relative_cursor_move(x: None | int, y: None | int) -> str:
    """Move the cursor (on ANSI/xterm)"""
    ret = ""
    if y and y > 0:
        ret += ANSI_CSI + str(y) + "B"
    if y and y < 0:
        ret += ANSI_CSI + str(-y) + "A"
    if x and x > 0:
        ret += ANSI_CSI + str(x) + "D"
    if x and x < 0:
        ret += ANSI_CSI + str(-x) + "C"
    return ret


def ctrlseq(*args) -> None:
    print(*args, sep="", end="")


class FancyUI(ui.UI):
    def __init__(self, level: int) -> None:
        self.formatter = FancyFormatter()
        self.widgets: list[Widget] = []
        self.section_stack: list[str] = []
        self.level: int = level
        self.verbose: bool = False
        warnings.showwarning = self.warning_override

    def section(self, title: str) -> ContextManager:
        @contextmanager
        def _section_context():
            self.print(self.formatter.blue(title))
            self.section_stack.append(title)
            yield
            self.section_stack.pop()

        return _section_context()

    def progress(self, title: str, subtitle: str = "") -> Progress:
        return Progress(self, title=title, subtitle=subtitle)

    def message(self, level: ui.LEVEL_LITERAL, *values: str | Any) -> None:
        if level < self.level:
            return
        if level in _priority_mod:
            output = [
                self.formatter.state(_priority_mod[level], str(v)) for v in values
            ]
        else:
            output = [*values]
        self.print(*output)

    T = TypeVar("T")

    def iterate(
        self, iterable: Iterable[T], fmt: Callable[[T], str] = str
    ) -> Iterator[T]:
        def format_index() -> Iterator[str]:
            if isinstance(iterable, Sized):
                elems = f"/{len(iterable)}"
                width = len(elems) - 1
            else:
                elems = ""
                width = 0

            i = 1

            while True:
                yield f"({i:{width}}{elems})"
                i += 1

        index_formatter = format_index()

        for elem in iterable:
            with self.section(
                self.formatter.gray(next(index_formatter)) + " " + fmt(elem)
            ):
                yield elem

    def items(
        self,
        *values: str | tuple[str, str],
        separator: str = ": ",
    ) -> None:
        DEFAULT_ICON = " - "
        provides_icon = any(isinstance(v, tuple) for v in values)
        icon_length = [len(t[0]) for t in values if isinstance(t, tuple)]
        pre_length = max(icon_length) if icon_length else len(DEFAULT_ICON)

        for val in values:
            pre, content = val if isinstance(val, tuple) else DEFAULT_ICON, val
            self.print(f"{pre:<{pre_length}}", separator, content, sep="")

    def guest(self, guest_name: str, *values: Any) -> None:
        if not str(values[-1]).endswith("\n"):
            values = (*values, "↵\n")
        self.print(
            self.formatter.gray(guest_name + self.formatter.strong(" │")),
            *values,
            end="",
        )

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

        Returns:
            The element selected by the user.
        """

        def parse_select(data: str) -> None | int:
            try:
                return int(data)
            except ValueError:
                return None

        print(prompt)
        for elem in elems:
            print(f"{elems.index(elem)}) {fmt(elem)}")
        selected = parse_select(input("> "))
        while selected is None or selected >= len(elems):
            selected = parse_select(input("> "))
        return elems[selected]

    def progress_update(self) -> None:
        """Indicate the update of a progress widget"""
        for widget in self.widgets:
            widget.draw()
        move_up = 0
        for widget in self.widgets:
            move_up += widget.size.height
        ctrlseq(relative_cursor_move(0, -move_up), clear_line(), clear_down())

    @staticmethod
    def check_env() -> bool:
        """Return `True` if the UI is usable in the current context/environment"""
        return all(("TERM" in os.environ, sys.stdin.isatty(), sys.stdout.isatty()))

    def add_widget(self, widget: Widget) -> None:
        self.widgets.append(widget)

    def pop_widget(self, widget: Widget) -> None:
        self.widgets.remove(widget)

    def print(self, *values: str | Any, **kwargs) -> None:
        indent = "  " * len(self.section_stack)
        if indent:
            print(indent, end="")
        values_ = [str(v).replace("\n", f"\n{indent}") for v in values]
        print(*values_, **kwargs)

    def tabulate(
        self, data: Sequence[Sequence[Any]], headers: None | Sequence[str] = None
    ) -> None:
        if headers is None:
            s = tabulate.tabulate(data, tablefmt="plain")
        else:
            headers = [h.upper() for h in headers]
            s = tabulate.tabulate(data, headers=headers, tablefmt="plain")
        print(s)

    def warning_override(
        self,
        message: Warning | str,
        category: Type[Warning],
        filename: str,
        lineno: int,
        file: TextIO | None = None,
        line: str | None = None,
    ) -> None:
        filename = re.sub(".*spin(.*)", r"spin\1", filename)
        self.warning(str(message) + f"\n╰╴{filename}:{lineno}")
