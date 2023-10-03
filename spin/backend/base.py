"""Base backend, for API reference and help"""

from __future__ import annotations

import ipaddress
import pathlib
from abc import abstractmethod
from typing import TYPE_CHECKING, Optional, Tuple, overload

from typing_extensions import Literal, Protocol, TypedDict

if TYPE_CHECKING:
    from spin.image.image import Image
    from spin.machine import network
    from spin.machine.connection import SerialConnection
    from spin.machine.hardware import CDROM, Device, Disk, Storage
    from spin.machine.machine import Machine
    from spin.utils.config import BackendCommonSettings
    from spin.utils.constants import MACHINE_STATE_LITERAL, SERIALIZABLE_TYPES


ReturnType = Tuple[bool, Optional[str]]
"""The type returned by actions executed in the backend.

The first element is a bool indicating the success of the operation (``True``
for success). And the second element is an optional string with a
*user-friendly* message, which normally contains information about the error.
"""


class NonExistingMachine(BaseException):
    """Exception raised when an operation is requested for a machine that
    has not been created."""


class OperationUnsupported(BaseException):
    """Exception raised when a backend does not support a particular operation."""


class DiskPool:
    """Disk management in a backend-dependant pool"""

    @property
    @abstractmethod
    def formats(self) -> list[str]:
        """Contains the formats supported by the pool"""

    @abstractmethod
    def import_image(self, image: "Image") -> "Disk":
        """Import the image into the pool.

        Args:
            image: The image to import. The pool will add itself to the list
                pools where the image is present.

        Returns:
            A :py:class:`Disk` object, where the content of the disk is
            the image provided.

        Raises:
            BackendError: If something fails on the backend side.
            ValueError: If the provided image has no local file.
        """
        raise NotImplementedError

    @abstractmethod
    def create_disk(self, disk: "Storage") -> ReturnType:
        """Create a disk in this pool.

        If the disk has a backing image; it must be present in the pool
        before this disk is inserted.

        Args:
            disk: The disk to import into the pool.

        Raises:
            NotFound: If the backend cannot find the backing image in the
                pool.

        Returns:
            ``True`` if the disk was created, ``False`` if something fails.
            The backend may include a user-friendly message as a second element.
        """
        raise NotImplementedError

    @abstractmethod
    def fill(self, disk: Storage, data: pathlib.Path) -> None:
        """Fill *disk* with the data found in *data*"""
        ...

    @abstractmethod
    def remove(self, disk: "Storage") -> bool:
        """Remove a disk from the pool.

        Warning: The disk file is destroyed. Lose of data *will* occur.

        Args:
            disk: The disk to remove from the pool.

        Raises:
            ValueError: If the disk is not present in the pool.
        """
        raise NotImplementedError

    @abstractmethod
    def list_disks(self) -> "list[Storage]":
        """Retrieve the disks stored in this pool"""
        raise NotImplementedError


class NetworkInterface(Protocol):
    """Provides access to the backend network facilities"""

    def get(self, name: network.LAN.Reference | str) -> Optional[network.LAN]:
        """Returns the network *name* if it exists."""
        raise NotImplementedError

    def create(self, net: network.LAN) -> None:
        """Create *net* in the backend.

        If the network has no IP range set; the backend will define
        one automatically, and update the network object.
        """
        raise NotImplementedError

    def delete(self, net: network.LAN) -> None:
        """Create *network* in the backend.

        If the network has no IP range set; the backend will define
        one automatically, and update the network object.
        """
        raise NotImplementedError


class MachineFeatures:
    """Enumerates and describes the features supported by the backend"""

    SharedFolderStrategy = Literal["tag-hint"]
    shared_folder: Optional[SharedFolderStrategy] = None
    """Supported shared folder system by the backend

    - ``None`` indicates no support for shared folders.
    - ``"tag-hint"`` is meant to be used with QEMU, where the mount point is _hinted_
      at the guest as a volume target.
    """

    DiskLocation = Literal["pool", "directory", "anywhere"]
    disk_location: None | tuple[DiskLocation] = None
    """Specifies where the disk files must be stored.

    Multiples values are supported, if the backend is flexible.

    The meaning of each possible value is:

    - ``None``: no information available.
    - ``"pool"``: the backend has an internal pool of disk. Disk manipulation
      must be performed through the backend provided API. This is the case
      for the default configuration of ``libvirt``.
    - ``"directory"``: an special directory stablished by the backend,
      accessible by the user.
    - ``"anywhere"``: the file can be anywhere in the filesystem, as long as
      the backend has access to it. May require read and search permissions
      all the way up to ``/``.
    """

    shared_folder_fs: str
    """Shared folder filesystem, to use when populating fstab."""

    automount_fstab_opts: list[str] = []
    """The fstab options used when editing ``fstab`` for auto-mounting.
    
    Shared folders have different options depending on the backend and mounting 
    method. This array contains the list of options (to be joined with ``','``), 
    written to fstab to automount the folder.
    """


