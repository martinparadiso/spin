"""Virtual machine clafs
"""

from __future__ import annotations

import dataclasses
import datetime
import importlib
import pathlib
import re
import warnings
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, List, Optional, Sequence, Type, TypeVar, cast

from pydantic import BaseModel
from typing_extensions import (
    ClassVar,
    Literal,
    Protocol,
    TypeAlias,
    TypedDict,
    TypeGuard,
)

import spin.backend.base
import spin.machine.network
from spin.build.image_definition import ImageDefinition
from spin.errors import NoBackend
from spin.image.database import LocalDatabase
from spin.image.image import Image, ImageReference
from spin.machine import core
from spin.machine.credentials import SSHCredential
from spin.machine.hardware import CDROM, NIC, Disk, SharedFolder, Storage
from spin.machine.shell_input import ShellInput
from spin.utils import Size, ui
from spin.utils.constants import MACHINE_STATE_LITERAL, FeatureLiteral

GroupReference: TypeAlias = str


class Group(Protocol):
    """Collection of related machines."""

    class Serialized(TypedDict):
        cls: str
        mod: str
        uuid: str

    Reference: ClassVar = GroupReference

    uuid: str
    """Unique identifier for the group"""

    def remove_if_empty(self) -> bool:
        """Returns ``True`` if the group should be destroyed when the last machine is removed"""
        return False

    machines: list[Machine]
    """All the machines present in this group.
    """

    network: None | spin.machine.network.LAN
    """Network shared between all machines in the group"""

    folder: None | pathlib.Path
    """The *spinfolder* shared between all machines in the group"""

    autodestroy: bool
    """If set to ``True``, delete the group when the last machine is removed"""

    def reference(self) -> str:
        """Retrieve a reference for third-party serialization.

        Currently the UUID is used for serialization
        """
        return self.uuid

    def dict(self) -> Serialized:
        """Serialize the *group*.

        The resulting dictionary *must*:

        - JSON serializable by the builtin `json` library.
        - Be able to reconstruct the original object by calling
          the class ``cls`` stored in ``mod``, and passing the
          remainder of the dictionary as keyword arguments.
        """
        ...

    @staticmethod
    def restore(data: Serialized) -> Group:
        """Deserialize a group.

        Args:
            data: A `dict`, with a serialized `Group`.

        Return:
            A `Group` implementation.
        """
        group_cls: Type[Group] = getattr(
            importlib.import_module(data["mod"]), data["cls"]
        )
        kwargs = {k: v for k, v in data.items() if k not in ("mod", "cls")}
        return group_cls(**kwargs)


F = TypeVar("F")


class Log:
    """Groups all kind of logs about a machine"""

    class Entry(TypedDict):
        """Base log entry typed-dict."""

        message_type: str
        message: str
        time: datetime.datetime

    class UserMessage(TypedDict):
        """Arbitrary user message"""

        message_type: str
        message: str

    class CommandMessage(UserMessage):
        """Log entry generated when a command is sent to the machine"""

        trigger: Literal["on_boot", "on_creation"]

    def __init__(self) -> None:
        self.messages: list[Log.Entry] = []

    @staticmethod
    def _now() -> datetime.datetime:
        """Return the time, in iso format.

        Returns:
            A :py:class:`str` containing the time the method was called, in iso
            format.
        """
        return datetime.datetime.now()

    def log(self, message: str | UserMessage):
        """Log a message, pass a :py:class:`str:` for generic messages.

        Specific logs should provide a :py:class:`Log.Entry`. The logger
        will set the time accordingly.

        Args:
            message: The message to store. If you pass a :py:class:`str` the
                function will append the necessary data. If you pass a
                :py:class:`dict` it must conform to :py:class:`UserMessage`.

        Examples:

            For instance to log a machine starting::

                def start(...):
                    self.log.log({'message_type': 'boot', 'message': 'Booting machine'})

        """
        if isinstance(message, str):
            message = Log.UserMessage(message_type="unknown", message=message)
        store: Log.Entry = {
            "time": self._now(),
            "message": message["message"],
            "message_type": message["message_type"],
        }
        self.messages.append(store)

    def __call__(self, message: str, type_: str = "unknown") -> None:
        """Quick method to call instead of :py:func:`log`.

        Equivalent to::

            log.log({"message":message, "message_type":type})

        Args:
            message: The message to log.
            type_: The type/family of message. For instance 'start', or 'boot'.
        """
        self.log({"message": message, "message_type": type_})

    def get(self, *, console: bool = True, commands: bool = True) -> list[Log.Entry]:
        """Retrieve logs, specifying what to include.

        Args:
            console: Include messages sent by the machine to the
                serial/console port.
            commands: Include commands sent to the machine. Stored in
                :py:class:`Log.Entry` dictionary.

        Return:
            A list of :py:class:`str`. Each element is a single line from the
                console port; or the command issued to the machine.
        """
        checks = [
            lambda type_: console and type_ == "console",
            lambda type_: commands and type_ == "command",
        ]
        return list(
            filter(lambda m: any(c(m["message_type"]) for c in checks), self.messages)
        )


