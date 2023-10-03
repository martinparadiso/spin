"""List machines
"""

from __future__ import annotations

import pathlib

from spin.utils import ui
from spin.utils.config import conf


def list_machines(
    *, full_uuid: bool = False, list_all: bool = False, path: bool = False
) -> list[list[str]]:
    """Print the list of machines requested

    By default, returns only running machines. If ``list_all`` is set to
    ``True``, machines that are paused are also listed.

    Args:
        full_uuid: If set to ``False``, print only the first 8 characters of
            the UUID.
        list_all: List non-running machines.
        path: Print the path to the *machinefolder* where the machine metadata
            is stored.

    Returns:
        The generated data, in the form of a matrix. *With* the header.
    """

    from spin.machine.tracker import Tracker

    header = ["UUID", "IMAGE", "CREATED", "STATUS", "NAME"]
    if path:
        header.append("FOLDER")
    data: list[list[str]] = []

    tr = Tracker()
    machines = tr.list_machines(status="RUNNING" if not list_all else None)

    for m in machines:
        folder = str(m.folder.parent) if m.folder is not None else ""
        if folder.startswith(str(pathlib.Path.home())):
            folder = folder.replace(str(pathlib.Path.home()), "~", 1)
        uuid = str(m.uuid) if full_uuid else str(m.uuid)[:8]
        if m.folder is not None and not m.folder.exists():
            image = ""
            tag = ""
            created = ""
        else:
            image = str(m.image.name) if m.image is not None else "Unknown"
            tag = (":" + str(m.image.tag)) if m.image is not None else ""
            created = ""  # HACK: Implement machine creation date
            if m.backend is None or isinstance(m.backend, type):
                # FIXME: Why are we setting a backend here?
                new_backend = conf.default_backend()()
                m.backend = new_backend.machine(m)

        machine = [uuid, image + tag, created, m.status.capitalize(), m.name or ""]
        if path:
            machine.append(folder)
        if not list_all and m.state != "RUNNING":
            continue
        data.append(machine)

    ui.instance().tabulate(data, headers=header)

    return [header, *data]
