"""Loading functionality.

The module covers the loading of all type of objects and ``spinfile``.
"""

from __future__ import annotations

import json
import pathlib
from uuid import uuid4

import spin.define
import spin.machine.network
from spin import errors
from spin.machine.machine import Group, Machine
from spin.utils import ui
from spin.utils.config import conf


def machinefile(path: pathlib.Path) -> list[Machine]:
    """Load `Machine` (s) from a machine file.

    Args:
        path: The path to the ``json`` file containing the definition.

    Returns:
        A list of all the machines stored in the file.
    """
    return Machinefile(path).load()


class FileManager:
    """Manages files owned or associated with a given Machine"""

    def __init__(self, root: pathlib.Path) -> None:
        self.root = root

    def add(self, machine: Machine, name: str) -> pathlib.Path:
        """Create a file in the host filesystem, which belongs to *machine*.

        The file will be destroyed together with the Machine.

        Args:
            machine: The machine associated with the given file.
            name: The name of the new file.

        Returns:
            The path of the *new* file.
        """
        parent = self.root / machine.uuid
        if not parent.exists():
            parent.mkdir()
        file = parent / name
        return file

    def get(self, machine: Machine, name: str) -> None | pathlib.Path:
        """Retrieve the file stored as *name*.

        Args:
            machine: The machine associated with the given file.
            name: The name of the file to retrieve.

        Returns:
            A `Path` to the file; or `None` if there is no file under
            that name.
        """
        file = self.root / machine.uuid / name
        if not file.exists():
            return None
        return file

    def get_all(self, machine: Machine) -> list[pathlib.Path]:
        """Retrieve all the files associated with *machine*.

        Return:
            The list of files associated with *machine*. Can be empty.
        """
        folder = self.root / machine.uuid
        if not folder.exists():
            return []
        return [item for item in folder.iterdir() if item.is_file()]


class Spinfolder:
    """Represents a ``.spin`` folder. Not neccessarely created yet."""

    def __init__(
        self,
        machine: None | Machine = None,
        location: None | pathlib.Path = None,
        parent: None | pathlib.Path = None,
    ):
        """
        Args:
            machine: a Machine, with a folder already set.
            location: Exact location of the folder.
            parent: Parent folder, where the new spinfolder should be created.

        Raises:
            ValueError: If all parameters are ``None``.
            ValueError: If two or more parameters have a value.
        """

        if len([arg for arg in (machine, location, parent) if arg is not None]) != 1:
            raise ValueError("You must provide exactly one parameter")

        if location is None:
            if machine is not None:
                if machine.folder is None:
                    raise errors.MissingAttribute(machine, "folder")
                location = machine.folder
            elif parent is not None:
                location = parent / conf.default_machine_folder

        if location is None:  # Note: here for type-checkers
            raise ValueError("You must provide exactly one parameter")

        self.location: pathlib.Path = location
        """Exact location of this spinfolder"""

        self.machinefile: None | Machinefile = None
        """File where machine data is stored"""

        if (
            self.location.exists()
            and self.location.is_dir()
            and self.location / conf.default_machine_file
        ):
            self.machinefile = Machinefile(self.location / conf.default_machine_file)

    def exists(self) -> bool:
        """Check if the folder exists.

        Returns:
            ``True`` if the folder exists; ``False`` otherwise
        """
        requirements = [
            self.location.exists(),
            self.location.is_dir(),
            self.machinefile is not None,
        ]
        return all(requirements)

    def init(self) -> None:
        """Initialize the folder

        Raises:
            ValueError: If the folder exists, and it is not empty.
            ValueError: If the path is already in use by another type of file.
        """
        if self.location.exists() and not self.location.is_dir():
            raise ValueError(f"Path {self.location} already in use.")

        if self.location.exists() and len([*self.location.iterdir()]) != 0:
            raise ValueError(f"Folder {self.location} present and not empty")

        self.location.mkdir(parents=False, exist_ok=True)
        self.machinefile = Machinefile(self.location / conf.default_machine_file)
        self.machinefile.init()

    def delete(self) -> None:
        """Delete this folder from the filesystem.

        Note: The folder is deleted only if all the files inside
        can be removed
        """

        def recursive_delete(path: pathlib.Path):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                for elem in path.iterdir():
                    recursive_delete(elem)
                try:
                    path.rmdir()
                except OSError as exce:
                    ui.instance().warning(
                        f"Could not delete directory {str(path)}: {exce}"
                    )
            else:
                ui.instance().notice(f"Ignoring non-regular file: {str(path)}")

        if self.machinefile is not None:
            self.machinefile.path.unlink()
            self.machinefile = None
        recursive_delete(self.location)

    def save_machine(self, machine: Machine, *, update: bool = False) -> None:
        """Save *machine* in this folder.

        Args:
            machine: The machine to save.
            update: If set to `True`, the machine will be updated if already
                present in this folder. If set to ``False`` and the machine
                is present, an Exception is raised.
        """
        if self.machinefile is None:
            raise ValueError("Missing machinefile / folder not initialized")
        self.machinefile.save(machine, update=update)

    def delete_machine(self, machine: Machine, *, associated_files: bool) -> None:
        """Delete machine(s) from this file.

        Args:
            machines: Machine to delete
            associated_files: Remove files marked as 'owned' by this machine.

        Raises:
            ValueError: If the machine could not be found.
        """
        if self.machinefile is None:
            raise ValueError("Missing machinefile / folder not initialized")
        self.machinefile.delete(machine)
        if associated_files:
            for file in FileManager(self.location).get_all(machine):
                file.unlink()

    def get_machine(
        self, *, uuid: None | str = None, name: None | str = None
    ) -> list[Machine]:
        """Retrieve the machine indicated by *uuid* or *name*.

        Args:
            uuid: The UUID of the machine to search.
            name: The name of the machine to search.

        Returns:
            A list containing all the machines matching the given criteria.
        """

        # TODO: overlaod this function; if a UUID is supplied; the
        # return should be ``None | Machine``
        if uuid is not None and name is not None:
            raise ValueError("Supply either `uuid` or `name`")
        if self.machinefile is None:
            raise ValueError("Missing machinefile / folder not initialized")

        def filter_function(machine: Machine) -> bool:
            if uuid is not None:
                return machine.uuid == uuid
            if name is not None:
                return machine.name == name
            return True

        return [*filter(filter_function, self.machinefile.load())]

    def add_file(self, machine: Machine, name: str):
        """Add a file associated with the given machine.

        See `FileManager.add`.
        """
        return FileManager(self.location).add(machine, name)

    def get_file(self, machine: Machine, name: str):
        """Get the file stored as *name* associated with the given machine.

        See `FileManager.get`.
        """
        return FileManager(self.location).get(machine, name)

    def get_files(self, machine: Machine):
        """Get the all the files associated with the given machine.

        See `FileManager.get_all`.
        """
        return FileManager(self.location).get_all(machine)