def sanitize_multiline(multiline: str) -> str:
    """Parse a multiline string, removing unnecessary spaces

    The function removes the spaces commonly found in 'aligned' multiline
    strings. This avoids sending extra spaces when feeding multiline commands
    to a shell.

    If the received string has less than 3 lines, no processing is done.

    Args:
        multiline: The multiline :py:class:`str` to remove the leading spaces.

    Returns:
        The processed string. Or the same string if the input has less than 3
        lines.

    Examples:

        The function is designed to make the following conversion::

            a = \"""
                A multiline
                string
            \"""

            b = "A multiline\\nstr\\n"

            assert sanitize_multiline(a) == b
    """
    lines = multiline.splitlines()
    if len(lines) < 3:
        return multiline

    def leading_spaces(line: str) -> int:
        acc = 0
        for char in line:
            if char != " ":
                break
            acc += 1
        return acc

    if lines[0] == "":
        # First line is empty due to format style::
        #
        #   multiline = """
        #       ...
        #   """
        lines = lines[1:]

    if leading_spaces(lines[0]) != len(lines[0]):
        lspace = leading_spaces(lines[0])
    else:
        lspace = leading_spaces(lines[1])

    if leading_spaces(lines[-1]) < lspace:
        # Last line is also an empty line due to formatting
        lines = lines[:-1]

    return "".join(line[lspace:] + "\n" for line in lines)


def import_plugins(modules: list[ModuleType], *imports: ModuleType | str) -> None:
    """Import the serialized modules into the module list.

    Args:
        modules: The collection to store the modules in. If an exception is
            raised during load, the list remains unmodified.
        imports: The list of serialized modules.

    Raises:
        ImportError: If a given module cannot be loaded.
    """
    buf: list[ModuleType] = []
    for module in imports:
        if isinstance(module, ModuleType):
            buf.append(module)
        else:
            buf.append(importlib.import_module(module))
    modules.extend(buf)


BootOrder = List[Storage]


class Options(BaseModel):
    """Collection of toggles, switches and small options for a machine"""

    wait_for_network: bool = True
    """During boot, wait for machine to report an IP."""

    wait_for_ssh: bool = True
    """During boot, wait for SSH to become available."""


@dataclasses.dataclass
class Hardware:
    """Collection of all hardware associated with a machine"""

    class Serialized(TypedDict):
        """Serialized hardware information"""

        cpus: int
        memory: int
        network: Optional[NIC.Serialized]
        disk: Optional[Disk.Serialized]

    def __init__(
        self,
        *,
        cpus: None | int = None,
        memory: None | int | Size = None,
        network: None | NIC | NIC.Serialized = None,
        disk: None | Disk | Disk.Serialized = None,
    ) -> None:
        self.cpus: int = 2 if cpus is None else cpus
        """Number of vCPUs assigned to the machine"""

        self.memory: Size = Size("2GiB")
        """Amount of memory assigned to the machine"""

        if memory is not None:
            if isinstance(memory, int):
                self.memory = Size(memory)
            else:
                self.memory = memory

        self.network: None | NIC = NIC("NAT")
        """Main network card for the machine"""

        if network is not None:
            if isinstance(network, dict):
                self.network = NIC(**network)
            else:
                self.network = network

        self.disk: None | Disk = Disk(size=Size("10Gi"))
        """Main disk drive for the machine"""

        if disk is not None:
            if isinstance(disk, dict):
                self.disk = Disk(**disk)
            else:
                self.disk = disk

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(cpus={self.cpus},memory={self.memory})"

    def dict(self) -> Serialized:
        """Serialize the hardware into a :py:class:`dict`"""
        return {
            "cpus": self.cpus,
            "memory": self.memory.bytes,
            "disk": None if self.disk is None else self.disk.dict(),
            "network": None if self.network is None else self.network.dict(),
        }