class MachineControl:
    """Change the state of the virtual machine"""

    def create(self, start: bool = False) -> ReturnType:
        """Create the virtual machine in the backend

        Args:
            start: If set to ``True``, the machine will be started immediately.
                Otherwise the machine will be created, but not booted.

        Raises:
            ValueError: If the machine already exists.

        Returns:
            ``True`` if the machine was created, ``False`` if something fails.
            The backend may include a user-friendly message as a second element.
        """
        raise NotImplementedError

    @abstractmethod
    def update(self) -> ReturnType:
        """Synchronize the machine properties with the backend

        Raises:
            Exception: If there are changes in the machine that cannot
                updated in the backend.

        Returns:
            ``True`` if the operation was completed successfully.
        """
        raise NotImplementedError

    @abstractmethod
    def start(self, paused: bool = False) -> ReturnType:
        """Start the virtual machine.

        Args:
            paused: If set to ``True``, the machine will started *paused*, and
                needs to be unpaussed in order to work.

        Raises:
            NonExistingMachine: If the machine does not exists in the backend.

        Returns:
            ``True`` if the machine was started, ``False`` if something fails.
            The backend may include a user-friendly message as a second element.
        """
        raise NotImplementedError

    def acpi_shutdown(self, timeout: int | float) -> ReturnType:
        """Try to shutdown the virtual machine by sending an ACPI signal.

        Args:
            timeout: Seconds to wait for the machine to shutdown. If the
              does not shutdown in *timeout* seconds, the function returns
              ``False``.

        Raises:
            NonExistingMachine: If the machine does not exists in the backend.

        Returns:
            ``True`` if the machine successfully shutsdown before *timeout*;
            ``False`` if the machine is still running after *timeout*, or the
            backend reports an error.
        """
        raise NotImplementedError

    @abstractmethod
    def force_stop(self) -> ReturnType:
        """Stop the virtual machine by force.

        If the machine was not running, does nothing.

        Warning: this stops the virtual machine by force, similarly to cutting
        the power on a real machine.

        Raises:
            NonExistingMachine: If the machine does not exists in the backend.

        Returns:
            ``True`` if the machine was stopped, ``False`` if something fails
            and the machine cannot be stopped.
        """
        raise NotImplementedError

    def acpi_reboot(self, timeout: int | float) -> ReturnType:
        """Try rebooting the machine by sending an ACPI reboot signal.

        The function waits *timeout* seconds for the machine to reboot. If the
        machine does not reboot in *timeout* seconds the function returns false.

        Args:
            timeout: The seconds to wait for the machine to indicate a reboot.

        Raises:
            NonExistingMachine: If the machine does not exists in the backend.

        Returns:
            ``True`` if the machine was rebooted before *timeout*, ``False`` if
            not.
        """
        raise NotImplementedError

    def force_reboot(self) -> ReturnType:
        """Force a machine reboot.

        Similarly to :func:`force_stop`, the machine is completely stopped
        without notifing the guest OS.

        If the machine is not running, the function does nothing and returns
        False.

        Raises:
            NonExistingMachine: If the machine does not exists in the backend.

        Returns:
            ``True`` if the machine was rebooted, ``False`` if something went
            wrong.
        """
        raise NotImplementedError

    def pause(self) -> ReturnType:
        """Pause the machine execution.

        Raises:
            NonExistingMachine: If the machine does not exists in the backend.

        Returns:
            ``True`` if the machine was paused, ``False`` if something went
            wrong.
        """
        raise NotImplementedError

    def unpause(self) -> ReturnType:
        """Unpause the machine, does nothing if not paused.

        Note: an un-pause *may* fail if the disk is full.

        Raises:
            NonExistingMachine: If the machine does not exist in the backend.

        Returns:
            ``True`` if the machine is left in a running state, ``False`` if
            the unpause fails.
        """
        raise NotImplementedError

    def bootstrap_boot(self) -> ReturnType:
        """Boot the machine *as-is*. Contains network support and drives.

        This is normally used for temporary boots during the construction
        process. For instance for booting from a installation media.

        The machine **does not** need to exist in the backend for this
        function to succeed.
        """
        raise NotImplementedError

    @abstractmethod
    def delete(self) -> ReturnType:
        """Remove the machine from the backend

        This does not remove any devices or disks in the filesystem, only
        removes the entry from the backend.

        Returns:
            ``True`` if the machine is successfully destroyed, ``False`` if
            the operation fails. A second element with a help message may be
            provided.
        """
        raise NotImplementedError


