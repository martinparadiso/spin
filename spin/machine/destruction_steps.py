"""Contains destruction steps to execute during machine destruction
"""
from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

from spin.machine.machine import CreatedMachine, as_machine
from spin.utils.load import Spinfolder

if TYPE_CHECKING:
    from spin.machine.machine import DefinedMachine

from spin.machine.steps import DestructionStep
from spin.utils import ui
from spin.utils.dependency import dep


@dep(before={"RemovePersistentStorage", "RemoveFromBackend"})
class RemoveDiskFromPool(DestructionStep):
    """Remove a disk from a backend-managed pool"""

    name = "Delete disk from pool"

    @classmethod
    def accepts(cls, machine: "DefinedMachine") -> bool:
        if not cls.delete_storage:
            return False
        main_disk_in_pool = (
            machine.hardware.disk is not None and machine.hardware.disk.pool is not None
        )
        other_disk_in_pool = any(d.pool is not None for d in machine.diskarray)
        return main_disk_in_pool or other_disk_in_pool

    def process(self):
        assert self.machine.hardware.disk is not None
        assert self.machine.hardware.disk.pool is not None
        for d in [self.machine.hardware.disk, *self.machine.diskarray]:
            pool = self.machine.backend.main.disk_pool(
                self.machine.hardware.disk.pool, create=False
            )
            if pool is None:
                warnings.warn(f"Missing pool for {d}")
                continue
            ui.instance().notice(f"Deleting {d}")
            ok = pool.remove(d)
            if not ok:
                warnings.warn(f"Failed to remove disk {d} from pool")
        return True, None


@dep()
class RemovePersistentStorage(DestructionStep):
    name = "Removing machine files and metadata"

    @classmethod
    def accepts(cls, machine: "DefinedMachine") -> bool:
        return True

    def process(self):
        spinfolder = Spinfolder(location=self.machine.folder)
        spinfolder.delete_machine(as_machine(self.machine), associated_files=True)
        if len(spinfolder.get_machine()) == 0:
            ui.instance().notice("Removing folder")
            spinfolder.delete()


@dep(before=RemovePersistentStorage)
class RemoveInsecureKeys(DestructionStep):
    name = "Remove keys"
    description = "Removing insecure keys"

    @classmethod
    def accepts(cls, machine: "DefinedMachine") -> bool:
        return any(
            cred.comment.startswith("insecure-key-for")
            for cred in machine.ssh
            if cred.comment is not None
        )

    def process(self):
        for cred in filter(
            lambda c: c.comment is not None
            and c.comment.startswith("insecure-key-for"),
            self.machine.ssh,
        ):
            if cred.identity_file is None:
                ui.instance().warning(f"No private key file for credential {cred}")
                continue
            for file in (cred.identity_file, cred.identity_file.with_suffix(".pub")):
                ui.instance().notice(f"Removing {file}")
                file.unlink()


@dep
class RemoveFromNetwork(DestructionStep):
    """Remove the machine from the network"""

    name = "Removing from network"

    @classmethod
    def accepts(cls, machine: CreatedMachine) -> bool:
        return (
            machine.hardware.network is not None
            and machine.hardware.network.network is not None
        )

    def process(self):
        nic = self.machine.hardware.network
        assert nic is not None
        assert nic.network is not None

        vm = as_machine(self.machine)
        nic.network.remove(vm)


@dep(before=RemovePersistentStorage)
class RemoveFromBackend(DestructionStep):
    """Remove the machine from the backend during destruction"""

    name = "Deleting from backend"

    @classmethod
    def accepts(cls, machine: "DefinedMachine") -> bool:
        return machine.backend.exists()

    def process(self):
        self.machine.backend.delete()


@dep
class RemoveFromTracker(DestructionStep):
    name = "Deleting from spin tracker"

    @classmethod
    def accepts(cls, machine: "DefinedMachine") -> bool:
        from spin.machine.tracker import Tracker

        tracker = Tracker()
        return tracker.find(uuid=machine.uuid) is not None

    def process(self):
        from spin.machine.machine import as_machine
        from spin.machine.tracker import Tracker

        tracker = Tracker()
        tracker.remove(as_machine(self.machine))
