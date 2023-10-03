"""Steps requires by libvirt machines"""


from spin.machine.destruction_steps import RemoveFromBackend, RemoveFromNetwork
from spin.machine.machine import DefinedMachine
from spin.machine.start_steps import Boot
from spin.machine.steps import DestructionStep, StartStep
from spin.plugin.libvirt.machine import MachineInterface
from spin.utils import ui
from spin.utils.dependency import dep

from . import xml
from .utils import parse_exception

try:
    import libvirt
except ImportError as exce:
    pass


@dep(before=Boot)
class StartNetwork(StartStep):
    """Start the libvirt network associated with the machine"""

    name = "Start network"
    description = "Starting machine network (if not already up)"

    @classmethod
    def accepts(cls, machine: DefinedMachine) -> bool:
        return isinstance(machine.backend, MachineInterface)

    @parse_exception
    def process(self):
        # HACK: This is rudimentary and supports a single networking mode
        # As with machines, we control it with XML
        if not isinstance(self.machine.backend, MachineInterface):
            raise ValueError("Incorrect backend: not libvirt")

        if self.machine.hardware.network is None:
            ui.instance().warning("Machine has no network")
            return

        if self.machine.hardware.network.mode == "user":
            ui.instance().notice("Automatic network management")
            return

        dom = self.machine.backend.domain()

        domxml = xml.from_str(dom.XMLDesc())
        xmlnode = domxml.find("devices/interface/source")
        if xmlnode is None:
            raise Exception("Could not find network name.")
        name = xmlnode.attrib["network"]
        if name is None:
            raise Exception("Could not find network name.")

        with libvirt.open(self.machine.backend.uri) as conn:
            net = conn.networkLookupByName(name)

        if not net.isActive():
            net.create()


@dep(requires=RemoveFromNetwork, before=RemoveFromBackend)
class DestroyNetwork(DestructionStep):
    """Destroy the network together with the machine"""

    name = "Removing network from libvirt"

    @classmethod
    def accepts(cls, machine: DefinedMachine) -> bool:
        return (
            machine.hardware.network is not None
            and machine.hardware.network.network is not None
            and isinstance(machine.backend, MachineInterface)
        )

    @parse_exception
    def process(self):
        if not isinstance(self.machine.backend, MachineInterface):
            raise ValueError("Incorrect backend: not libvirt")

        assert self.machine.hardware.network is not None
        assert self.machine.hardware.network.network is not None

        if self.machine.hardware.network.network.deleted is False:
            ui.instance().notice("Not deleting")
            return

        if self.machine.hardware.network.mode == "user":
            ui.instance().notice("Network in 'user' mode, not deleting.")
            return

        name = self.machine.hardware.network.network.uuid
        with libvirt.open(self.machine.backend.uri) as conn:
            net = conn.networkLookupByName(name)

        if net.isActive():
            ui.instance().notice("Network is active, stopping.")
            net.destroy()
        net.undefine()
