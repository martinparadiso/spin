"""Contains basic/core creation steps.
"""

from __future__ import annotations

import os
import pathlib
import warnings
from typing import Any, Literal, Type

import yaml

import spin.utils.constants
from spin.backend.base import DiskPool
from spin.errors import BackendError, Bug, MissingAttribute, NoBackend, require
from spin.image.edit import open_image
from spin.image.image import Image
from spin.machine.credentials import SSHCredential
from spin.machine.hardware import CDROM, Disk, SharedFolder
from spin.machine.machine import DefinedMachine, MachineUnderCreation, as_machine
from spin.machine.steps import CreationTask, CreationStep
from spin.machine.tracker import Tracker
from spin.utils import cloud_init, fileparse, ui
from spin.utils.config import conf
from spin.utils.crypto import fingerprint
from spin.utils.dependency import register, solves
from spin.utils.info import can_write
from spin.utils.load import Spinfolder


def _mk_task(name: str, doc: str) -> Type[CreationTask]:
    new_class = type(name, (CreationTask,), {"__doc__": doc})
    return new_class


OS = _mk_task("OS", "Task setting up the machine OS (if necessary).")
Network = _mk_task("Network", "Set up machine network")
MainDisk = _mk_task("MainDisk", "Set up the main file main disk" "")
ExtraStorage = _mk_task("ExtraStorage", "Create secondary/extra storage")
HostSharedFolder = _mk_task("HostSharedFolder", "Prepare host filesystem")
SharedFolderAutomount = _mk_task("SharedFolderAutomount", "Auto-mount shared folders")
CloudInitSourceDisk = _mk_task(
    "CloudInitSourceDisk", "Generte cloud-init data source CDROM"
)
CloudInitKeyExtraction = _mk_task(
    "CloudInitKeyExtraction", "Extract keys added to cloud-init"
)
StoreInTracker = _mk_task("StoreInTracker", "Store the machine in tracker")


class InsertSSHCredential(CreationTask):
    """Insert the corresponding SSH credential into the machine"""

    def __init__(self, credential: SSHCredential, machine) -> None:
        super().__init__(machine)
        self.credential = credential


@solves(ExtraStorage)
@register()
class ExtraStorageInPool(CreationStep):
    """Add extra disks/storage to the Machine."""

    name = "Insert CDs"
    description = "Inserting CDs into the machine"

    @classmethod
    def confidence(cls, task) -> int:
        if task.machine.backend.disk_location is None:
            return False
        if "pool" not in task.machine.backend.disk_location:
            return False
        return 0

    def solve(self, task) -> None:
        if (
            isinstance(self.machine.image, Image)
            and self.machine.image.props.type == "installation-media"
        ):
            assert self.machine.image.file is not None
            ui.instance().notice("Adding installation media disk")
            label = self.machine.image.filename
            if label is None:
                label = str(self.machine.image.name) + "-" + str(self.machine.image.tag)
            cdrom = CDROM(self.machine.image.file, label=label)
            ui.instance().debug(f"Adding install media CDROM {cdrom}")
            self.machine.add_disk(cdrom)
        # HACK: This is completely wrong:
        #   1. We reach for a libvirt specific setting
        #   2. Disk pool should have a default (passed as arg None), which is
        #      backend dependent, and then the backend queries the default value
        #      from the setting.
        #   3. The 'main' thing looks horrible.
        pool_name = (
            self.machine.backend.main.settings().pool or conf.settings.defaults.pool
        )
        pool = self.machine.backend.main.disk_pool(pool_name, create=True)

        for disk in self.machine.diskarray:
            ui.instance().notice(f"Adding: {disk}")
            if disk.uuid is None:
                disk.new_uuid()
            if disk not in pool.list_disks():
                pool.create_disk(disk)


