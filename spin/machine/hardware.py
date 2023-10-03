"""Contains hardware related classes, like Disks and NICs

The hardware described here
"""
from __future__ import annotations

import pathlib
from typing import Optional, Sequence
from uuid import uuid4

from pydantic import ValidationError, create_model_from_typeddict
from typing_extensions import Literal, Protocol, TypedDict, get_args

import spin.utils.config
from spin.machine.network import LAN, PortMapping
from spin.machine.shared import Manager
from spin.utils import Size


class ImageProtocol(Protocol):
    """Image with an accessible file"""

    file: pathlib.Path

    def hexdigest(self) -> str:
        ...


class HasBacking(Protocol):
    """Class providing type-hint for devices with backing images"""

    backing_image: None | ImageProtocol = None
    """The path to the backing image"""


class Device:
    """Base class for all hardware devices

    Currently serves no purpose
    """

    class Serialized(TypedDict):
        shared: bool

    def __init__(self, shared: bool = False) -> None:
        self._shared: bool = shared

    def is_shared(self) -> bool:
        """Returns ``True`` if the device is shared among several machines.

        Returns:
            ``True`` if the device is in use by several machines, ``False``
            if not. This normally is used to prevent destruction of shared
            devices.
        """
        return self._shared

    def dict(self) -> Serialized:
        return {"shared": self.is_shared()}

    def __eq__(self, __o: object) -> bool:
        return vars(self) == vars(__o)


class NIC(Device):
    """Network Interface Card for use in Virtual Machines"""

    modes_literal = Literal["NAT", "user"]

    modes = get_args(modes_literal)
    """Available NIC types

    - `NAT`: Classic NAT virtual network.
    - `user`: Unprivileged network mode, behaviour depends on backend.
      Normally behaves as a NAT without the ability to forward ports.
    """

    class Serialized(Device.Serialized):
        mode: NIC.modes_literal
        network: Optional[LAN.Reference]
        forwarding: list[PortMapping.Serialized]

    def __init__(
        self,
        mode: modes_literal = "NAT",
        network: None | str | LAN = None,
        shared: bool = False,
        forwarding: None | Sequence[PortMapping | PortMapping.Serialized] = None,
    ):
        """
        Args:
            type: The network type, see types for a list of available types
            network: The network this NIC is attached to. Can be a :py:class:`LAN`
                object; or the name of the network.

        Raises:
            ValueError: If an unsupported NIC type is provided
        """
        if mode not in self.modes:
            raise ValueError(f"Unsupported NIC type `{mode}`")
        super().__init__(shared=shared)
        self.mode: NIC.modes_literal = mode
        if isinstance(network, str):
            network = Manager(LAN).load(network)
        self.network: None | LAN = network
        self.forwarding: list[PortMapping] = []
        for port in forwarding or []:
            if isinstance(port, Sequence):
                port = PortMapping(*port)
            self.forwarding.append(port)

    def dict(self) -> Serialized:
        return {
            **super().dict(),  # type: ignore[misc]
            "mode": self.mode,
            "network": None if self.network is None else self.network.uuid,
            "forwarding": [p.dict() for p in self.forwarding],
        }


class Storage(Device):
    """Base class for all storage devices"""

    class Serialized(Device.Serialized):
        uuid: Optional[str]
        location: Optional[str]
        pool: Optional[str]
        size: Optional[int]
        label: Optional[str]

    def __init__(
        self,
        uuid: None | str,
        size: None | Size | str | int,
        location: None | str | pathlib.Path,
        pool: None | str,
        label: None | str,
        shared: None | bool = None,
    ) -> None:
        super().__init__()
        self.uuid: None | str = uuid
        if isinstance(location, str):
            location = pathlib.Path(location)
        self.location = location
        """The path to the disk file in the host filesystem"""

        self.size: None | Size
        """Virtual size of the device"""

        if isinstance(size, (str, int)):
            self.size = Size(size)
        else:
            self.size = size

        # Child provided, optional
        self.format: None | str = None

        self.pool: None | str = pool
        """Pool where this disk is stored.

        If ``None``, the library uses the default value provided
        in the configuration.
        """

        self.label: None | str = label
        """Identification string useful to search for the disk.
        """

    def exists(self) -> bool:
        """Check if the disk path is present"""
        return (
            self.location is not None
            and self.location.exists()
            and self.location.is_file()
        )

    def delete(self) -> None:
        """Delete the disk in the filesystem.

        Warning:
            Destructive operation, contents of the disk will be completely
            lost. Use with care.
        """
        if self.location is not None:
            self.location.unlink()
            self.location = None

    def new_uuid(self) -> None:
        """Generate a new UUID for this device."""

        self.uuid = str(uuid4())

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(label={self.label},size={self.size},location={repr(self.location)})"

    def dict(self) -> Serialized:
        return {
            "uuid": self.uuid,
            "location": None if self.location is None else str(self.location),
            "pool": self.pool,
            "label": self.label,
            "size": None if self.size is None else self.size.bytes,
            "shared": self._shared,
        }

    @classmethod
    def init_subclass(cls, **kwargs) -> Storage:
        for sub in cls.__subclasses__():
            try:
                validator = create_model_from_typeddict(sub.Serialized)
                validator.update_forward_refs(Literal=Literal)  # For Python <= 3.8
                validator(**kwargs)
                return sub(**kwargs)
            except ValidationError:
                pass
        raise ValueError


