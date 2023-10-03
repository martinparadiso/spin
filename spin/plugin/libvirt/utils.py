"""Common utilities for the libvirt backend"""

from __future__ import annotations

import sys
import traceback
from typing import Callable, TypeVar

from typing_extensions import ParamSpec

from spin.utils import ui

try:
    import libvirt
except ImportError as _:
    pass
P = ParamSpec("P")
T = TypeVar("T")


dumped_exceptions: set[int] = set()


def parse_exception(fun: Callable[P, T]) -> Callable[P, T]:
    """Decorator, which process exceptions raised by libvirt.

    The decorator catches the exceptions thrown by libvirt, tries
    to understand the problem, gives the user some information, and
    then re-throws the exception.

    Examples:

        Simply decorate a function::

            @parse_exception
            def make_disk(Disk) -> bool:
                # Call libvirt and try to create a disk
    """

    def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        try:
            return fun(*args, **kwargs)
        except libvirt.libvirtError as exce:
            if id(exce) not in dumped_exceptions:
                dumped_exceptions.add(id(exce))
                ui.instance().debug(
                    f"Called libvirt with args={args} and kwargs={kwargs}"
                )
                ui.instance().error(exce)
                _, __, tb = sys.exc_info()
                frame = list(traceback.walk_tb(tb))[-1][0]
                file = frame.f_globals["__file__"]
                lineno = frame.f_lineno - 1
                print(f"Error on {file}:{lineno}")
                with open(file, "r", encoding="utf8") as file:
                    content = file.readlines()
                pre_lines = content[lineno - 5 : lineno]
                post_lines = content[lineno + 1 : lineno + 6]
                for line in pre_lines:
                    print(f"  {line}", end="")
                print(f"> {content[lineno]}", end="")
                for line in post_lines:
                    print(f"  {line}", end="")
            raise

    return wrapper


SUPPORTED_NETWORKS = ("NAT", "user")
SUPPORTED_HARDDRIVE_FORMATS = ("raw", "qcow2")
