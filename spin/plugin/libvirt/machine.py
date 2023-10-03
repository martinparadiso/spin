"""Machine control functionality."""

from __future__ import annotations

import ipaddress
import time
import traceback
from threading import Event, Lock, Thread

from typing_extensions import Literal

import spin.backend.base
import spin.utils.info
from spin.errors import TODO, BackendError, ConnectionClosed
from spin.machine.connection import SerialConnection
from spin.machine.hardware import CDROM, Device
from spin.machine.machine import Machine, is_defined
from spin.plugin.libvirt.utils import parse_exception
from spin.utils import ui
from spin.utils.constants import MACHINE_STATE_LITERAL

from . import settings, xml
from .utils import parse_exception

try:
    import libvirt
except ImportError as exce:
    pass
open_consoles: dict[str, list[str]] = {}
"""Collection of UUID with an open console"""


class Console(SerialConnection):
    """Serial connection for libvirt domains."""

    def __init__(self, *, uuid: str, uri: str) -> None:
        """
        Args:
            uuid: The UUID of the domain to connect to.
            uri: The URI where the domain resides in.

        TODO: Currently the implementation connects to the first (default) serial
            port, some flexibility may be useful.
        """
        self.uuid = uuid
        self.uri = uri
        self.domain: libvirt.virDomain
        self.stream: libvirt.virStream | None = None
        self._thread: None | Thread = None
        self._conn: None | libvirt.virConnect = None
        self._buf = bytes()
        self._buflock = Lock()
        self._stop = Event()
        self._port_ok = True
        """``True`` if the port is in a safe state (open or closed), ``False``
        if it was errored during a read or write and hasn't been reset yet."""

    def __enter__(self) -> SerialConnection:
        self.open()
        return self

    def __exit__(self, *_) -> Literal[False]:
        self.close()
        return False

    def _poll(self) -> None:
        """The console connection is implemented with polling."""

        while not self._stop.is_set():
            libvirt.virEventRunDefaultImpl()

    @parse_exception
    def _read_callback(self, stream: libvirt.virStream, events, _):
        try:
            with self._buflock:
                self._buf = self._buf + stream.recv(4096)
        except libvirt.libvirtError as exce:
            # NOTE: We *cannot* raise here, we are in another thread
            ui.instance().warning(f"Exception while reading from serial port: {exce}")
            self._port_ok = False
            self._stop.set()
            return

    @parse_exception
    def open(self) -> None:
        ui.instance().debug("Opening serial/console port")

        if self.uuid in open_consoles:
            bt = "\n".join(open_consoles[self.uuid][:-2])
            ui.instance().error(f"Port already opened in:\n{bt}")
            raise BackendError(f"Port already opened by {open_consoles[self.uuid]}")

        # HACK: Should this be global?
        # HACK: In the documentation the function indicates the event handler
        # must be registered before a connection is open; we are not doing that
        libvirt.virEventRegisterDefaultImpl()

        self._conn = libvirt.open(self.uri)
        self.domain = self._conn.lookupByUUIDString(self.uuid)
        self.stream = self._conn.newStream(libvirt.VIR_STREAM_NONBLOCK)
        err = self.domain.openConsole(dev_name=None, st=self.stream)
        self.stream.eventAddCallback(
            libvirt.VIR_STREAM_EVENT_READABLE, self._read_callback, None
        )
        if err < 0:
            raise BackendError(f"Failed to open console. Error no: {err}")
        self._thread = Thread(target=self._poll, name="libvirt-event-poll")
        self._thread.start()

        open_consoles[self.uuid] = traceback.format_stack()

    @parse_exception
    def close(self) -> None:
        ui.instance().debug("Closing serial/console port")
        if self.stream is not None:
            try:
                self.stream.eventRemoveCallback()
                self.stream.finish()
                self.stream = None
            except Exception as exce:
                ui.instance().error(
                    f"Could not close stream {self.stream}. Exception: {exce}"
                )

        if self._thread is not None:
            try:
                self._stop.set()
                self._thread.join()
                self._thread = None
            except Exception as exce:
                ui.instance().error(f"Could not stop {self._thread}. Exception: {exce}")

        if self._conn is not None:
            try:
                self._conn.close()
                self._conn = None
            except Exception as exce:
                ui.instance().error(
                    f"Could not close stream {self.stream}. Exception: {exce}"
                )

        open_consoles.pop(self.uuid)
        self._stop.clear()
        self._buf = bytes()
        self._port_ok = True

    @parse_exception
    def read(self, at_most: int) -> bytes:
        if not self._port_ok:
            self.close()
            raise ConnectionClosed

        with self._buflock:
            ret = self._buf[:at_most]
            self._buf = self._buf[at_most:]
        return ret

    @parse_exception
    def write(self, data: bytes) -> int:
        if not self._port_ok:
            self.close()
            raise ConnectionClosed

        if self.stream is None:
            raise ValueError("Connection closed")
        try:
            return self.stream.send(data)
        except libvirt.libvirtError as exce:
            if "cannot write to stream" in str(exce):
                raise ConnectionClosed from exce
            raise