@solves(HostSharedFolder)
@register(requires=[OS])
class SharedFolders(CreationStep):
    """Create and configure shared folders in host."""

    name = "Shared folders"
    description = "Creating folders in host"

    def __init__(self, machine: MachineUnderCreation) -> None:
        super().__init__(machine)
        self.rollback_dirs: list[pathlib.Path] = []

    @classmethod
    def confidence(cls, task) -> int:
        return 0

    def solve(self, task) -> None:
        for folder in self.machine.shared_folders:
            if folder.host_path.is_file():
                raise ValueError(
                    f"Path for shared folder {str(folder.host_path)} "
                    "exists and it's a regular file"
                )
            if not folder.host_path.exists():
                ui.instance().notice(f"Creating {str(folder.host_path)}")
                folder.host_path.mkdir()
                self.rollback_dirs.append(folder.host_path)

            arrow = "⟹ " if folder.read_only else "⟺ "
            ui.instance().notice(
                f"{str(folder.host_path)} {arrow} {str(folder.guest_path)}"
            )

    def rollback(self) -> None:
        for folder in self.rollback_dirs:
            ui.instance().notice(f"Removing shared folder directory {folder}")
            folder.rmdir()


@solves(SharedFolderAutomount)
@register(requires=[MainDisk, HostSharedFolder])
class EditFstab(CreationStep):
    """Try to modify fstab to auto-mount shared folders on boot."""

    name = "Auto-mount"
    description = "Auto-mount shared folders by editing `/etc/fstab` in the disk file"

    FSTAB_SECTION_BEGIN = "### SPIN MOUNTS BEGIN ###"
    FSTAB_SECTION_END = "### SPIN MOUNTS END ###"
    ENTRY_DIV = "\t"

    @classmethod
    def confidence(cls, task) -> int:
        has_tag_hint = task.machine.backend.shared_folder == "tag-hint"
        if not has_tag_hint:
            ui.instance().warning("Cannot automount: tag-hint not supported ")
            return False
        has_disk_file = task.machine.hardware.disk is not None
        if not has_disk_file:
            ui.instance().warning("Cannot automount: no main disk")
            return False
        is_not_DOS = (
            task.machine.image is None
            or task.machine.image.os is None
            # NOTE: fstab is not part of POSIX; but unix-like. So we ask
            # if we are *not* in a DOS/windows environment
            or task.machine.image.os.family != "windows"
        )
        if not is_not_DOS:
            ui.instance().warning("Cannot edit fstab: unknown image or DOS based")
            return False
        return -5

    def make_entry(self, machine: "DefinedMachine", folder: "SharedFolder") -> str:
        """Generate an fstab line from the given machine and folder

        Args:
            machine: The machine being processed.
            folder: The folder for which to generate the entry.

        Returns:
            A string generated with the given information.
        """
        tag = str(folder.guest_path)
        mnt_pnt = str(folder.guest_path)
        fs = machine.backend.shared_folder_fs
        mount_opts = ["ro" if folder.read_only else "rw"]
        mount_opts.extend(machine.backend.automount_fstab_opts)
        if conf.settings.shared_folder.extra_fstab_o is not None:
            mount_opts.append(conf.settings.shared_folder.extra_fstab_o)
        return self.ENTRY_DIV.join(
            [
                tag,
                mnt_pnt,
                fs,
                ",".join(mount_opts),
                "0",
                "0",
            ]
        )

    def solve(self, task) -> None:
        assert self.machine.hardware.disk is not None
        assert self.machine.hardware.disk.location is not None

        if not can_write(self.machine.hardware.disk.location):
            ui.instance().warning(f"Aborting FSTAB edit: cannot open disk file")
            return
        new_entries: list[str] = [
            self.make_entry(self.machine, f) for f in self.machine.shared_folders
        ]

        with open_image(self.machine.hardware.disk.location, read_only=False) as img:
            fstab_path_map: dict[spin.utils.constants.OS.SubfamilyLiteral, str] = {
                "linux": "/etc/fstab",
            }
            if (
                self.machine.image is not None
                and self.machine.image.os is not None
                and self.machine.image.os.subfamily is not None
            ):
                fstab_path = fstab_path_map[self.machine.image.os.subfamily]
            else:
                ui.instance().warning(
                    f"Could not determine OS in image; assuming /etc/fstab"
                )
                fstab_path = "/etc/fstab"
            ui.instance().debug(f"Looking for fstab in `{fstab_path}`")
            fstab = img.read_lines(fstab_path)

            start_old, end_old = len(fstab), len(fstab)

            for line in fstab:
                if line == self.FSTAB_SECTION_BEGIN:
                    start_old = fstab.index(line)
                if line == self.FSTAB_SECTION_END:
                    end_old = fstab.index(line)

            if all([start_old, end_old]) and end_old < start_old:
                raise Bug("Misformatted fstab, refussing to modify")

            if start_old != len(fstab):
                ui.instance().notice("Found existing fstab mapping, overwriting")
            new_fstab = fstab[:start_old] + fstab[end_old + 1 :]

            new_fstab.extend(
                [self.FSTAB_SECTION_BEGIN, *new_entries, self.FSTAB_SECTION_END]
            )

            img.write("/etc/fstab", "".join([f"{l}\n" for l in (new_fstab)]))
            for folder in self.machine.shared_folders:
                if not img.is_dir(folder.guest_path):
                    img.mkdir(folder.guest_path, parents=True)