class Groups:
    """Persistent group management"""

    @classmethod
    def _read_file(cls) -> dict[str, Group.Serialized]:
        return json.loads(conf.groups_file.read_text("utf8"))

    @classmethod
    def save(cls, group: Group, *, update: bool = False) -> None:
        """Save the group to disk.

        Args:
            group: The group to save.
            update: If set to `True`, the group will be updated if already
                present. If set to ``False`` and the group is present, an
                Exception is raised.
        """
        groups = cls._read_file()
        if group.uuid in groups and update is False:
            raise ValueError("Group already exists")
        groups[group.uuid] = group.dict()
        serialized = json.dumps(groups)
        conf.groups_file.write_text(serialized)

    @classmethod
    def load(cls, uuid: str) -> None | Group:
        """Load the group stored under the given UUID"""
        serial = cls._read_file().get(uuid, None)
        if serial is None:
            return None
        return Group.restore(serial)

    @classmethod
    def delete(cls, group: Group) -> None:
        """Delete *group* from disk.

        Raises:
            ValueError: If the group is not present in the disk.
        """
        groups = cls._read_file()
        if group.uuid not in groups:
            raise ValueError("Group not present")
        groups.pop(group.uuid)
        serialized = json.dumps(groups)
        conf.groups_file.write_text(serialized)


def load_network(
    ref: spin.machine.network.LAN.Reference,
) -> None | spin.machine.network.LAN:
    """Load a network from persistent storage"""
    serial_nets: dict[
        spin.machine.network.LAN.Reference, spin.machine.network.LAN.Serialized
    ] = json.loads(conf.networks_file.read_text("utf8"))
    if ref not in serial_nets:
        raise errors.NotFound(ref)
    return spin.machine.network.LAN(**serial_nets[ref])