@dataclasses.dataclass
class MachineInfo:
    """Contains information about a machine"""

    class Serialized(TypedDict):
        boots: int
        creation: Optional[str]

    def dict(self) -> Serialized:
        return cast(MachineInfo.Serialized, dataclasses.asdict(self))

    boots: int = 0
    """Number of boots *registered* by the library.
    
    If you booted the machine directly from the backend the value
    will probably not be updated.
    """

    creation: Optional[str] = None
    """Creation datetime of the machine"""


class HighLevelNetwork:
    """High level network interface"""

    def __init__(self, hardware: Hardware) -> None:
        self.hardware = hardware

    def port_forward(
        self,
        host: int,
        guest: int,
        proto: spin.machine.network.PortMapping.PROTOCOL,
        *,
        host_interface: None | str = None,
    ) -> None:
        """Forward a port(or redirect an incoming connection) from
        the host main interface to the guest.

        Args:
            host: The name of the interface on the host; if set to
                ``None``; the system will attempt to determine the
                first usable physical interface.
        """
        if self.hardware.network is None:
            raise ValueError("Machine has no NIC to forward ports")

        nic = self.hardware.network
        nic.forwarding.append(
            spin.machine.network.PortMapping(
                host=host,
                guest=guest,
                protocol=proto,
            )
        )


