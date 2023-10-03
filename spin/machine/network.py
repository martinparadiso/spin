"""Network related classes and functionality."""

from __future__ import annotations

import ipaddress
import itertools
import pathlib
import secrets
from typing import Any, Callable, ClassVar, Generic, Optional, Tuple, TypeVar, overload
from uuid import uuid4

from typing_extensions import Literal, TypeAlias, TypedDict

from spin.errors import TODO
from spin.machine import core, shared
from spin.utils.config import conf

IPNetwork = TypeVar("IPNetwork")
IPAddress = TypeVar("IPAddress")


class PortMapping:
    """Represents a port forwarding from the host to the guest"""

    RANGE = (1, 2**16 - 1)
    PROTOCOL = Literal["tcp", "udp"]

    Serialized = Tuple[int, int, PROTOCOL]

    def __init__(self, host: int, guest: int, protocol: PROTOCOL) -> None:
        """
        Args:
            host: the port in the host
            guest: the port in the guest
        """
        self.host = host
        self.guest = guest
        self.protocol: PortMapping.PROTOCOL = protocol
        """The port protocol (**tcp** or **udp**)"""

    @classmethod
    def valid_port(cls, port: int) -> bool:
        """Return ``True`` if `port` is a valid number"""
        return cls.RANGE[0] <= port <= cls.RANGE[1]

    @classmethod
    def _validate(cls, port: int) -> None:
        """Raise exception if port is not valid.

        Raises:
            ValuError: If the port number is out of range.
        """
        if not cls.valid_port(port):
            raise ValueError(f"Port out of range: {port}")

    @property
    def host(self) -> int:
        """Port in the host machine"""
        return self._host

    @host.setter
    def host(self, value: int) -> None:
        self._validate(value)
        self._host = value

    @property
    def guest(self) -> int:
        """Port in the guest machine"""
        return self._guest

    @guest.setter
    def guest(self, value: int) -> None:
        self._validate(value)
        self._guest = value

    def __eq__(self, __value: object) -> bool:
        if not isinstance(__value, self.__class__):
            return False
        return vars(self) == vars(__value)

    def __str__(self) -> str:
        return f"{self.host}:{self.guest}/{self.protocol}"

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"host={self.host}, "
            f"guest={self.guest}, "
            f"protocol={self.protocol})"
        )

    # TODO: Rename 'all' ``dict()``s to serial or something like that
    def dict(self) -> PortMapping.Serialized:
        """Serialize into a json-friendly *tuple*"""
        return self.host, self.guest, self.protocol


class _Network(Generic[IPNetwork, IPAddress]):
    """Wraps LAN addressnetwork information"""

    network_init: Callable[[Any], IPNetwork]
    address_init: Callable[[Any], IPAddress]

    class Serialized(TypedDict):
        network: str
        gateway: str
        dhcp: Optional[tuple[str, str]]

    def __init__(
        self,
        network: str | IPNetwork,
        gateway: str | IPAddress,
        dhcp: None | tuple[str, str] | tuple[IPAddress, IPAddress] = None,
    ) -> None:
        if isinstance(network, str):
            network = self.__class__.network_init(network)
        if isinstance(gateway, str):
            gateway = self.__class__.address_init(gateway)
        if dhcp is not None:
            dhcp = (self.address_init(dhcp[0]), self.address_init(dhcp[1]))

        self.network: IPNetwork = network  # type: ignore[assignment]
        self.gateway: IPAddress = gateway  # type: ignore[assignment]
        self.dhcp: None | tuple[IPAddress, IPAddress] = dhcp

    def dict(self) -> Serialized:
        return {
            "network": str(self.network),
            "gateway": str(self.gateway),
            "dhcp": None
            if self.dhcp is None
            else (str(self.dhcp[0]), str(self.dhcp[1])),
        }


class IPv4Network(_Network[ipaddress.IPv4Network, ipaddress.IPv4Address]):
    address_init = ipaddress.IPv4Address
    network_init = lambda n: ipaddress.IPv4Network(n, strict=False)


class IPv6Network(_Network[ipaddress.IPv6Network, ipaddress.IPv6Address]):
    address_init = ipaddress.IPv6Address
    network_init = lambda n: ipaddress.IPv6Network(n, strict=False)