class UsableImage(Protocol):
    """Image with an accessible file"""

    file: pathlib.Path
    sha256: str


class Disk(Storage, HasBacking):
    """A disk

    It's a disk

    Args:
        size: The size of the disk
        location: Path to the the disk image
        backing_image: Backing image for this disk, can be None if disk already
            exists
        uuid: The UUID of the disk.
    """

    class Serialized(Storage.Serialized):
        fmt: Literal["qcow2", "raw"]
        backing_image: Optional[str]

    def __init__(
        self,
        size: None | Size | str | int = None,
        location: None | str | pathlib.Path = None,
        pool: None | str = None,
        label: None | str = None,
        fmt: Literal["qcow2", "raw"] = "qcow2",
        backing_image: None | str | ImageProtocol = None,
        uuid: None | str = None,
        shared: None | bool = None,
    ):
        super().__init__(
            uuid=uuid,
            size=size,
            location=location,
            pool=pool,
            label=label,
            shared=shared,
        )
        if size is None:
            self.size = spin.utils.config.conf.settings.defaults.disk_size
        self.format: Literal["qcow2", "raw"] = fmt
        """Disk format. Currently prefers qcow2 due to libvirt."""

        self.backing_image: None | ImageProtocol = (
            backing_image if not isinstance(backing_image, str) else None
        )

    def dict(self) -> Serialized:
        """Return a JSON-friendly ``dict``

        Returns:
            A ``dict``, ready to pass to ``json.dumps()``.
        """
        return {
            **super().dict(),  # type: ignore[misc]
            "fmt": self.format,
            "backing_image": None
            if self.backing_image is None
            else str(self.backing_image.hexdigest()),
        }


class CDROM(Storage):
    """CD-ROM

    Args:
        location: Path to the image
    """

    class Serialized(Storage.Serialized):
        fmt: Literal["iso"]

    def __init__(
        self,
        location: None | str | pathlib.Path,
        size: None | int | Size | str = None,
        label: None | str = None,
        fmt: Literal["iso"] = "iso",
        pool: None | str = None,
        uuid: None | str = None,
        shared: None | bool = None,
    ):
        """
        Args:
            location: Path in the filesystem to the CDROM iso image.
            label: CDROM label, see attribute for more information.
        """
        super().__init__(
            uuid=uuid,
            size=size,
            location=location,
            pool=pool,
            label=label,
            shared=shared,
        )
        self.fmt: Literal["iso"] = fmt
        """Disk format. Currently prefers qcow2 due to libvirt."""

    def dict(self) -> Serialized:
        """Return a JSON-friendly ``dict``

        Returns:
            A ``dict``, ready to pass to ``json.dumps()``.
        """
        return {
            **super().dict(),  # type: ignore[misc]
            "fmt": self.fmt,
        }


class SharedFolder:
    """A shared folder between host and a guest

    Args:
        host_path: *Absolute* or *relative* path in the host filesystem
        guest_path: *Absolute* path in the guest filesystem to mount the folder
            in.
        read_only: If set to ``True`` the guest cannot modify the folder or its
            contents. If set to ``False`` the guest can make modify the contents
            of the folder.
    """

    class Serialized(TypedDict):
        host_path: str
        guest_path: str
        read_only: bool

    def __init__(
        self,
        host_path: str | pathlib.Path,
        guest_path: str | pathlib.Path,
        read_only: bool = False,
    ):
        self.host_path: pathlib.Path = pathlib.Path(host_path)
        self.guest_path: pathlib.PurePath = pathlib.Path(guest_path)
        self.read_only: bool = read_only

    def dict(self) -> Serialized:
        return {
            "host_path": str(self.host_path.absolute()),
            "guest_path": str(self.guest_path),
            "read_only": self.read_only,
        }