@solves(InsertSSHCredential)
@register(requires=[MainDisk])
class AddSSHKey(CreationStep):
    """Insert SSH keys in the guest machine"""

    name = "Add SSH key(s)"
    description = "Inserting SSH keys into the guest machine"

    @classmethod
    def confidence(cls, task):
        is_linux = False
        if task.machine.image is not None and task.machine.image.os is not None:
            is_linux = task.machine.image.os.subfamily == "linux"
        if not is_linux:
            return False
        return -1

    def solve(self, task: InsertSSHCredential) -> None:
        assert self.machine.hardware.disk is not None
        assert self.machine.hardware.disk.location is not None

        if not can_write(self.machine.hardware.disk.location):
            raise ValueError("Cannot write modify disk image as current user")

        # HACK: Remove the list; it's a half migration from previous impl.
        creds: list[SSHCredential] = [task.credential]

        find_default_user = any(c.login is None for c in creds)
        with open_image(self.machine.hardware.disk.location, read_only=False) as disk:
            passwd = fileparse.passwd(
                disk.read_file("/etc/passwd", encoding="utf8").splitlines()
            )
            default_user: None | fileparse.PasswdEntry = None
            default_user_auth: None | str = None
            auth_keys_path = lambda home_path: home_path + "/.ssh/authorized_keys"

            if find_default_user:
                ui.instance().notice(
                    "Key(s) missing login: trying to find default user"
                )
                default_user = next((u for u in passwd if u.uid == 1000), None)
                if default_user is None:
                    ui.instance().warning("Could not found default user by UID 1000")
            for cred in creds:
                user: fileparse.PasswdEntry | None
                auth_keys: str
                if cred.login is None:
                    if default_user is None:
                        ui.instance().error(
                            (
                                f"Credential {cred} could not be added: missing"
                                " login, and default user could not be determined."
                            )
                        )
                        continue
                    user = default_user
                else:
                    user = next((e for e in passwd if e.username == cred.login), None)
                    if user is None:
                        ui.instance().error(
                            f"Could not find {cred.login} in guest passwd"
                        )
                        continue
                auth_keys = auth_keys_path(user.home)
                disk.write(auth_keys, cred.pubkey, append=True)
                disk.chown(auth_keys, user.uid, user.gid)
                disk.chmod(auth_keys, 0o644)


@solves(CloudInitSourceDisk)
@register(before=[ExtraStorage])
class CloudInitStep(CreationStep):
    """Generate the cloud-init ISO to insert into the Machine."""

    name = "Setting up cloud-init"

    @classmethod
    def confidence(cls, task) -> int:
        if task.machine.cloud_init is None:
            return False
        return 0

    def solve(self, task) -> None:
        from spin.machine.hardware import CDROM

        if self.machine.cloud_init is None:
            return

        iso_path = Spinfolder(as_machine(self.machine)).add_file(
            as_machine(self.machine), "cloud-init.img"
        )

        metadata = cloud_init.generate_metadata(
            instance_id=str(self.machine.uuid), hostname=self.machine.hostname
        )

        userdata: pathlib.Path | dict
        if isinstance(self.machine.cloud_init, str):
            userdata = pathlib.Path(self.machine.cloud_init)
        else:
            userdata = self.machine.cloud_init
        content = cloud_init.save_in_dir(userdata, metadata)
        cloud_init.make_iso(content, iso_path)
        self.machine.add_disk(CDROM(iso_path))