class LAN(shared.Resource):
    """Local Area Network, where guest machines connect to"""

    Reference: TypeAlias = str

    _instances: ClassVar[dict[str, LAN]] = {}
    """Collection of LAN instances; to guarantee synchornization"""

    class Serialized(shared.Resource.Serialized):
        nat: Optional[bool]
        ipv4: Optional[Literal["auto"] | IPv4Network.Serialized]
        ipv6: Optional[Literal["auto"] | IPv6Network.Serialized]
        users: list[core.UUID]

    def __init__(
        self,
        uuid: str,
        nat: None | bool = True,
        ipv4: None | Literal["auto"] | IPv4Network.Serialized | IPv4Network = "auto",
        ipv6: None | Literal["auto"] | IPv6Network.Serialized | IPv6Network = "auto",
        users: None | list[core.UUID] = None,
        autodestroy: bool = True,
    ) -> None:
        """
        Args:
            name: Name of the network.
            network: Address space of the network.
            nat: Whether or not the network will have NAT forwarding.
            ipv4: Enable or disable IPv4 support.
            ipv6: Enable or disable IPv6 support.
        """

        # If `self` is in the cache/instance pool; it means the attributes
        # are already set, do NOT touch them
        if self in self.__class__._instances.values():
            return
        self.__class__._instances[uuid] = self

        self.name: str = uuid
        """A *unique* name for the LAN network.

        For backends with named networks (such as libvirt), it is used as
        an identifier.
        """

        self.autodestroy = autodestroy
        """If set to ``True``, the network will be removed when empty"""

        self.nat: None | bool = nat
        """If set to ``True``, the network will be setup with NAT functionality."""

        if isinstance(ipv4, dict):
            ipv4 = IPv4Network(**ipv4)
        if isinstance(ipv6, dict):
            ipv6 = IPv6Network(**ipv6)

        self.ipv4: None | Literal["auto"] | IPv4Network = ipv4
        """Whether or not the network supports IPv4"""

        self.ipv6: None | Literal["auto"] | IPv6Network = ipv6
        """Whether or not the network supports IPv6"""

        self.deleted = False

        self._users: list[shared.ResourceUser] = [
            core.CoreMachine(u) for u in (users or [])
        ]

    def __new__(cls, *args, **kwargs) -> LAN:
        name: str = kwargs.get("uuid") if "uuid" in kwargs else args[0]
        if name in cls._instances:
            return cls._instances[name]
        return super().__new__(cls)

    @classmethod
    def file(cls) -> pathlib.Path:
        return conf.networks_file

    @property
    def uuid(self) -> core.UUID:
        """Retrieve the LAN UUID."""
        if self.name is None:
            raise ValueError("Missing machine name")
        return core.UUID(self.name)

    @uuid.setter
    def uuid(self, val: str) -> None:
        self.name = val

    def users(self) -> list[shared.ResourceUser]:
        return list(self._users)

    def add(self, machine: shared.ResourceUser) -> None:
        self._users.append(machine)
        self.save(update=True)

    def remove(self, machine: shared.ResourceUser) -> None:
        user_index = self._users.index(
            [*filter(lambda u: u.uuid == machine.uuid, self._users)][0]
        )
        self._users.pop(user_index)

        self.save(update=True)

    def dict(self) -> LAN.Serialized:
        """Serialize the network into a JSON friendly :class:`dict`."""
        if self.name is None:
            raise ValueError("Unnamed network")

        ipv4: None | Literal["auto"] | IPv4Network.Serialized
        ipv6: None | Literal["auto"] | IPv6Network.Serialized
        if self.ipv4 == "auto":
            ipv4 = "auto"
        elif self.ipv4 is None:
            ipv4 = None
        else:
            ipv4 = self.ipv4.dict()

        if self.ipv6 == "auto":
            ipv6 = "auto"
        elif self.ipv6 is None:
            ipv6 = None
        else:
            ipv6 = self.ipv6.dict()

        return {
            "uuid": self.uuid,
            "autodestroy": self.autodestroy,
            "nat": self.nat,
            "ipv4": ipv4,
            "ipv6": ipv6,
            "users": [u.uuid for u in self._users],
        }


def default() -> LAN:
    """Return the default network for new machines.

    The current strategy is to generate a new network, specific
    for each machine.

    Returns:
        The default network.
    """
    lan = LAN(uuid=uuid4().hex)
    lan.save()
    return lan


find = shared.Manager(LAN).load
"""Search a network by it's name"""


IPv6_SUBNET_PREFIX = "fd73:7069:6e00::/48"


def _random_ipv4() -> ipaddress.IPv4Network:
    a, b = secrets.token_bytes(2)
    return ipaddress.IPv4Network(f"10.{a}.{b}.0/24")


def _random_ipv6() -> ipaddress.IPv6Network:
    lan = ipaddress.IPv6Network(IPv6_SUBNET_PREFIX)
    random_subnet_id = secrets.token_hex(2)
    expl = lan.network_address.exploded.split(":")
    expl[3] = random_subnet_id
    return ipaddress.IPv6Network(":".join(expl) + "/64")


@overload
def random_subnet(version: Literal[4]) -> ipaddress.IPv4Network:
    ...


@overload
def random_subnet(version: Literal[6]) -> ipaddress.IPv6Network:
    ...


def random_subnet(
    version: Literal[4, 6]
) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    """Generate a random subnet.

    Returns:
        A random IPv(4|6) subnet.
    """
    if version == 4:
        return _random_ipv4()
    if version == 6:
        return _random_ipv6()
    raise ValueError(f"Invalid IP version: {version}")


@overload
def dhcp(
    net: ipaddress.IPv4Network,
) -> tuple[ipaddress.IPv4Address, ipaddress.IPv4Address]:
    ...


@overload
def dhcp(
    net: ipaddress.IPv6Network,
) -> tuple[ipaddress.IPv6Address, ipaddress.IPv6Address]:
    ...


def dhcp(
    net: ipaddress.IPv6Network | ipaddress.IPv4Network,
) -> (
    tuple[ipaddress.IPv4Address, ipaddress.IPv4Address]
    | tuple[ipaddress.IPv6Address, ipaddress.IPv6Address]
):
    """Generate a DHCP address range for the given network.

    Warning:
        The function assumes the first available address of the network
        is used as a gateway. The full address space of the network is
        used.
    """
    if net.version == 4:
        _, dhcp_start = itertools.islice(net.hosts(), 2)
        dhcp_end = ipaddress.IPv4Address(
            (int.from_bytes(net.broadcast_address.packed, "big") - 1)
        )
        return (dhcp_start, dhcp_end)
    if net.version == 6:
        raise TODO
    raise ValueError("Unknown IP version")