class SpinfileGroup(Group):
    """Group Machines defined in the same ``spinfile``"""

    class Serialized(Group.Serialized):
        spinfile_path: str
        spinfolder: None | str
        network: None | spin.machine.network.LAN.Reference

    def __init__(
        self,
        spinfile_path: pathlib.Path | str,
        spinfolder: None | pathlib.Path | str = None,
        network: None
        | spin.machine.network.LAN
        | spin.machine.network.LAN.Reference = None,
        uuid: None | str = None,
    ) -> None:
        """
        Args:
            spinfile_path: Path to the spinfile where the machines are defined.
            spinfolder: Spinfolder where all the data is (or is going to be) stored.
            network: The network that the machines *may* share.
            uuid: Th uuid of the group.
        """
        self.spinfile: pathlib.Path = pathlib.Path(spinfile_path)
        """The path to the spinfile where this machines are defined"""

        self.machines: list[Machine] = []
        self.folder = None if spinfolder is None else pathlib.Path(spinfolder)
        self.network: None | spin.machine.network.LAN = None
        self.uuid = uuid or str(uuid4())
        self.autodestroy = True

        if self.folder is not None:
            self.machines = Spinfolder(location=self.folder).get_machine()

        if network is not None:
            if isinstance(network, str):
                network = load_network(network)
            self.network = network

    def dict(self) -> Serialized:
        return {
            "cls": self.__class__.__qualname__,
            "mod": self.__class__.__module__,
            "uuid": self.uuid,
            "spinfile_path": str(self.spinfile),
            "spinfolder": None if self.folder is None else str(self.folder),
            "network": None if self.network is None else self.network.uuid,
        }


def deserialize_machine(data: dict) -> Machine:
    """Deserialize the machine stored in *data*

    Returns:
        The Machine reconstructed from *data*.
    """
    extra: dict = {}
    gref = data["group"]
    if gref is not None:
        extra["group"] = Groups.load(gref)
    new = {k: v for k, v in data.items() if k not in extra}
    return Machine(**new, **extra)


class Machinefile:
    """Manage save and load of machinefile(s).

    The save and load functionality is simple, but it is centralized
    here to avoid code duplication.
    """

    def __init__(self, path: pathlib.Path) -> None:
        """
        Args:
            path: path to the machinefile.
        """
        self.path = path

    def init(self) -> None:
        """Initialize the machinefile"""
        if self.path.exists():
            raise ValueError("File already exists")
        self.path.write_text("[]", encoding="utf8")

    def load(self) -> list[Machine]:
        """Load the machines found in the machinefile."""
        with open(self.path, "r", encoding="utf8") as stream:
            data: list[dict] = json.load(stream)
        ret: list[Machine] = []
        for entry in data:
            ret.append(deserialize_machine(entry))

        return ret

    def save(self, *machines: Machine, update: bool = False) -> None:
        """Save machine(s) in this folder.

        Args:
            machines: Machine(s) to save in this folder `Machinefile`.
            update: If set to ``True``, overwrite machines found with same
                UUID. If it is set to ``False``, ValueError will be raised
                when a machine with the same UUID exists.

        Raises:
            ValueError: If no machine is provided.
            ValueError: If the folder is not initiated.
            ValueError: If a machine with same UUID already exists.
        """
        if len(machines) == 0:
            raise ValueError("At least one machine needs to be provided")

        existing = self.load()
        already_present = []

        for machine in machines:
            same_uuid = [*filter(lambda vm: vm.uuid == machine.uuid, existing)]
            if len(same_uuid) > 0:
                already_present.extend(same_uuid)

        if len(already_present) > 0 and update is False:
            raise ValueError(f"Machine(s) already present in file: {already_present}")

        for to_update in already_present:
            existing.remove(to_update)

        existing.extend(machines)

        data = [m.dict() for m in existing]
        serialized = json.dumps(data)
        with open(self.path, "w", encoding="utf8") as stream:
            stream.write(serialized)

    def delete(self, *machines: Machine, exact_match: bool = False) -> None:
        """Delete machine(s) from this file.

        Args:
            machines: Machine(s) to save in this folder `Machinefile`.
            exact_match: If set to ``False``, the function will compare
                machines only by UUID. If set to ``True`` the standard
                __eq__ comparison is used.

        Raises:
            ValueError: If no machine is provided.
            ValueError: If a machine is missing.
        """

        if len(machines) == 0:
            raise ValueError("At least one machine needs to be provided")

        existing = self.load()

        def should_be_removed(machine: Machine) -> bool:
            if exact_match:
                return machine in machines
            return machine.uuid in [vm.uuid for vm in machines]

        to_remove = [*filter(should_be_removed, existing)]

        if len(to_remove) < len(machines):
            raise ValueError("Could not find all machines")

        for vm in to_remove:
            existing.remove(vm)

        data = [m.dict() for m in existing]
        serialized = json.dumps(data)
        with open(self.path, "w", encoding="utf8") as stream:
            stream.write(serialized)