@solves(InsertSSHCredential)
@register(before=[CloudInitSourceDisk])
class AddNewKeysToCloudInit(CreationStep):
    """Merge the cloud-init keys and the keys in the machine."""

    name = "Add keys to cloud-init"
    description = "Adding dynamically generated keys to cloud-init"

    @classmethod
    def confidence(cls, task):
        if task.machine.cloud_init is None:
            return False
        return 10

    def solve(self, task: InsertSSHCredential):
        assert self.machine.cloud_init is not None
        if isinstance(self.machine.cloud_init, (str, pathlib.Path)):
            ui.instance().warning("Editing cloud-init file to add keys")
            with open(self.machine.cloud_init, "r", encoding="utf8") as f:
                ci: dict = yaml.load(f, yaml.SafeLoader)
            self.machine.cloud_init = ci
        if "users" not in self.machine.cloud_init:
            ui.instance().error("cloud-init has no `users` section, refusing to modify")
            return
        if len(self.machine.cloud_init["users"]) == 0:
            ui.instance().warning("Empty `users` key in cloud-init")

        cred = task.credential
        ui.instance().notice(f"Adding {cred}")
        if cred.login is None:
            if self.machine.cloud_init["users"][0] == "default":
                # The system is generating the default credentials; insert
                # the key into the global auth keys
                if "ssh_authorized_keys" not in self.machine.cloud_init:
                    self.machine.cloud_init["ssh_authorized_keys"] = []
                self.machine.cloud_init["ssh_authorized_keys"].append(cred.pubkey)
                return
            # If the first element is not 'default', we are overriding the
            # first element; add it there
            user = self.machine.cloud_init["users"][0]
        else:
            user = cloud_init.get_user(self.machine.cloud_init, cred.login)
            if user is None:
                ui.instance().warning(
                    f"Could not find login {cred.login} to insert the key in cloud-init"
                )
                return
        if "ssh_authorized_keys" not in user:
            user["ssh_authorized_keys"] = []
        if cred.pubkey in user["ssh_authorized_keys"]:
            ui.instance().debug(f"Key {fingerprint(cred)} already present")
            return
        user["ssh_authorized_keys"].append(cred.pubkey)


@solves(Network)
@register()
class NetworkSetup(CreationStep):
    """Setup the network in the backend"""

    name = "Setting up network"
    description = ""

    @classmethod
    def confidence(cls, task):
        return 0

    def solve(self, task):
        if self.machine.hardware.network is None:
            return
        nic = self.machine.hardware.network
        if isinstance(nic.network, str):
            raise ValueError("Network not loaded")

        if nic.network is None:
            return

        in_backend = self.machine.backend.main.network.get(nic.network.uuid)
        if in_backend is None:
            self.machine.backend.main.network.create(nic.network)
            net = nic.network
            self.rollbacks.append(lambda: self.machine.backend.main.network.delete(net))


