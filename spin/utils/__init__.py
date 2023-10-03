"""Support module containing common utilities"""
from __future__ import annotations

import pathlib
import re
from typing import Literal

from spin.utils.sizes import Size

from . import _ui_fancy, _ui_log, ui

uuid_re = re.compile(
    "^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def isuuid(value: str) -> bool:
    """Check if a string is a valid UUID.

    Args:
        value: The string to check.

    Return:
        ``True`` if the value is a valid UUID, ``False`` if not.
    """
    return uuid_re.match(value) is not None


def content(file: pathlib.Path | str, encoding: str = "utf8") -> str:
    """Return the contents of the file as a string"""

    file = pathlib.Path(file).expanduser().resolve()
    with open(file, "r", encoding=encoding) as stream:
        return stream.read()


def init_ui(
    mode: Literal["log", "fancy", "auto"] = "auto",
    verbosity_level: int = ui.WARNING,
) -> None:
    """Return the best suited UI for the current invocation"""

    if mode == "fancy" or (mode == "auto" and _ui_fancy.FancyUI.check_env()):
        ui.instance(_ui_fancy.FancyUI(verbosity_level))
    else:
        ui.instance(_ui_log.LogUI(verbosity_level))