class Machine(core.CoreMachine):
    """Virtual machine"""

    class Serialized(TypedDict):
        """Machine serialized into a JSON friendly dictionary.

        Callbacks and special functions (such as :py:func:`gen_ssh_keys`) are
        not present.
        """

        name: Optional[str]
        folder: Optional[str]
        uuid: str
        hostname: Optional[str]
        title: Optional[str]
        description: Optional[str]
        metadata: dict[str, str]
        group: Optional[Group.Reference]
        info: MachineInfo.Serialized
        options: dict
        spinfile: Optional[str]
        image: Optional[ImageReference.Serialized]
        hardware: Hardware.Serialized
        cloud_init: Optional[str | dict]
        ignition: Optional[dict]
        autodestroy: bool
        shared_folders: list[SharedFolder.Serialized]
        diskarray: list[Storage.Serialized]
        boot_order: list[Storage.Serialized]
        hardware_virtualization: FeatureLiteral
        ssh: list[SSHCredential.Serialized]
        on_creation: ShellInput.Serialized
        on_boot: ShellInput.Serialized
        plugins: list[str]
        backend: Optional[spin.backend.base.MachineInterface.Serialized]

    def __init__(
        self,
        *,
        name: None | str = None,
        folder: None | str | Path = None,
        uuid: None | core.UUID | str = None,
        hostname: None | str = None,
        title: None | str = None,
        description: None | str = None,
        metadata: None | dict[str, str] = None,
        group: None | Group.Serialized = None,
        info: None | MachineInfo | MachineInfo.Serialized = None,
        options: None | dict = None,
        spinfile: None | str | Path = None,
        image: None | Image | ImageReference.Serialized = None,
        hardware: None | Hardware | Hardware.Serialized = None,
        cloud_init: None | dict | str | pathlib.Path = None,
        ignition: None | dict = None,
        autodestroy: bool = False,
        shared_folders: None
        | list[SharedFolder]
        | list[SharedFolder.Serialized] = None,
        diskarray: None | list[Storage] | list[Storage.Serialized] = None,
        boot_order: None | list[Storage] | list[Storage.Serialized] = None,
        hardware_virtualization: Optional[FeatureLiteral] = None,
        ssh: None | list[SSHCredential.Serialized] = None,
        on_creation: None | ShellInput.Serialized = None,
        on_boot: None | ShellInput.Serialized = None,
        plugins: None | list[str] | list[ModuleType] = None,
        backend: None | spin.backend.base.MachineInterface.Serialized = None,
    ) -> None:
        def none_or_path(arg: None | str | pathlib.Path) -> None | pathlib.Path:
            if arg is None:
                return None
            return pathlib.Path(arg)

        super().__init__(uuid)

        self.spinfile: None | pathlib.Path = none_or_path(spinfile)
        """Path to the *spinfile* that defines this machine
        
        The file exists if the machine is created through a spinfile, for
        machines created via Python library, the attribute is ``None``.
        """

        self.folder: None | pathlib.Path = none_or_path(folder)
        """Path to the folder storing all the machine information.
        
        The folder exists if the machine has been created.
        """

        self.name: None | str = name
        """Name of the VM, not necessarily unique

        If set to None, the library will set it to ``spin-{machine.uuid[:8]}``
        """

        self.hostname: None | str = hostname
        """Hostname for the Guest

        If set to None, defaults to name.
        """

        self.title: None | str = title
        self.description: None | str = description
        self.metadata: dict[str, str] = metadata or {}

        self.hardware_virtualization: FeatureLiteral = (
            "prefer" if hardware_virtualization is None else hardware_virtualization
        )
        """Determine the virtualization mode.
        
        The best performance is achieved with hardware virtualization enabled,
        but support depends on the platform (both hardware and OS).
        """

        self.image: None | Image | ImageDefinition = None
        """Image to use in the machine"""

        if isinstance(image, dict):
            ref = ImageReference(**image)
            image = LocalDatabase().get(ref.sha256)
            if image is None:
                warnings.warn(
                    f"Image not found in database: {ref}. Maybe deleted by user?"
                )
        self.image = image

        self.hardware: Hardware
        """Hardware characteristics of the machine"""

        self.group: None | Group = None if group is None else Group.restore(group)
        """Group this machine belongs to"""

        if isinstance(hardware, dict):
            self.hardware = Hardware(**hardware)
        elif hardware is not None:
            self.hardware = hardware
        else:
            self.hardware = Hardware()

        self.cloud_init: None | pathlib.Path | dict = None
        """Path to a cloud-init YAML, or it's contents on a ``dict``.

        You can pass the path to the file; or the content in the form of a
        Python :py:class:`dict`.

        Example:
            Add the user `default` SSH key to allow SSH login::

                with spin.define.vm("ubuntu", "focal") as vm:
                    vm.cloud_init = {
                        "users": [
                            "default",
                            {
                                "name": "ubuntu",
                                "ssh_authorized_keys": spin.utils.content("~/.ssh/id_rsa.pub"),
                                "sudo": "ALL=(ALL) NOPASSWD:ALL",
                            },
                        ]
                    }
        """
        if isinstance(cloud_init, str):
            self.cloud_init = pathlib.Path(cloud_init)
        else:
            self.cloud_init = cloud_init

        self.ignition: None | dict = None

        self.autodestroy: bool = autodestroy
        """Remove the machine on shutdown, defaults to False
        """

        self.shared_folders: list[SharedFolder] = []
        """Folders shared between host and guest"""

        if (
            isinstance(shared_folders, list)
            and len(shared_folders) > 0
            and all(isinstance(e, dict) for e in shared_folders)
        ):
            self.shared_folders = [
                SharedFolder(**e) for e in shared_folders if isinstance(e, dict)
            ]

        self.diskarray: Sequence[Storage] = []
        """Collection of disks in this machine"""

        if diskarray is not None:
            if len(diskarray) > 0 and all(isinstance(dev, dict) for dev in diskarray):
                self.diskarray = [
                    Storage.init_subclass(**e) for e in diskarray if isinstance(e, dict)
                ]
            else:
                self.diskarray = [e for e in diskarray if isinstance(e, Storage)]

        self.backend: Optional[
            Type[spin.backend.base.MachineInterface]
            | spin.backend.base.MachineInterface
        ] = None
        """Specify the backend to use"""

        self._boot_order: None | Sequence[Storage] = None

        if boot_order is not None and len(boot_order) > 0:
            if isinstance(boot_order[0], dict):
                boot_order = [
                    Storage.init_subclass(**e)
                    for e in boot_order
                    if isinstance(e, dict)
                ]
            self.boot_order = [e for e in boot_order if isinstance(e, Storage)]

        self.on_creation: ShellInput = (
            ShellInput(None) if on_creation is None else ShellInput(**on_creation)
        )
        """Manages shell input to execute during creation on first boot."""

        self.on_boot = ShellInput(None) if on_boot is None else ShellInput(**on_boot)
        """Manages shell input to execute during machine boot/start"""

        self.log = Log()
        """Machine logs. See :py:class:`Log` for more information"""

        self.ssh: list[SSHCredential | Callable[[], SSHCredential]] = []
        """List of SSH credentials providing access to the machine.
        
        The system will put this keys into the machine before boot.

        A :py:class:`Callable` can be used; in that case the function will
        be called during machine creation to generate the information.

        See:
            - :py:func:`gen_ssh_keys` for generation of machine-specific keys.
            - :py:func:`read_key` to read a file containing a public key.
            - :py:class:`KeyAdder` for the logic regarding how these keys are
              added to the guest machine.
        """
        if ssh is not None:
            self.ssh.extend(SSHCredential(**entry) for entry in ssh)

        self.plugins: list[ModuleType] = []
        """Collection of plugins to use in this machine.
        """

        self.info: MachineInfo
        """Guest instance information"""

        self.options: Options = Options(**(options or {}))
        """Options for this machine"""

        if info is None:
            self.info = MachineInfo()
        else:
            if isinstance(info, dict):
                self.info = MachineInfo(**info)
            else:
                self.info = info

        if plugins is not None:
            import_plugins(self.plugins, *plugins)

        if isinstance(backend, dict):
            # HACK: Implement properly
            kwargs = {k: v for k, v in backend.items() if k not in ("mod", "cls")}

            back_class: Type[spin.backend.base.Backend] = getattr(
                importlib.import_module(backend["mod"]), backend["cls"]
            )
            self.backend = back_class.load(self, **kwargs)

    def __str__(self) -> str:
        return f"{self.name}"

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(hardware={self.hardware}, backend={self.backend})"

    def __eq__(self, __o: object) -> bool:
        dont_compare = ("log",)
        me = {k: v for k, v in vars(self).items() if k not in dont_compare}
        other = {k: v for k, v in vars(__o).items() if k not in dont_compare}
        return me == other

    @property
    def state(self) -> MACHINE_STATE_LITERAL:
        """Return the most-recent state of the machine"""
        # TODO: Revisit this; probably needs more tweaks to correctly determine
        # the current state. It's too simplistic.
        if self.folder is None:
            return "DEFINED"
        if not self.folder.exists():
            return "UNKNOWN"
        if not has_backend(self) or not self.backend.exists():
            return "CREATED"
        return self.backend.state()

    @property
    def status(self) -> MACHINE_STATE_LITERAL:
        """Alias for :py:attr:`Machine.state`"""
        return self.state

    def add_disk(self, disk: Storage) -> None:
        """Add a disk to the machine.

        Args:
            disk: The disk to add
        """
        self.diskarray = [*self.diskarray, disk]

    @property
    def network(self) -> HighLevelNetwork:
        """High level interface for controlling common network tasks.

        For instance:
            - Port forwarding via `port_forward`
        """
        return HighLevelNetwork(self.hardware)

    # Machine control ----------------------------------------------------------

    def create(self, *args, **kwargs) -> None:
        """Create this machine

        Args:
            args, kwargs: forwarded to backend.create()

        Raises:
            NoBackend: If the backend attribute is set to None
            BackendError: If the creation fails in the backend side
            Exception: If the backend has not been started

        Returns:
            ``True`` on success.
        """
        if self.backend is None:
            raise NoBackend("No backend to create the machine")
        if isinstance(self.backend, type):
            raise NoBackend("Backend not connected")
        self.backend.create(*args, **kwargs)

    def start(self, *args, **kwargs):
        """Start this machine.

        Warning: pre- and post- boot commands are not called in this function.
            That logic is executed in :py:class:`MachineProcessor`.

        Args:
            args, kwargs: forwarded to backend.start()

        Raises:
            NoBackend: If the backend attribute is set to None
            BackendError: If the creation fails in the backend side
            Exception: If the backend has not been started

        Returns:
            ``True`` on success."""
        self.log("Starting machine", "start")
        if self.backend is None:
            raise NoBackend
        if isinstance(self.backend, type):
            raise NoBackend("Backend not connected")
        self.backend.start(*args, **kwargs)

    def eject_cdrom(self, regex: re.Pattern) -> Sequence[CDROM]:
        """Eject CD-ROM(s) from the machine

        Args:
            regex: Pattern of the CD-ROM(s) to eject. The library will iterate
                over all the CD-ROMs, removing all the matches.

        Return: The disks removed.
        """
        if self.backend is None or isinstance(self.backend, type):
            raise NoBackend()
        ret: list[CDROM] = []
        diskarray = list(self.diskarray)
        for storage in self.diskarray:
            if (
                isinstance(storage, CDROM)
                and storage.label is not None
                and regex.match(storage.label) is not None
            ):
                ret.append(storage)
                diskarray.remove(storage)
                ui.instance().debug(f"Ejecting: {storage}")
        self.diskarray = diskarray

        # HACK: Boot order should be updated by the machine when diskarray changes
        self.boot_order = [
            dev
            for dev in self.boot_order
            if dev in self.diskarray or dev is self.hardware.disk
        ]

        self.backend.update()
        return ret

    def is_shutoff(self) -> bool:
        """Check if the machine is shut off

        Returns:
            True if the machine is shut off, False otherwise
        """
        if self.backend is None or isinstance(self.backend, (type)):
            raise NoBackend
        return self.backend.is_shutoff()

    @property
    def boot_order(self) -> BootOrder:
        """The current boot order of the machine

        Returns:
            A list, containing the boot elements, in order.
        """
        if self._boot_order is None:
            # We construct a default boot order
            self._boot_order = list(self.diskarray)
            if self.hardware.disk is not None:
                self._boot_order = [self.hardware.disk, *self._boot_order]
        return list(self._boot_order)

    @boot_order.setter
    def boot_order(self, val: Optional[BootOrder]) -> None:
        """Indicate the boot order to follow

        Args:
            order: Ordered list of disk(s) and/or CDROM(s) to boot. You can pass
                ``None`` to reset the bootorder to the default.

        Raises:
            ValueError: If one (or more) devices are not present in this
                machine.
        """
        if val:
            wrong: list[Storage] = []
            for dev in val:
                if dev == self.hardware.disk:
                    continue
                if dev in self.diskarray:
                    continue
                wrong.append(dev)
            if wrong:
                raise ValueError(f"Device(s) not present in this machine: {wrong}")

        self._boot_order = val

    def dict(self) -> Serialized:
        """Serialize the machine into a basic :py:class:`dict`"""

        def none_or_abs(path):
            return None if path is None else str(path.absolute())

        cloud_init: None | str | dict
        if isinstance(self.cloud_init, pathlib.Path):
            cloud_init = none_or_abs(self.cloud_init)
        else:
            cloud_init = self.cloud_init

        backend = None
        if has_backend(self):
            backend = self.backend.dict()

        return {
            "name": self.name,
            "folder": none_or_abs(self.folder),
            "uuid": str(self.uuid),
            "hostname": self.hostname,
            "title": self.title,
            "description": self.description,
            "metadata": self.metadata,
            "group": None if self.group is None else self.group.reference(),
            "info": self.info.dict(),
            "options": self.options.dict(),
            "spinfile": none_or_abs(self.spinfile),
            # HACK: Serialize image definition
            "image": None
            if (not isinstance(self.image, Image))
            else self.image.reference().dict(),
            "hardware": self.hardware.dict(),
            "cloud_init": cloud_init,
            "ignition": self.ignition,
            "autodestroy": self.autodestroy,
            "shared_folders": [sf.dict() for sf in self.shared_folders],
            "diskarray": [disk.dict() for disk in self.diskarray],
            "boot_order": [disk.dict() for disk in self.boot_order],
            "hardware_virtualization": self.hardware_virtualization,
            "ssh": [(c().dict() if callable(c) else c.dict()) for c in self.ssh],
            "on_creation": self.on_creation.dict(),
            "on_boot": self.on_boot.dict(),
            "plugins": [pkg.__name__ for pkg in self.plugins],
            "backend": backend,
        }


