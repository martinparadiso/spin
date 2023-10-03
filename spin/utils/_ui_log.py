"""Log style user interface"""

from __future__ import annotations

import re
import warnings
from contextlib import contextmanager
from datetime import datetime
from typing import (
    Any,
    Callable,
    ContextManager,
    Iterable,
    Iterator,
    Literal,
    Sequence,
    TextIO,
    Type,
    TypeVar,
)

import tabulate

from spin.errors import NoUserAvailable
from spin.utils import ui


class NullFormatter(ui.Formatter):
    """Perform no color in the input string"""

    def color(self, _: ui.COLORS_LITERAL | str, string: str) -> str:
        return string

    def strong(self, string: str) -> str:
        return string

    def emph(self, string: str) -> str:
        return string

    def underline(self, string: str) -> str:
        return string


class Progress(ui.Progress):
    def __init__(self, ui_: LogUI) -> None:
        self.ui = ui_
        self.progress: None | float = None

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return

    def update(self, percentage: None | float) -> None:
        self.progress = percentage


class LogUI(ui.UI):
    def __init__(self, level: int) -> None:
        self.level: int = level
        self.verbose: bool = False
        self.section_stack: list[str] = []
        warnings.showwarning = self.warning_override

    def get_leading(self, level: None | ui.LEVEL_LITERAL) -> str:
        ret = f"[{datetime.now().isoformat()}]"
        if level is not None:
            ret += f" [{ui.LEVEL_STRING[level]:^7}]"
        return ret

    def print(self, *values: str | Any, level: None | ui.LEVEL_LITERAL = None) -> None:
        print(self.get_leading(level), *values)

    def message(self, level: ui.LEVEL_LITERAL, *values: str | Any) -> None:
        if level >= self.level:
            self.print(*values, level=level)

    def guest(self, guest_name: str, *values: Any) -> None:
        if self.level > ui.DEBUG:
            return
        self.print(f" [{guest_name}]", *values)

    T = TypeVar("T")

    def iterate(
        self, iterable: Iterable[T], fmt: Callable[[T], str] = str
    ) -> Iterator[T]:
        return iter(iterable)

    def section(self, title: str) -> ContextManager:
        @contextmanager
        def _nullnest():
            self.print(title)
            self.section_stack.append(title)
            yield
            self.section_stack.pop(-1)

        return _nullnest()

    I = TypeVar("I")

    def select(
        self,
        *elems: I,
        default: None | I,
        no_user: Literal["default", "raise", "none"] = "default",
        fmt: Callable[[I], str] = str,
        prompt: None | str = None,
    ) -> I | None:
        assert len(elems) >= 2

        self.print("Automatic selecting between:", *elems)

        if no_user == "raise":
            raise NoUserAvailable

        if no_user == "none" or (no_user == "default" and default is None):
            return None

        if no_user == "default":
            return default

    def items(
        self,
        *values: str | tuple[str, str],
        itemize: bool = True,
        separator: str = ": ",
    ) -> None:
        # TODO: Should this UI print itemized lists?
        return

    def progress(self, title: str) -> Progress:
        return Progress(self)

    def tabulate(
        self, data: Sequence[Sequence[Any]], headers: None | Sequence[str] = None
    ) -> None:
        # TODO: Should we print tables while logging?
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
        self.warning(str(message) + f"\nat {filename}:{lineno}")