@solves(MainDisk)
@register()
class MainDiskInPool(CreationStep):
    name = "Setting up main disk"
    description = "Create main disk in a storage pool"

    def __init__(self, machine: MachineUnderCreation) -> None:
        super().__init__(machine)
        self.pool: None | DiskPool = None
        self.disk_to_destroy: None | Disk = None

    def rollback(self) -> None:
        if self.disk_to_destroy is not None:
            assert self.pool is not None
            self.pool.remove(self.disk_to_destroy)

    @classmethod
    def confidence(cls, task) -> int:
        if task.machine.backend.disk_location is None:
            return False
        if "pool" not in task.machine.backend.disk_location:
            return False
        return 10

    def solve(self, task) -> None:
        assert self.machine.hardware.disk is not None
        assert self.machine.hardware.disk.location is None
        if self.machine.hardware.disk.pool is None:
            self.machine.hardware.disk.pool = (
                self.machine.backend.main.settings().pool or conf.settings.defaults.pool
            )
        pool = self.machine.backend.main.disk_pool(
            self.machine.hardware.disk.pool, create=True
        )
        self.machine.hardware.disk.new_uuid()

        fill = False
        if (
            isinstance(self.machine.image, Image)
            and self.machine.image.exists()
            and self.machine.image.props.type == "disk-image"
        ):
            if self.machine.image.props.supports_backing:
                pool.import_image(self.machine.image)
                self.machine.hardware.disk.backing_image = self.machine.image
            else:
                fill = True

        ui.instance().notice(f"Creating main disk in pool {pool}")
        ret_ok, msg = pool.create_disk(self.machine.hardware.disk)
        if fill:
            assert self.machine.image is not None
            pool.fill(self.machine.hardware.disk, self.machine.image.file)
        if not ret_ok:
            raise BackendError(msg)

        def rollback() -> None:
            disk = self.machine.hardware.disk
            pool_ = pool
            if disk is not None:
                pool_.remove(disk)

        self.rollbacks.append(rollback)


@solves(OS)
@register(requires=[MainDisk])
class PreinstalledOS(CreationStep):
    """Make sure the main disk has an OS."""

    name = "Preinstalled OS"
    description = "Checking if image provides an OS"

    @classmethod
    def confidence(cls, task) -> int:
        disk_image = (
            task.machine.image is not None
            and task.machine.image.props.type == "disk-image"
            and bool(task.machine.image.props.contains_os)
        )
        if not disk_image:
            return False
        return 10

    def solve(self, task) -> None:
        if self.machine.image is None:
            ui.instance().warning("Machine has no image")
            return
        if self.machine.image.props.contains_os is None:
            ui.instance().warning("Image manifest does not have OS information")
        if self.machine.image.props.contains_os:
            ui.instance().notice("Image manifest reports an OS")
        else:
            ui.instance().warning("Image manifest reports no OS for image")


@solves(MainDisk)
@register()
class MainDiskAnywhere(CreationStep):
    """Create a disk in any part of the host filesystem"""

    name = "Creating main disk"
    description = "Create main disk in the filesystem"

    def __init__(self, machine: MachineUnderCreation) -> None:
        super().__init__(machine)

    @classmethod
    def confidence(cls, task) -> int:
        if task.machine.backend.disk_location is None:
            return False
        if "anywhere" not in task.machine.backend.disk_location:
            return False

        # Pool storage is 0, and it's 'better'
        return -5

    def solve(self, task) -> None:
        if self.machine.hardware.disk is None:
            return

        disk = self.machine.hardware.disk

        if disk.backing_image is not None and (
            disk.backing_image.file is None or not disk.backing_image.file.exists()
        ):
            raise ValueError(f"Backing image {disk.backing_image} is missing file.")

        if disk.exists():
            ui.instance().notice(f"Disk {disk.location} exists. Skipping creation.")
            return

        if disk.location is None:
            if self.machine.folder is None:
                raise Exception("Missing machine folder")
            if disk.uuid is None:
                disk.new_uuid()
            assert disk.uuid is not None
            disk_path = Spinfolder(as_machine(self.machine)).add_file(
                as_machine(self.machine), disk.uuid
            )
            ui.instance().notice(f"Missing disk path. Creating in {disk_path}")
            disk.location = disk_path

        backend = self.machine.backend
        if backend is None or isinstance(backend, type):
            raise NoBackend

        if isinstance(self.machine.image, Image):
            if self.machine.image.file is None:
                raise Exception("Missing localpath for image.")
            if self.machine.image.props.type == "disk-image":
                self.machine.hardware.disk.backing_image = self.machine.image
            else:
                NotImplementedError()

        # HACK: This should be separate
        from spin.plugin.api import register

        providers = register.disk_creators[disk.format]

        create = providers[0]
        ui.instance().notice(f"Using {create.__module__} plugin for disk creation")

        create(disk)
        os.chown(disk.location, -1, -1)

        def rollback():
            if disk.location is None:
                return
            disk.location.unlink(True)

        self.rollbacks.append(rollback)


