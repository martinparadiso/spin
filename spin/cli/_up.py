"""Bring up machines, both new and already created.
"""
from __future__ import annotations

import pathlib
from typing import Literal, overload

from spin.build.builder import Builder, ImageDefinition
from spin.cli._utils import load
from spin.image.database import Database
from spin.machine.machine import Machine, has_backend, is_created, is_defined
from spin.machine.processor import MachineProcessor
from spin.utils import ui


@overload
def up(
    *machines: pathlib.Path | Machine | str,
    track: bool = True,
    print_console: bool = False,
    return_machines: Literal[True],
) -> list[Machine]:
    ...


@overload
def up(
    *machines: pathlib.Path | Machine | str,
    track: bool = True,
    print_console: bool = False,
    return_machines: Literal[False] = False,
) -> int:
    ...


@overload
def up(
    *machines: pathlib.Path | Machine | str,
    track: bool = True,
    print_console: bool = False,
    return_machines: bool,
) -> int | list[Machine]:
    ...


def up(
    *machines: pathlib.Path | Machine | str,
    track: bool = True,
    print_console: bool = False,
    return_machines: bool = False,
) -> int | list[Machine]:
    """Bring up a machine.

    The machine is searched with :py:func:`spin.cli.load.load`.

    Args:
        machines: The machine(s) to start, see above for possible types and values.
        track: If set to ``True``, the machine is stored in the tracker for future
            use.
        print_console: If set to ``True``, the guest console port is printed to
            stdout.

    Raises:
        ValueError: If the machine could not be found.
        ValueError: If when looking up by name, more than one machine is found.
    """
    if len(machines) == 0:
        raise ValueError("Need at least one machine")
    machines_: list[Machine] = []
    for machine in machines:
        if not isinstance(machine, Machine):
            found_machine = load(machine, disable_definition=True)
            if found_machine is None:
                raise ValueError("Could not found machine")
        else:
            found_machine = [machine]

        machines_.extend(found_machine)

    processors = [MachineProcessor(m, track=track) for m in machines_]

    for proc in filter(lambda p: not is_defined(p.machine), processors):
        proc.complete_definition()

    # HACK: Should this be here? Or should be inside the create() process
    for m in machines_:
        if isinstance(m.image, ImageDefinition):
            builder = Builder(m.image)
            builder.prepare()
            result = builder.build()
            m.image = result.image

    for proc in filter(
        lambda p: has_backend(p.machine) and not p.machine.backend.exists(),
        processors,
    ):
        proc.create()

    for proc in filter(
        lambda p: has_backend(p.machine) and not p.machine.backend.is_running(),
        processors,
    ):
        proc.start(print_console=print_console)

    if return_machines:
        return machines_
    return 0
