"""High-level interface for machine processing.
 
Inthis file are tools to move the machine from one state to the
other; for instance to create, start and destroy.
"""

from __future__ import annotations

import os
import pathlib
import warnings
from typing import TYPE_CHECKING

from spin.machine.machine import Group, as_machine, is_created, is_under_creation
from spin.utils.load import Spinfolder

if TYPE_CHECKING:
    from spin.machine.machine import Machine

from spin.errors import Bug, UnresolvedTasks
from spin.machine.steps import (
    CreationTask,
    CreationStep,
    DefinitionStep,
    DestructionStep,
    StartStep,
)
from spin.utils import ui
from spin.utils.config import conf
from spin.utils.dependency import dependencies, pool

from . import creation_steps, definition_steps, destruction_steps


class MachineProcessor:
    """Generates the appropriate environment for a machine to work

    The class takes a :py:class:`Machine` object and performs all the necessary
    modifications to the host/environment so the machine can run without errors.

    For instance, the processor is in charge of creating networks, folders, disk
    files.
    """

    def __init__(self, machine: "Machine", track: bool = True) -> None:
        """
        Args:
            machine: The machine to be launched.
            track: If set to `True` the machine is added to the local machine
                registry.
        """
        self.machine = machine
        """The machine to be launched.
        
        The processor takes this machine as an inforamation source and modifies
        the host to match its requirements. For instance, it will create folders
        and networks according to the machine specification.
        """

        self.group: None | Group = None
        """Group where the machine will be stored"""

        self.dry_run: bool = False

        self.tasks: list[CreationTask] = []
        """Collection of tasks to fulfill"""

        warnings.warn("track not implemented")

    def complete_definition(self) -> None:
        """Complete the definition of the virtual machine

        Fill the empty values in the machine definition with the defaults.
        """

        # HACK: Refactor this global/class-level variable system into
        # something nicer
        old_group = DefinitionStep.group
        DefinitionStep.group = self.group

        defs = dependencies.fullgraph(cond=lambda n: n.accepts(self.machine), instance_of=DefinitionStep)  # type: ignore

        with ui.instance().section(
            f"Completing machine {self.machine.name} | {len(defs)} steps"
        ):
            for step_cls in ui.instance().iterate(
                defs, fmt=lambda s: f"{s.name or s.__name__}: {s.description}"
            ):
                step = step_cls(self.machine, self.tasks)
                step.process()

        DefinitionStep.group = old_group

    def _generate_tasks(self) -> list[CreationTask]:
        assert is_under_creation(self.machine)
        ret: list[CreationTask] = [
            *self.tasks,
            creation_steps.OS(self.machine),
            creation_steps.Network(self.machine),
            creation_steps.MainDisk(self.machine),
            creation_steps.ExtraStorage(self.machine),
            creation_steps.StoreInTracker(self.machine),
        ]
        if self.machine.cloud_init:
            ret.append(creation_steps.CloudInitKeyExtraction(self.machine))
        if self.machine.shared_folders:
            ret.append(creation_steps.HostSharedFolder(self.machine))
            ret.append(creation_steps.SharedFolderAutomount(self.machine))
        if self.machine.cloud_init:
            ret.append(creation_steps.CloudInitSourceDisk(self.machine))
        for cred in self.machine.ssh:
            assert not callable(cred)
            ret.append(creation_steps.InsertSSHCredential(cred, self.machine))
        for task in ret:
            task.machine = self.machine
        return ret

    def _save_network(self) -> None:
        if self.machine.hardware.network is None:
            return
        net = self.machine.hardware.network.network
        if net is None or isinstance(net, str):
            ui.instance().warning(
                f"Missing network on interface {self.machine.hardware.network}"
            )
            return
        if self.dry_run:
            return
        # NOTE: We update in case the network is shared
        net.save(update=True)

    def _mkdir(self, path: pathlib.Path, *args, **kwargs):
        if self.dry_run:
            ui.instance().notice(f"Dry run: not creating folder {str(path)}")
            return
        path.mkdir(*args, **kwargs)
        os.chown(path, -1, -1)
        # TODO: Reimplement rollback
        # self.rollbacks.insert(0, lambda: path.rmdir())

    def _persistent_storage(self) -> None:
        """Create the metadata folder for the machine

        This step makes the ``.spin`` folder alongside the ``spinfile``
        where all the configuration and metadata about the machine is kept.
        """
        self._save_network()
        if self.machine.spinfile is None:
            ui.instance().notice(
                "Machine has no spinfile, creating in orphans directory"
            )
            parent_dir = conf.orphanage / str(self.machine.uuid)

            if parent_dir.exists():
                raise Bug(f"Folder for orphan {self.machine.uuid} exists.")

            self._mkdir(parent_dir, mode=conf.settings.orphan_folder_mode, parents=True)
        else:
            parent_dir = self.machine.spinfile.parent

        spinfolder = Spinfolder(parent=parent_dir)
        if not spinfolder.exists():
            spinfolder.init()
        spinfolder.save_machine(as_machine(self.machine), update=True)
        self.machine.folder = spinfolder.location

    def create(self, rollback_on_fail: bool = True) -> None:
        """Create the machine in the backend.

        This method creates all the necessary, missing, elements for the
        machine to work properly. Among other things, it creates shared folders,
        networks and other things.

        Args:
            rollback_on_fail: If some procedure fails, try to rollback all the
                applied changes.
        """
        with ui.instance().section(f"Creating the machine: {self.machine.name}"):
            self._persistent_storage()

            if not is_under_creation(self.machine):
                raise Bug("Machine is not ready for construction")
            tasks: list[CreationTask] = self._generate_tasks()

            steps, tasks_assignment = pool.creation_pipeline(
                tasks,
                select=lambda options, task: max(
                    options, key=lambda o: o.confidence(task)
                ),
            )

            rollback: list[CreationStep] = []
            ui.instance().debug(f"Creation steps: {steps}")
            try:
                for step_cls in ui.instance().iterate(
                    steps, fmt=lambda s: f"{s.name or s.__name__}: {s.description}"
                ):
                    step = step_cls(self.machine)

                    for task in ui.instance().iterate(
                        tasks_assignment.get(step_cls, [])
                    ):
                        step.solve(task)
                        tasks.remove(task)
                    rollback.append(step)
            except:
                ui_ = ui.instance()
                ui_.fatal("Exception during machine creation")
                ui_.info("Attempting rollback")
                for step in ui_.iterate(rollback[::-1], lambda s: f"Undoing {s.name}"):
                    step.rollback()
                raise

        if len(tasks) > 0:
            raise UnresolvedTasks(tasks)

        self.save_to_disk()
        self.machine.backend.update()

    def start(self, print_console: bool = False, rollback_on_fail: bool = True) -> None:
        """Start the machine in the backend.

        This method performs all the necessary last-minute modifications, runs
        any pre- and post- boot scripts. Returns only when the machine is booted
        and all actions are performed.

        Args:
            rollback_on_fail: If some procedure fails, try to rollback all the
                applied changes.
            print_console: If set to ``True``, the guest console port is printed to
                stdout.
        """
        if rollback_on_fail:
            ui.instance().warning("Rollback on fail not implemented")

        restore_pc = StartStep.print_console
        StartStep.print_console = print_console

        steps = dependencies.fullgraph(
            cond=lambda n: n.accepts(self.machine), instance_of=StartStep  # type: ignore
        )
        if not is_created(self.machine):
            raise ValueError("Cannot start: machine not created")
        machine = self.machine

        with ui.instance().section(f"Starting: {self.machine.name}"):
            for step_cls in ui.instance().iterate(
                steps, fmt=lambda s: f"{s.name or s.__name__}: {s.description}"
            ):
                step = step_cls(self.machine)
                step.process()

        self.save_to_disk()
        StartStep.print_console = restore_pc

    def save_to_disk(self) -> None:
        """Save the machine information to the default disk file

        Raises:
            Exception: If the machine is missing the folder.

        Warning:
            This writes to the file without any checks. No checking is performed
            between the --possibly-- existing machine stored in the file and
            the current save.
        """
        if self.machine.folder is None:
            raise ValueError("Missing machine folder")
        Spinfolder(location=self.machine.folder).save_machine(self.machine, update=True)

    def destroy(
        self, *, delete_storage: bool = False, rollback_on_fail: bool = True
    ) -> None:
        """Destroy a machine.

        A `destruction` implies deleting files created by the machine,
        deleting it's information from the backend, and possibly disk files.

        Args:
            delete_storage: If set to ``True``, steps to delete all associated
                storage files will be called. For instance, disk files, cloud-init
                CDROMs.
        """
        # TODO: Destruction should proceed even after errors; trying to destroy
        # everything and warn the user about un-deleted resources
        if rollback_on_fail:
            ui.instance().warning("Rollback on fail not implemented")
        if not is_created(self.machine):
            raise ValueError("Machine is not created")

        class_delete_storage = DestructionStep.delete_storage
        DestructionStep.delete_storage = delete_storage
        steps = dependencies.fullgraph(
            cond=lambda n: n.accepts(self.machine), instance_of=DestructionStep  # type: ignore
        )

        with ui.instance().section(f"Destroying machine: {self.machine.name}"):
            for step_cls in ui.instance().iterate(
                steps, fmt=lambda s: f"{s.name or s.__name__}: {s.description}"
            ):
                step = step_cls(self.machine)
                step.process()

        DestructionStep.delete_storage = class_delete_storage