@solves(ExtraStorage)
@register()
class ExtraStorageAnywhere(CreationStep):
    """Create a disk in any part of the host filesystem"""

    name = "Creating extra disks"
    description = "Create extra disk(s) in the filesystem"

    @classmethod
    def confidence(cls, task) -> int:
        if task.machine.backend.disk_location is None:
            return False
        if "anywhere" not in task.machine.backend.disk_location:
            return False

        # Pool storage is 0, and it's 'better'
        return -5

    def solve(self, task) -> None:
        warnings.warn("Extra storage anywhere not implemented")


@solves(OS)
@register(requires=[ExtraStorage, MainDisk, NetworkSetup])
class ManualInstallStep(CreationStep):
    """Install the OS provided by a CDROM/ISO."""

    name = "Installing the OS"

    @classmethod
    def confidence(cls, task) -> int | Literal[False]:
        if task.machine.image is None:
            return False
        return 10

    def solve(self, task) -> None:
        assert self.machine.image is not None

        if self.machine.image.props.type != "installation-media":
            raise Bug("Install type not supported")

        boot_order = list(self.machine.boot_order)
        shared_folders = self.machine.shared_folders

        ui.instance().notice("Overriding default boot order")

        if not require(self.machine.image.file):
            raise MissingAttribute(self.machine.image, "file")
        installcds = [
            d for d in self.machine.diskarray if d.label == self.machine.image.filename
        ]
        if len(installcds) == 0:
            raise Exception("Internal error: missing installation image")
        if len(installcds) > 1:
            raise Exception("Internal error: multiple installation images")
        installcd = installcds[0]
        if installcd in self.machine.boot_order:
            self.machine.boot_order.remove(installcd)

        self.machine.boot_order = [installcd, *self.machine.boot_order]

        # We need to remove shared folders (and maybe other non-essential stuff)
        # in order to boot now.
        self.machine.shared_folders = []

        if self.machine.backend is None or isinstance(self.machine.backend, type):
            raise Exception("Missing machine backend.")
        self.machine.backend.bootstrap_boot()

        for action in ui.instance().iterate(self.machine.image.on_install):
            ok = action.execute(as_machine(self.machine))
            if not ok:
                raise Exception(f"Action: {action} failed")

        self.machine.boot_order = boot_order
        self.machine.shared_folders = shared_folders
        shutdown_ok = self.machine.backend.acpi_shutdown(timeout=60)
        if not shutdown_ok:
            raise BackendError("ACPI shutdown failed")
        if self.machine.backend.is_running():
            raise BackendError("Machine still running.")


@solves(CloudInitKeyExtraction)
@register(after=[CloudInitStep])
class ExtractCloudInitCreds(CreationStep):
    name = "Extracting new credentials inserted in cloud-init"

    @classmethod
    def confidence(cls, task) -> int:
        if task.machine.cloud_init is None:
            return False
        return 0

    def solve(self, task):
        if self.machine.cloud_init is None:
            ui.instance().debug("No cloud-init data to extract data from")
            return
        userdata = self.machine.cloud_init
        if isinstance(userdata, (str, pathlib.Path)):
            with open(userdata, encoding="utf8") as f:
                ci_file: dict[str, Any] = yaml.load(f, yaml.SafeLoader)
                userdata = ci_file
        if not userdata:
            return
        cloud_init.extract_credentials(userdata, self.machine.ssh)


@solves(StoreInTracker)
@register()
class StoreInTrackerStep(CreationStep):
    name = "Storing machine in register"

    @classmethod
    def confidence(cls, task: CreationTask):
        return 0

    def solve(self, task: CreationTask) -> None:
        tracker = Tracker()
        tracker.add(as_machine(task.machine))
