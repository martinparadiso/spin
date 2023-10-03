"""Contains basic/core creation steps.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spin.machine import network
from spin.machine.credentials import SSHCredential
from spin.machine.machine import ElementalMachine
from spin.utils.spinfile import gen_ssh_keys

if TYPE_CHECKING:
    from spin.machine.machine import Machine

from spin.errors import Bug, NotFound
from spin.machine.steps import DefinitionStep
from spin.utils import ui
from spin.utils.config import conf
from spin.utils.dependency import dep


@dep
class NameStep(DefinitionStep):
    """Fill information and missing string values."""

    name = "Populating basic metadata"
    description = None

    @classmethod
    def accepts(cls, machine: ElementalMachine) -> bool:
        return True

    def process(self) -> None:
        if self.machine.name is None:
            self.machine.name = f"spin-{self.machine.uuid[:8]}"

        if self.machine.hostname is None:
            self.machine.hostname = self.machine.name


# TODO: Change this before, to a NetworkConfiguration(after=...)
@dep(before="NetworkConfiguration")
class GroupStep(DefinitionStep):
    """Setup the group information of the machine."""

    name = "Setting group"

    @classmethod
    def accepts(cls, machine: Machine) -> bool:
        return cls.group is not None and machine.group is None

    def process(self):
        self.machine.group = self.__class__.group


@dep(requires=NameStep)
class BackendStep(DefinitionStep):
    """Set the machine backend, depending on what is available."""

    name = "Backend"
    description = "Setting up backend connection"

    @classmethod
    def accepts(cls, machine: "Machine") -> bool:
        return True

    def process(self) -> None:
        if self.machine.backend is None:
            new_backend = conf.default_backend()()
            self.machine.backend = new_backend.machine(self.machine)
        if isinstance(self.machine.backend, type):
            self.machine.backend = self.machine.backend(self.machine)


@dep(requires=BackendStep)
class NetworkConfiguration(DefinitionStep):
    """Configure the machine network."""

    name = "Configuring network"

    @classmethod
    def accepts(cls, machine: Machine) -> bool:
        return machine.hardware.network is not None

    def process(self):
        nic = self.machine.hardware.network
        assert nic is not None

        if nic.network is None:
            if self.group is not None:
                raise Bug("Network should be configured by the group")
            ui.instance().notice("No network set; creating new")
            nic.network = network.default()

        if isinstance(nic.network, str):
            nic.network = network.find(nic.network)
            if nic.network is None:
                raise NotFound(f"Network named {nic.network}")

        # TODO: Find a way to force the registration of the machine,
        # the user *could* set the network outside this function, and
        # create a un-referenced resource.
        nic.network.add(self.machine)


@dep(requires=NameStep)
class GenerateInsecureKeys(DefinitionStep):
    """Generate temporary --insecure-- SSH keys."""

    name = "Insecure keys"
    description = "Inserting insecure key generator for accessing the machine"

    @classmethod
    def accepts(cls, machine: "Machine") -> bool:
        return True

    def process(self) -> None:
        login: None | str = None
        if (
            self.machine.image is not None
            and len(self.machine.image.props.usernames) >= 1
        ):
            login = self.machine.image.props.usernames[0]
        self.machine.ssh.append(
            gen_ssh_keys(login=login, comment=f"insecure-key-for-{self.machine.uuid}")
        )
        if conf.settings.default_ssh_key is not None:
            self.machine.ssh.append(
                SSHCredential(
                    login=login,
                    pubkey=conf.settings.default_ssh_key,
                    comment="User default SSH key",
                )
            )


@dep
class ValidateImageAndDisk(DefinitionStep):
    """Make sure the machine disk backing is linear."""

    name = "Image/disk backing"
    description = "Validating there is no overlap of image and disk backing"

    @classmethod
    def accepts(cls, machine: "Machine") -> bool:
        return True

    def process(self) -> None:
        has_image = self.machine.image is not None
        has_backing = (
            self.machine.hardware.disk is not None
            and self.machine.hardware.disk.backing_image is not None
        )

        if has_image and has_backing:
            raise ValueError("Cannot have both a base image and a disk backing image")


@dep(requires=GenerateInsecureKeys)
class GenerateKeys(DefinitionStep):
    """Generate/insert SSH keys stored as callables."""

    name = "Generate keys"
    description = "Replacing callbacks with actual keys"

    @classmethod
    def accepts(cls, machine: "Machine") -> bool:
        return True

    def process(self) -> None:
        repl: dict[int, SSHCredential] = {}
        for key_or_call in self.machine.ssh:
            if callable(key_or_call):
                repl[self.machine.ssh.index(key_or_call)] = key_or_call()

        for index, key in repl.items():
            self.machine.ssh[index] = key
