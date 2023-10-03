"""libvirt core support"""

from __future__ import annotations

from typing import Optional, overload

from typing_extensions import Literal

import spin.plugin.api.register
from spin.backend.base import Backend, DiskPool, NetworkInterface
from spin.machine import network
from spin.machine.machine import Machine
from spin.plugin.libvirt.machine import MachineInterface
from spin.plugin.libvirt.settings import LibvirtConfig
from spin.utils import ui
from spin.utils.config import BackendCommonSettings

from . import checks, settings, xml
from .storage import LibvirtDiskPool
from .utils import parse_exception

try:
    import libvirt
except ImportError as exce:
    pass


class LibvirtNetworkInterface(NetworkInterface):
    """Functionality to access and manage libvirt network"""

    def __init__(self, uri: str) -> None:
        self.uri = uri

    def get(self, name: network.LAN.Reference) -> Optional[network.LAN]:
        with libvirt.open(self.uri) as conn:
            try:
                net = conn.networkLookupByName(name)
            except libvirt.libvirtError as exce:
                if "not found" not in str(exce):
                    raise
                net = None
        if net is None:
            return None
        lan = xml.to_network(net.XMLDesc())
        if lan.name != name:
            return None
        return lan

    def create(self, net: network.LAN) -> None:
        if net.ipv4 and net.ipv4 == "auto":
            new_sub4 = network.random_subnet(4)
            gateway4 = next(new_sub4.hosts())

            net.ipv4 = network.IPv4Network(
                network=new_sub4,
                gateway=gateway4,
                dhcp=network.dhcp(new_sub4),
            )
        ipv6_ra_configured = checks.accept_ra_configured()

        if net.ipv6 == "auto" and ipv6_ra_configured:
            new_sub6 = network.random_subnet(6)
            gateway6 = next(new_sub6.hosts())
            net.ipv6 = network.IPv6Network(network=new_sub6, gateway=gateway6)
            # TODO: Implement DHCPv6
            ui.instance().warning("DHCPv6 not set")
        elif net.ipv6 == "auto" and not ipv6_ra_configured:
            net.ipv6 = None
            ui.instance().notice("IPv6 disabled: libvirt requires accept_ra = 2")
        else:
            ui.instance().warning("libvirt requires `accept_ra = 2`. Network may fail.")

        as_str = xml.to_str(xml.from_network(net))
        with libvirt.open(self.uri) as conn:
            conn.networkDefineXML(as_str)

    def delete(self, net: network.LAN) -> None:
        if net.name is None:
            raise ValueError("Network missing name")
        with libvirt.open(self.uri) as conn:
            try:
                backend_net = conn.networkLookupByName(net.name)
            except libvirt.libvirtError as exce:
                if "not found" not in str(exce):
                    raise ValueError("Network not in backend") from exce
                raise
            if backend_net.isActive():
                backend_net.destroy()
            backend_net.undefine()


@spin.plugin.api.register.backend
class LibvirtBackend(Backend):
    def __init__(self, *args, uri: None | str = None, **kwargs) -> None:
        """
        Args:
            uri: Libvirt URI to connect to. Defaults to the one provided by
                the settings.
        """
        super().__init__(*args, **kwargs)
        self.uri: str
        if uri is not None:
            self.uri = uri
        else:
            self.uri = settings.get().uri

        self.network = LibvirtNetworkInterface(self.uri)

    def find(self, *, uuid: Optional[str] = None) -> "Optional[Machine]":
        pass

    @parse_exception
    @overload
    def disk_pool(self, name: str, *, create: Literal[True]) -> DiskPool:
        ...

    @parse_exception
    @overload
    def disk_pool(self, name: str, *, create: Literal[False]) -> None | DiskPool:
        ...

    @parse_exception
    @overload
    def disk_pool(self, name: str, *, create: bool) -> None | DiskPool:
        ...

    @parse_exception
    def disk_pool(self, name: str, *, create: bool = False) -> None | DiskPool:
        with libvirt.open(self.uri) as conn:
            try:
                pool = conn.storagePoolLookupByName(name)
            except libvirt.libvirtError as exce:
                if "not found" not in str(exce):
                    raise
                pool = None
        if pool is None:
            if not create:
                return None
            return LibvirtDiskPool(pool=name, uri=self.uri).create_pool()
        return LibvirtDiskPool(pool=pool, uri=self.uri)

    def machine(self, machine: Machine) -> MachineInterface:
        vmi = MachineInterface(machine, self.uri)
        vmi.main = self
        return vmi

    @classmethod
    def load(cls, machine: "Machine", *args, **kwargs) -> MachineInterface:
        if "uri" not in kwargs:
            raise ValueError("Missing required kwarg: uri")
        backend = cls(uri=kwargs["uri"])
        return backend.machine(machine)

    @classmethod
    def settings(cls) -> BackendCommonSettings:
        return LibvirtConfig()
