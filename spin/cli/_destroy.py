"""Completely remove a machine and it's devices"""


from __future__ import annotations

import pathlib

from spin.cli._utils import load
from spin.machine.machine import Machine, has_backend
from spin.machine.processor import MachineProcessor


def destroy(machine: str | pathlib.Path | Machine, remove_disk: bool = False) -> int:
    """Remove the given machine.

    Args:
        machine: The machine to destroy.
        remove_disk: If set to ``True`` remove all associated disks.

    Raises:
        ValueError: If the machine is running.
    """
    if not isinstance(machine, Machine):
        machines = load(machine, disable_definition=True)
    else:
        machines = [machine]

    for vm in machines:
        if has_backend(vm) and vm.backend.exists() and vm.backend.is_running():
            raise ValueError("Cannot destroy a running machine")

        MachineProcessor(vm).destroy(delete_storage=remove_disk)
    return 0
