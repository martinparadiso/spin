"""Common utilities for the CLI interface"""

from __future__ import annotations

import pathlib

import spin.define
import spin.utils.load
import spin.utils.spinfile_loader
from spin.errors import NotFound
from spin.machine.machine import Machine
from spin.machine.tracker import Tracker
from spin.utils import isuuid, ui
from spin.utils.config import conf
from spin.utils.load import Machinefile


def load(search_by: str | pathlib.Path, disable_definition: bool) -> list[Machine]:
    """Load a machine from a UUID, path or name.

    The function will try to auto-detect the user-submitted value to determine
    if it is an UUID, Path or name.

    Args:
        machine: A way to identify the machine to load. For a string the value
            can be a UUID, a name, or a relative or absolute path. For strings,
            the value is matched against a UUID regular expression, if successful
            the machine is searched by UUID. If the string starts with ``"/"``
            or ``"."``, the value is understood as a Path. At last, if neither
            an UUID or a path is detected, the machine is searched by name.
        disable_definition: If set to ``True``, the ``with spin.define.vm``
            statements found will have no side-effects (such as searching
            for valid images).

    Raises:
        NotFound: If no ``spinfile.py`` or ``.spin`` folder could be found in
            the provided path.

    Returns:
        A list containing all the :py:class:`Machine`s found.

    """

    machine: None | Machine = None

    # HACK: We have a circular dep. problem; we *should* read the
    # magic auto-detect token from a constant
    if search_by == "-":
        search_by = "."

    if isinstance(search_by, str):
        if isuuid(search_by):
            ui.instance().debug("Searching machine by uuid")
            tracker = Tracker()
            machine = tracker.find(uuid=search_by)
            if machine is None:
                raise NotFound(search_by)
            return [machine]
        if search_by.startswith(("/", ".")):
            search_by = pathlib.Path(search_by)
        else:
            ui.instance().debug("Searching machine by name")
            tracker = Tracker()
            return tracker.find(name=search_by)

    if isinstance(search_by, pathlib.Path):
        ui.instance().debug("Searching machine by path")

        machinefolder = search_by / conf.default_machine_folder
        if search_by.is_file():
            spinfile = search_by
        else:
            spinfile = search_by / "spinfile.py"

        if (not machinefolder.exists() or not machinefolder.is_dir()) and (
            not spinfile.exists() or not spinfile.is_file()
        ):
            raise NotFound((str(machinefolder), str(spinfile)))

        if machinefolder.exists():
            return Machinefile(
                search_by / conf.default_machine_folder / conf.default_machine_file
            ).load()
        found = spin.utils.spinfile_loader.spinfile(
            spinfile, disable_definition=disable_definition
        )

        return [m for m in found if isinstance(m, Machine)]

    raise TypeError("Invalid type for argument machine")
