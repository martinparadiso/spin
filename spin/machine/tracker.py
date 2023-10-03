"""A machine manager, mainly for managing all the machines
"""

from __future__ import annotations

import json
import pathlib
import warnings
from typing import Optional, overload

from spin.errors import Bug, NotFound
from spin.machine.machine import Machine
from spin.utils.config import conf
from spin.utils.constants import MACHINE_STATE_LITERAL
from spin.utils.load import Spinfolder


class Tracker:
    """Manage all the machines running under the current user"""

    def list_machines(
        self, status: Optional[MACHINE_STATE_LITERAL] = "RUNNING"
    ) -> list[Machine]:
        """Return a list of all the found machines

        Warning:
            Some machines can be *mocks*: they were found in the track file,
            but their folder is missing.

        Args:
            status: The machine status. All the machines returned are guaranteed
                to be in that state. If ``None``, all the machines are returned,
                independently of their state.

        Returns:
            A list containing all the machines found.
        """

        from spin.cli._utils import load

        with open(conf.tracker_file) as f:
            data = json.load(f)

        ret = []
        for uuid, folder in data.items():
            try:
                machines = load(pathlib.Path(folder).parent, True)

            except NotFound:
                machine = Machine()
                machine.uuid = uuid
                machine.folder = pathlib.Path(folder)
                machines = [machine]
            except Exception as e:
                warnings.warn(str(e))
                continue

            for machine in machines:
                if status is None or machine.state == status:
                    ret.append(machine)

        return ret

    def add(self, machine: Machine) -> None:
        """*Voluntarely* add (or update) a machine to the tracker.

        The machine will later be reported when :py:func:`list_machines` is
        called.

        Args:
            machine: The machine to register or update. Must have UUID and
                folder.

        Raises:
            ValueError: If ``machine`` has no UUID and/or folder.
        """
        if machine.folder is None:
            raise ValueError("Machine has no folder")
        track_file = conf.tracker_file

        with open(track_file, "r") as f:
            # uuid -> spinfolder
            data: dict[str, str] = json.load(f)

        data[machine.uuid] = str(machine.folder.absolute())

        as_json_str = json.dumps(data)
        with open(track_file, "w") as f:
            f.write(as_json_str)

    def remove(self, machine: Machine) -> bool:
        """Un-track a machine.

        Args:
            machine: The machine to remove from the tracker.

        Raises:
            ValueError: If the provided machine has no UUID.

        Return:
            ``True`` if the machine was removed, ``False`` otherwise.
        """
        track_file = conf.tracker_file
        with open(track_file, "r") as f:
            data: dict[str, str] = json.load(f)

        if machine.uuid not in data.keys():
            return False

        data.pop(machine.uuid)

        as_json_str = json.dumps(data)
        with open(track_file, "w") as f:
            f.write(as_json_str)

        return True

    @overload
    def find(self, *, name: str) -> list[Machine]:
        ...

    @overload
    def find(self, *, uuid: str) -> None | Machine:
        ...

    def find(
        self, *, name: None | str = None, uuid: None | str = None
    ) -> None | Machine | list[Machine]:
        """Find a machine in the database.

        Args:
            name: Lookup the machine by name. A list of machines matching the
                name is returned. If no machines are found, the value is None.
            uuid: Lookup the machine by UUID. A single :py:class:`Machine` object
                --or ``None``-- is returned.

        Returns:
            When looking up by *name*, a list with all the matching Machines.
            The list can be empty.

            When looking by UUID, a single :py:class:`Machine` object or
            ``None``.
        """
        if name is not None and uuid is not None:
            raise ValueError("Cannot pass name and uuid at the same time.")

        track_file = conf.tracker_file
        with open(track_file, "r") as f:
            data: dict[str, str] = json.load(f)

        if uuid is not None:
            if uuid not in data.keys():
                return None
            try:
                spinfolder = Spinfolder(location=pathlib.Path(data[uuid]))
                matching = spinfolder.get_machine(uuid=uuid)
                if len(matching) == 0:
                    return None
                if len(matching) > 1:
                    raise Bug("Found multiple machines stored with same UUID")
                return matching[0]
            except FileNotFoundError:
                # TODO: Raise a warning if the machine is not present
                # in the 'tracked' directory.
                return None

        from spin.cli._utils import load

        machines = []
        for uuid in data:
            try:
                new_machines = load(pathlib.Path(data[uuid]).parent, True)
            except NotFound:
                continue
            except Exception as e:
                warnings.warn(str(e))
                continue
            for machine in new_machines:
                if machine.name == name:
                    machines.append(machine)
        return machines