class MachineStatus:
    """Retrieve information about a machine"""

    @abstractmethod
    def state(self) -> MACHINE_STATE_LITERAL:
        """Retrieve the machine state.

        Returns: The current machine state for this guest.
        """
        raise NotImplementedError

    @abstractmethod
    def exists(self) -> bool:
        """Check if the machine exists in the backend.

        Returns:
            ``True`` if the machine has been created, ``False`` if not.
        """
        raise NotImplementedError

    @abstractmethod
    def is_running(self) -> bool:
        """Check if the machine is running.

        Raises:
            NonExistingMachine: If the machine does not exist in the backend.

        Return:
            ``True`` if the machine is running, ``False`` if not.
        """
        raise NotImplementedError

    @abstractmethod
    def is_shutoff(self) -> bool:
        """Check if the machine is shutoff.

        Raises:
            :py:class:`NonExistingMachine`: If the machine does not exist in the backend.

        Returns:
            ``True`` if the machine is shutoff, ``False`` otherwise.
        """
        raise NotImplementedError


class MachineIO:
    """Input/output related to the machine"""

    @property
    @abstractmethod
    def main_ip(self) -> None | ipaddress.IPv4Address | ipaddress.IPv6Address:
        """ "Main" IP address of the machine.

        Normally represents the IP the user can connect through
        SSH.

        Returns:
            ``None`` if the machine has no main IP (either temporarily, due to
            not requesting one yet; or because it has not networking). If
            available an IP address, either v4 or v6.
        """
        raise NotImplementedError

    @abstractmethod
    def has_console_port(self) -> bool:
        """Check if the machine has a serial port

        Whenever possible, machines are created with a serial port, so this
        function should return ``True`` almost always.

        Raises:
            NonExistingMachine: If the machine does not exists in the backend.

        Returns:
            ``True`` if the machine has a console port in it is definition, even
            if the machine is powered off. ``False`` if the machine does not
            have a console port.
        """
        raise NotImplementedError

    @abstractmethod
    def console_port(self) -> None | SerialConnection:
        """Retrieve the path to the pseudo-file acting as serial port

        Raises:
            NonExistingMachine: If the machine does not exists in the backend.
            ValueError: If the machine does not have a port, you can check with
              :py:func:`has_console_port`.

        Returns:
            If the machine is running, a :py:class:`pathlib.Path` to the pseudo-file
            representing the console/serial port. If the backend has not
            created the file yet, returns ``None``.
        """
        raise NotImplementedError

    @overload
    def insert(self, dev: "CDROM") -> ReturnType:
        """Insert a cdrom into the machine

        If the given CDROM is already present, does nothing.

        Args:
            dev: The CDROM to insert into the machine.

        Raises:
            NonExistingMachine: If the machine does not exists in the backend.
            OperationUnsupported: If the backend or machine does not support
                injecting CDROMs.

        Return:
            ``True`` if the CDROM was inserted, ``False`` if not.
        """
        ...
        # NOTE: As of November, 2022 sphinx does not display overload docstrings

    @overload
    def insert(self, dev: "Device") -> ReturnType:
        """Insert an USB into the machine

        If the given USB is already present, does nothing.

        Args:
            dev: The USB to insert.

        Raises:
            NonExistingMachine: If the machine does not exists in the backend.
            OperationUnsupported: If the backend or machine does not support
                injecting CDROMs.

        Returns:
            ``True`` if the USB was successfully added, ``False`` if something
            fails.
        """
        ...

    def insert(self, dev: "Device") -> ReturnType:
        """Insert a hot-pluggable device into the machine

        If the given device is present, does nothing.

        Args:
            dev: The device to insert.

        Raises:
            NonExistingMachine: If the machine does not exists in the backend.
            OperationUnsupported: If the backend or machine does not support
                injecting the given device.

        Returns:
            ``True`` if the device was successfully added, ``False`` if
            something fails.
        """

        raise OperationUnsupported

    @abstractmethod
    def eject(self, *dev: "Device") -> list["Device"] | list["CDROM"]:
        """Eject devices from the machine

        Args:
            dev: The devices to eject/remove from the machine.

        Raises:
            NonExistingMachine: If the machine does not exists in the backend.
            OperationUnsupported: If the backend or machine does not support
                ejecting devices.

        Return:
            A list containing all the devices successfully removed, the list can
            be empty.
        """
        raise OperationUnsupported()


