from __future__ import annotations

import ipaddress
from typing import Literal, Optional, overload

from spin.backend.base import (
    Backend,
    DiskPool,
    MachineInterface,
    NetworkInterface,
    ReturnType,
)
from spin.errors import TODO
from spin.machine import network
from spin.machine.connection import SerialConnection
from spin.machine.machine import Machine
from spin.utils.config import BackendCommonSettings
from spin.utils.constants import MACHINE_STATE_LITERAL


class FakeMachineInterface(MachineInterface):
    disk_location = ("anywhere",)

    def __init__(self, machine: "Machine", *args, **kwargs) -> None:
        super().__init__(machine, *args, **kwargs)

        self._state: MACHINE_STATE_LITERAL = "DEFINED"

    def create(self, start: bool = False) -> ReturnType:
        self._state = "CREATED"
        return True, None

    def update(self) -> ReturnType:
        return True, None

    def start(self, paused: bool = False) -> ReturnType:
        self._state = "RUNNING"
        return True, None

    def acpi_shutdown(self, timeout: int | float) -> ReturnType:
        self._state = "SHUTOFF"
        return True, None

    def force_stop(self) -> ReturnType:
        self._state = "SHUTOFF"
        return True, None

    def acpi_reboot(self, timeout: int | float) -> ReturnType:
        self._state = "RUNNING"
        return True, None

    def force_reboot(self) -> ReturnType:
        self._state = "RUNNING"
        return True, None

    def pause(self) -> ReturnType:
        self._state = "PAUSED"
        return True, None

    def unpause(self) -> ReturnType:
        self._state = "RUNNING"
        return True, None

    def bootstrap_boot(self) -> ReturnType:
        self._state = "RUNNING"
        return True, None

    def delete(self) -> ReturnType:
        self._state = "UNKNOWN"
        return True, None

    def state(self) -> MACHINE_STATE_LITERAL:
        return self._state

    def exists(self) -> bool:
        return self._state in (
            "CREATED",
            "SHUTOFF",
            "RUNNING",
            "PAUSED",
        )

    def is_running(self) -> bool:
        return self._state == "RUNNING"

    def is_shutoff(self) -> bool:
        return self._state == "SHUTOFF"

    @property
    def main_ip(self) -> None | ipaddress.IPv4Address | ipaddress.IPv6Address:
        if self.is_running():
            return ipaddress.IPv4Address("192.168.0.100")
        return None

    def has_console_port(self) -> bool:
        return False

    def console_port(self) -> None | SerialConnection:
        return None

    def eject(self, *dev) -> list:
        return []

    def dict(self):
        return {
            "mod": self.main.__module__,
            "cls": self.main.__class__.__qualname__,
        }


class FakeNetwork(NetworkInterface):
    """Fake network system"""

    known_networks: list[network.LAN] = []

    def get(self, name: network.LAN.Reference | str) -> Optional[network.LAN]:
        matches = [*filter(lambda net: net.name == name, self.__class__.known_networks)]
        if len(matches) == 0:
            return None
        return matches[0]

    def create(self, net: network.LAN) -> None:
        if net.name is None:
            raise ValueError("Unnamed network")
        existing = self.get(net.name)
        if existing is not None:
            self.__class__.known_networks.remove(existing)
        self.__class__.known_networks.append(net)

    def delete(self, net: network.LAN) -> None:
        # Do not use index() or remove(), since the object comparison
        # may result in false negatives
        if net.name is None:
            raise ValueError("Unnamed network")
        to_remove = self.get(net.name)
        if to_remove is None:
            raise ValueError(f"Network {net.name} not found")
        self.__class__.known_networks.remove(to_remove)


class FakeBackend(Backend):
    """Fake 'fully functional' backend for testing"""

    machines: dict[str, tuple[Machine, MachineInterface]] = {}

    def __init__(self) -> None:
        self.network = FakeNetwork()

    @classmethod
    def reset_backend(cls) -> None:
        """Reset the backend to the initial state"""
        cls.machines = {}

    def find(self, *, uuid: Optional[str] = None) -> Optional[Machine]:
        assert uuid is not None
        return self.__class__.machines.get(uuid, (None, None))[0]

    def machine(self, machine: Machine) -> FakeMachineInterface:
        assert machine.uuid not in self.__class__.machines
        vm = FakeMachineInterface(machine)
        vm.main = self
        self.__class__.machines[machine.uuid] = machine, vm
        return vm

    @classmethod
    def settings(cls) -> BackendCommonSettings:
        return BackendCommonSettings(pool=None)

    @classmethod
    def load(cls, machine: "Machine", **kwargs) -> MachineInterface:
        if machine.uuid in cls.machines:
            return cls.machines[machine.uuid][1]
        return cls().machine(machine)

    @overload
    def disk_pool(self, name: str, *, create: Literal[True]) -> DiskPool:
        ...

    @overload
    def disk_pool(self, name: str, *, create: Literal[False]) -> None | DiskPool:
        ...

    @overload
    def disk_pool(self, name: str, *, create: bool) -> None | DiskPool:
        ...

    def disk_pool(self, name: str, *, create: bool = False) -> None | DiskPool:
        raise TODO