class MachineInterface(spin.backend.base.MachineInterface):
    """Libvirt implementation of the MachineInterface"""

    class Serialized(spin.backend.base.MachineInterface.Serialized):
        uri: str

    name = "libvirt/KVM"

    shared_folder = "tag-hint"
    disk_location = ("pool",)
    # TODO: Support for other auto-mount modes, _netdev is kind of a
    # dirty way to provide automount. Also, virtiofs is a nice
    # alternative to 9p.
    shared_folder_fs = "9p"
    automount_fstab_opts = ["trans=virtio", "_netdev"]

    def __init__(self, machine: Machine, uri: None | str = None) -> None:
        """Create a backend connection to libvirt

        Args:
            machine: The Machine object to manage.
            uri: The URI to connect to, please refer to libvirt documentation.
                Defaults to the one set in settings.
            args, kwargs: Extra arguments, maybe required by other backends.
        """
        super().__init__(machine)
        self.uri: str
        if uri is not None:
            self.uri = uri
        else:
            self.uri = settings.get().uri
        ui.instance().debug(f"libvirt URI: {self.uri}")
        self.dom: libvirt.virDomain

    @parse_exception
    def domain(self):
        """Retrieve the libvirt domain object for this machine"""
        if not hasattr(self, "dom"):
            with libvirt.open(self.uri) as conn:
                self.dom = conn.lookupByUUIDString(self.machine.uuid)
        return self.dom

    @parse_exception
    def create(self, start: bool = False) -> spin.backend.base.ReturnType:
        if start:
            raise TODO

        if not is_defined(self.machine):
            raise ValueError(f"Machine {self.machine} not defined")
        domxml = xml.from_machine(self.machine)

        with libvirt.open(self.uri) as conn:
            # TODO: Check before this if the name is present in the backend
            self.dom = conn.defineXML(xml.to_str(domxml))

        return True, None

    @parse_exception
    def update(self) -> spin.backend.base.ReturnType:
        # Note: in libvirt updating is done by sending an XML with the same
        # UUID
        return self.create(start=False)

    @parse_exception
    def start(self, paused: bool = False) -> spin.backend.base.ReturnType:
        if paused:
            raise TODO

        self.domain().create()

        return True, None

    @parse_exception
    def acpi_shutdown(self, timeout: int | float) -> spin.backend.base.ReturnType:
        dom = self.domain()
        dom.shutdown()

        start = time.time()
        while time.time() - start < timeout:
            if self.is_shutoff():
                return True, None
            time.sleep(0.1)
        return False, None

    @parse_exception
    def force_stop(self) -> spin.backend.base.ReturnType:
        dom = self.domain()
        dom.destroy()

        if self.is_running():
            return False, None
        return True, None

    @parse_exception
    def acpi_reboot(self, timeout: int | float) -> spin.backend.base.ReturnType:
        import time

        dom = self.domain()
        dom.reboot()

        start = time.time()
        while time.time() - start < timeout:
            if not self.is_running():
                return True, None
            time.sleep(0.1)
        return False, None

    @parse_exception
    def bootstrap_boot(self) -> spin.backend.base.ReturnType:
        if not is_defined(self.machine):
            raise ValueError(f"Machine {self.machine} not defined")
        ui.instance().notice("Bootstrapping machine boot")
        as_xml = xml.from_machine(self.machine)

        xmlnode = as_xml.find("devices/interface/source")
        if xmlnode is None:
            raise Exception("Could not find network name.")
        name = xmlnode.attrib["network"]
        if name is None:
            raise Exception("Could not find network name.")

        with libvirt.open(self.uri) as conn:
            self.dom = conn.defineXML(xml.to_str(as_xml))
            net = conn.networkLookupByName(name)
            if not net.isActive():
                net.create()
            # HACK: deactivate network if domain creation fails
            self.dom.create()

        return True, None

    @property
    def main_ip(self) -> None | ipaddress.IPv4Address | ipaddress.IPv6Address:
        if not self.is_running():
            return None
        dom = self.domain()
        iface: dict = dom.interfaceAddresses(0)

        if len(iface) > 1:
            raise TODO("Multi-vnet detection")
        if len(iface) == 0:
            return None

        ipaddr = ipaddress.ip_address(iface[list(iface.keys())[0]]["addrs"][0]["addr"])
        return ipaddr

    @parse_exception
    def has_console_port(self) -> bool:
        xmlstr = self.domain().XMLDesc()
        asxml = xml.from_str(xmlstr)
        return asxml.find("devices/console") is not None

    @parse_exception
    def console_port(self) -> SerialConnection:
        if self.machine.status != "RUNNING":
            raise ValueError("Machine not created")
        return Console(uuid=self.machine.uuid, uri=self.uri)

    @parse_exception
    def eject(self, *dev: "Device") -> list["Device"] | list["CDROM"]:
        def find_xml(cdrom: CDROM):
            """Find a CDROM node, and return it"""
            dom = xml.from_str(self.domain().XMLDesc())
            return dom.find(
                f"devices/disk/[@device='cdrom']/source[@file='{cdrom.location}']/.."
            )

        devs = [*dev]
        for dev_ in devs:
            if not isinstance(dev_, CDROM):
                raise TODO
        to_remove = [cd for cd in devs if isinstance(cd, CDROM)]
        removed = []
        dom = self.domain()
        for cdrom in to_remove:
            if cdrom is not None:
                xmlnode = find_xml(cdrom)
                if xmlnode is None:
                    continue
                dom.detachDeviceFlags(
                    xml.to_str(xmlnode),
                    libvirt.VIR_DOMAIN_AFFECT_CONFIG,
                )
                removed.append(cdrom)
        return removed

    @parse_exception
    def exists(self) -> bool:
        with libvirt.open(self.uri) as conn:
            # NOTE: We are using this because lookupByUUIDString prints to
            # stdout/err begind our backs.
            doms = conn.listAllDomains()
            for dom in doms:
                if dom.UUIDString() == self.machine.uuid:
                    return True
            return False

    @parse_exception
    def state(self) -> MACHINE_STATE_LITERAL:
        STATE_MAPPER: dict[int, MACHINE_STATE_LITERAL] = {
            libvirt.VIR_DOMAIN_NOSTATE: "UNKNOWN",
            libvirt.VIR_DOMAIN_RUNNING: "RUNNING",
            libvirt.VIR_DOMAIN_BLOCKED: "ERRORED",
            libvirt.VIR_DOMAIN_PAUSED: "PAUSED",
            libvirt.VIR_DOMAIN_SHUTDOWN: "UNKNOWN",
            libvirt.VIR_DOMAIN_SHUTOFF: "SHUTOFF",
            libvirt.VIR_DOMAIN_CRASHED: "ERRORED",
            libvirt.VIR_DOMAIN_PMSUSPENDED: "UNKNOWN",
        }
        dom = self.domain()
        return STATE_MAPPER.get(dom.state()[0], "UNKNOWN")

    @parse_exception
    def is_running(self) -> bool:
        dom = self.domain()
        return dom.state()[0] == libvirt.VIR_DOMAIN_RUNNING

    @parse_exception
    def is_shutoff(self) -> bool:
        dom = self.domain()
        return dom.state()[0] == libvirt.VIR_DOMAIN_SHUTOFF

    @parse_exception
    def delete(self) -> spin.backend.base.ReturnType:
        dom = self.domain()
        try:
            dom.undefine()
            return True, None
        except libvirt.libvirtError as e:
            return False, str(e)

    def dict(self) -> Serialized:
        return {
            "mod": self.main.__module__,
            "cls": self.main.__class__.__qualname__,
            "uri": self.uri,
        }