class Backend:
    """General backend operations.

    This interface contains general operations
    """

    network: NetworkInterface
    """Access the network functionality of the backend"""

    @abstractmethod
    def find(self, *, uuid: Optional[str] = None) -> "Optional[Machine]":
        """Try to find a machine in the backend.

        Args:
            uuid: The UUID of the machine to find in the backend.

        Returns:
            The machine that matches the provided arguments. Or ``None`` if
            the machine could not be found.
        """
        raise NotImplementedError

    @overload
    @abstractmethod
    def disk_pool(self, name: str, *, create: Literal[True]) -> DiskPool:
        ...

    @overload
    @abstractmethod
    def disk_pool(self, name: str, *, create: Literal[False]) -> None | DiskPool:
        ...

    @overload
    @abstractmethod
    def disk_pool(self, name: str, *, create: bool) -> None | DiskPool:
        ...

    @abstractmethod
    def disk_pool(self, name: str, *, create: bool = False) -> None | DiskPool:
        """Retrieve the pool stored as *name*

        Args:
            name: The name of the pool.
            create: Create the pool if it does not exist.

        Returns:
            If found, the requested pool.
        """
        raise NotImplementedError

    @abstractmethod
    def machine(self, machine: Machine) -> MachineInterface:
        """Generate a `MachineInterface` for the given machine.

        The library will set the corresponding attributes in the original
        `Machine` object.

        Args:
            machine: A `DefinedMachine`, which requires a backend.

        Returns:
            A `MachineInterface` for the received machine.
        """
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def load(cls, machine: "Machine", **kwargs) -> MachineInterface:
        """Load a serialized machine interface"""
        pass

    @classmethod
    @abstractmethod
    def settings(cls) -> BackendCommonSettings:
        """Retrieve the settings for this backend.

        Return:
            A :py:class:`BackendCommonSettings` object (or a subclass of),
            containing the settings used by the backend.
        """
        raise NotImplementedError


class MachineInterface(MachineControl, MachineStatus, MachineIO, MachineFeatures):
    """Defines the expected interface from a backend to manage a machine.

    The API is split in several base classes, each one providing a
    subset of functionality:

    - :class:`MachineControl`: Functions to control the general state of a
      virtual machine.
    - :class:`MachineStatus`: Functions to query the state and information of
      the machine.
    - :class:`MachineIO`: Functions related to machine inputs and outputs, such
      as serial ports, VNC connections.
    - :class:`MachineFeatures`: Attributes describing the backend capabilities.
    """

    name: str
    """Friendly name of the backend"""

    class Serialized(TypedDict):
        """Base (required) serialized backend machine interface.

        Every backend should (and probably has to) extend this class
        to add specific attributes in order to be able to reconstruct
        the object.
        """

        cls: str
        """The main `Backend` class, where the `load` method is."""

        mod: str
        """The python module where the `Backend` class is located."""

    def __init__(self, machine: "Machine", *args, **kwargs) -> None:
        """
        Args:
            machine: The spin Machine object which to manage in the backend.
            args, kwargs: arguments for the sub-class, backend-specific class
                in charge of the actual processing.
        """
        self.machine = machine
        """The machine to manage"""

        self.main: Backend
        """General operations of the backend.

        This variable groups all machine independent operations.
        """

    @abstractmethod
    def dict(self) -> Serialized:
        """Serialize the backend object connection."""
        raise NotImplementedError