class MachineWithBackend(Machine):
    """Utility class for type hinting.

    This class inherits Machine, but in addition forces backend
    to be an object, avoiding unnecessary checks.
    """

    backend: spin.backend.base.MachineInterface


class ElementalMachine(Protocol):
    """Attributes a machine will *always have*, independently of the state"""

    uuid: core.UUID
    spinfile: None | pathlib.Path
    image: None | ImageDefinition | Image
    hardware: Hardware
    diskarray: Sequence[Storage]
    shared_folders: list[SharedFolder]
    log: Log
    info: MachineInfo
    on_creation: ShellInput
    on_boot: ShellInput
    options: Options

    @property
    def boot_order(self) -> BootOrder:
        ...

    @boot_order.setter
    def boot_order(self, val: Optional[BootOrder]) -> None:
        ...

    def add_disk(self, disk: Storage) -> None:
        ...


class DefinedMachine(ElementalMachine, Protocol):
    """Utility type, where all non-optional attributes are present"""

    name: str
    title: None | str = None
    description: None | str = None
    metadata: dict[str, str]
    hostname: str
    hardware_virtualization: FeatureLiteral
    ssh: list[SSHCredential]
    backend: spin.backend.base.MachineInterface
    cloud_init: None | str | pathlib.Path | dict[str, Any]
    ignition: None | dict


