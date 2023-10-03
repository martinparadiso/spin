"""Stop a machine
"""

from __future__ import annotations

import pathlib
from multiprocessing.pool import ThreadPool

from spin.cli._utils import load
from spin.errors import NoBackend
from spin.machine.machine import Machine
from spin.utils import ui

TIMEOUT = 30


def send_signal(m: Machine) -> tuple[Machine, bool]:
    """Send the actual shutdown signal to a machine

    Returns: ``True`` on success, ``False`` if the backend reports the machine
        as running at the end of the function.
    """
    assert m.backend is not None and not isinstance(m.backend, type)
    acpi_ok, acpi_msg = m.backend.acpi_shutdown(timeout=TIMEOUT)
    if not acpi_ok or m.backend.is_running():
        ui.instance().warning(f"Machine running after {TIMEOUT} seconds. Forcing stop")
        force_stop_ok, fs_msg = m.backend.force_stop()
        if not force_stop_ok:
            ui.instance().error("Could not force stop m.")
            if acpi_msg:
                ui.instance().error(f"Backend: {fs_msg}")
    if m.backend.is_running():
        return m, False
    return m, True


def down(*machines: str | pathlib.Path | Machine) -> int:
    """Stop a running machine

    Args:
        machine: The machine to stop.

    Raises:
        ValueError: If the machine cannot be found in the backend.

    Returns:
        A returncode, where:
            - ``0`` means no failure,
            - ``1`` if a machine is still running, and
            - ``2`` a machine could not be loaded.
    """

    if len(machines) == 0:
        raise ValueError("Need at least one machine")
    ms: list[Machine] = []
    for machine in machines:
        if not isinstance(machine, Machine):
            loaded_machines = load(machine, disable_definition=True)
        else:
            loaded_machines = [machine]

        for m in loaded_machines:
            if m.backend is None or isinstance(m.backend, type):
                raise NoBackend
            if not m.backend.exists():
                ui.instance().warning("Machine not present in the backend")
                return 2

            if not m.backend.is_running():
                ui.instance().warning("Machine not running")
                return 2
            ms.append(m)

    if not ms:
        ui.instance().warning("No machine(s) found")
        return 0

    with ThreadPool(processes=len(ms)) as pool:
        statuses = pool.map(send_signal, ms)

    for m, ok in statuses:
        if not ok:
            ui.instance().error(f"Could not stop machine {m.name}")

    if not all(ok for _, ok in statuses):
        return 1

    return 0