class MachineUnderCreation(DefinedMachine, Protocol):
    folder: pathlib.Path
    image: None | Image


class CreatedMachine(MachineUnderCreation, Protocol):
    """Utility type, represents the state of a machine after creation"""

    folder: pathlib.Path
    backend: spin.backend.base.MachineInterface


def has_backend(machine: Machine) -> TypeGuard[MachineWithBackend]:
    """Check if the machine has a backend, and return a MachineWithBackend.

    This function performs a 'type narrowing' operation, or cast,
    to convince the
    """
    return isinstance(machine.backend, spin.backend.base.MachineInterface)


def is_defined(machine: Machine) -> TypeGuard[DefinedMachine]:
    """Check if the machine satisfies DefinedMachine protocol"""
    # FIXME: Missing checks
    for attr in ("uuid", "name", "hostname"):
        if getattr(machine, attr) is None:
            return False
    for cred in machine.ssh:
        if callable(cred):
            return False
    if machine.backend is None or isinstance(machine.backend, type):
        return False
    return True


def is_under_creation(machine: Machine) -> TypeGuard[MachineUnderCreation]:
    """Check if a machine type-checks being under construction protocol"""
    if machine.image is not None:
        if not isinstance(machine.image, Image):
            return False
    if not hasattr(machine, "folder"):
        return False

    return is_defined(machine)


def is_created(machine: Machine) -> TypeGuard[CreatedMachine]:
    """Check if a machine has been created and satisfies the Created protocol"""
    return has_backend(machine) and is_defined(machine)


def as_machine(machine: Machine | DefinedMachine | CreatedMachine) -> Machine:
    """Return a ``DefinedMachine`` as a Machine.

    DefinedMachine is a subset of Machine. It is not a subclass due
    to type limitations.
    """
    return cast(Machine, machine)
