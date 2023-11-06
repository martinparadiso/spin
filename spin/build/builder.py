"""Performs the actual build

The builder normally delegates all implementation to other classes, it composes
all those objects and calls them in the correct order
"""

from __future__ import annotations
import dataclasses

import datetime
import json
import pathlib
import re
import secrets
import shutil
import traceback
import urllib.error
from abc import abstractmethod

import warnings
from spin.errors import TODO, Bug, CommandFailed, NotFound
from spin.machine.connection import open_ssh
from spin.machine.hardware import Disk
from spin.machine.machine import Machine

import spin.utils.info
import spin.utils.config
from spin.build.image_definition import ImageDefinition
from spin.image.database import Database
from spin.image.image import Image
from spin.utils.dependency import dep, dependencies
from spin.utils.sizes import Size
from spin.utils.transfer import NetworkTransfer
from spin.utils import ui


class BuildResult:
    """Image build output

    Attributes:
        success (bool) : True if the build succeeded, false if not
        build_start (datetime) : point in time when the build was started
        build_end (datetime) : point in time when the build finalized, available
            once the `done()` method is called
        build_duration (timedelta) : time spent building the image, available
            once the `done()` method is called
    """

    def __init__(self) -> None:
        self.success = False
        self.build_start = datetime.datetime.now()
        self.build_end: datetime.datetime
        self.build_duration: datetime.timedelta
        self.nsteps: int
        """Number of steps the build took"""

        self.image: None | Image = None
        """The image --on success-- or None if the image build failed"""

        self.exception: None | BaseException = None
        """Exception (possibly) raised during the build"""

    def done(self, success: bool) -> None:
        """Mark the end of the build process

        This method sets the finish time (build_end attribute), of the build
        process, and also sets the total time of the build, counting since the
        object initialization.

        Args:
            success (bool) : true if the build was successful, false otherwise
        """
        self.build_end = datetime.datetime.now()
        self.build_duration = self.build_end - self.build_start
        self.success = success


class BuildStep:
    """Base build step, defines interface and typing hints"""

    name: str
    """Friendly name to give the user, descriptive about the step"""

    def __init__(self, builder: SingleBuilder) -> None:
        self.builder: SingleBuilder = builder
        """The *builder* organizing this build procedure"""

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"

    @classmethod
    @abstractmethod
    def accepts(cls, builder: SingleBuilder) -> bool:
        """Check if the image requires this build step

        Args:
            builder: The builder object organizing the build process

        Returns:
            True if the step is applicable to the image, False otherwise
        """
        raise NotImplementedError(f"Class: {cls.__name__}")

    @abstractmethod
    def process(self, builder: SingleBuilder):
        """Process the image, making modifications

        Args:
            builder: The image builder being used
        """
        raise NotImplementedError

    def rollback(self) -> None:
        """Reverse the modifications made by this step."""
        return


@dep
class StartImage(BuildStep):
    """Create the Image object"""

    name = "Starting build"

    @classmethod
    def accepts(cls, builder: SingleBuilder) -> bool:
        return True

    def process(self, builder: SingleBuilder):
        builder.image = Image()


@dep(requires=StartImage)
class ImageMetadata(BuildStep):
    """Copies metadata from an image definition to the final image."""

    name = "Populating basic metadata and information"

    COPY_ATTRS = {"name", "tag", "os", "credentials", "on_install"}

    @classmethod
    def accepts(cls, builder: SingleBuilder) -> bool:
        return True

    def process(self, builder: SingleBuilder):
        assert builder.image is not None
        img, imgdef = builder.image, builder.image_definition

        for prop_name in vars(imgdef.props):
            value = getattr(imgdef.props, prop_name)
            ui.instance().notice(f"Setting image property: {prop_name} = {value}")
            setattr(img.props, prop_name, value)

        for attr in self.COPY_ATTRS:
            # Do not copy non-None, or containers with elements
            if getattr(img, attr, None) is not None:
                try:
                    if len(getattr(img, attr)) > 0:
                        continue
                except (AttributeError, TypeError):
                    continue
            ui.instance().notice(f"Setting image property: {attr}")
            setattr(img, attr, getattr(imgdef, attr))


@dep(requires=StartImage)
class SetupBaseImage(BuildStep):
    """Setup the base image of the machine"""

    name = "Configuring base image"

    @classmethod
    def accepts(cls, builder: SingleBuilder) -> bool:
        return builder.image_definition.base is not None

    def process(self, builder: SingleBuilder):
        assert builder.image_definition.base is not None
        assert builder.image is not None
        search_result = Database().get(builder.image_definition.base)

        if search_result is None:
            raise NotFound(f"Base image: {builder.image_definition.base}")

        if isinstance(search_result, list):
            warnings.warn(f"Found multiple images for {builder.image_definition.base}")
            image = search_result[0]
        else:
            image = search_result
        if isinstance(image, ImageDefinition):
            raise Bug(f"Base image {image} is a definition")

        builder.base_image = image


@dep(requires=SetupBaseImage, before=ImageMetadata)
class InheritMetadata(BuildStep):
    """Inherit metadata from base image"""

    name = "Inheriting metadata from base image"

    COPY_ATTRS = [
        "cloud_init",
        "architecture",
        "contains_os",
        "os",
        "usernames",
        "credentials",
        "cloud_init",
        "requires_install",
        "format",
        "props",
        "delayed_install",
        "type",
        "scripts",
    ]

    @classmethod
    def accepts(cls, builder: SingleBuilder) -> bool:
        return builder.image_definition.base is not None

    def process(self, builder: SingleBuilder):
        assert builder.image is not None
        assert builder.base_image is not None
        no_copy = {"retrieve_from", "usable", "pools", "name", "tag", "filename"}
        attrs = [
            a
            for a in dir(builder.base_image)
            if not a.startswith("_") and a not in no_copy
        ]

        for attr in attrs:
            if getattr(builder.image, attr, None) is not None:
                continue
            try:
                if len(getattr(builder.image, attr)) > 0:
                    continue
            except (AttributeError, TypeError):
                pass
            ui.instance().notice(f"Inheriting {attr} from {builder.base_image}")
            setattr(builder.image, attr, getattr(builder.base_image, attr))


@dep(requires=InheritMetadata)
class BootHelper(BuildStep):
    """Boot the a helper to modify the machine"""

    name = "Creating helper machine"

    @classmethod
    def accepts(cls, builder: SingleBuilder) -> bool:
        if builder.image_definition.base is None:
            return False
        requires_helper = len(builder.image_definition.commands) > 0
        return requires_helper

    def rollback(self) -> None:
        if self.builder.helper is None:
            ui.instance().notice("Helper machine was not present. Not removing")
            return
        import spin.cli

        try:
            success = spin.cli.down(self.builder.helper)
            if success != 0:
                ui.instance().error("Helper machine could not be stopped")
        finally:
            success = spin.cli.destroy(self.builder.helper, remove_disk=True)
            if success != 0:
                ui.instance().error("Helper machine could not be destroyed")

    def process(self, builder: SingleBuilder):
        assert builder.base_image is not None
        import spin.cli
        import spin.plugin.cloud_init

        if not builder.base_image.props.cloud_init:
            raise TODO("Base image requires cloud-init to build")

        with spin.define.vm(builder.base_image) as helper:
            builder.helper = helper
            helper.name = "build-helper-" + secrets.token_hex(4)
            helper.add_disk(Disk(backing_image=builder.base_image))
            helper.plugins = [spin.plugin.cloud_init]

        spin.cli.up(helper)


@dataclasses.dataclass
class _SecondDrive:
    dev_path: str
    root_part: str
    root_uuid: str
    boot_part: str
    boot_uuid: str


def _find_secondary_drive(lsblk: dict) -> _SecondDrive:
    """Return the ``/dev`` path to the main partition of the secondary drive"""
    ui.instance().notice("Attempting to detect second drive")
    possible: list[dict] = []
    for device in lsblk["blockdevices"]:
        devname = device["name"]
        if not devname.startswith("vd"):
            ui.instance().notice(f"Ignoring {devname}: not starting with 'vd'")
            continue
        parts = device["children"]
        if any(part["mountpoint"] == "/" for part in parts):
            ui.instance().notice(f"Ignoring {devname}: mounted as /")
            continue
        possible.append(device)
    possible.sort(key=lambda dev: dev["name"])
    ui.instance().notice(f"Possible drives: {[d['name'] for d in possible]}")
    selected = possible[0]
    if len(possible) > 1:
        ui.instance().warning(f"Assuming {selected['path']} due to lower letter")
    root_part: None | str = None
    boot_part: None | str = None
    root_uuid: None | str = None
    boot_uuid: None | str = None
    for part in selected["children"]:
        if part["fstype"] == "vfat":
            boot_part = part["path"]
            boot_uuid = part["partuuid"]
            continue
        if part["fstype"] == "ext4":
            root_part = part["path"]
            root_uuid = part["partuuid"]
            continue
    if root_part is None or boot_part is None or root_uuid is None or boot_uuid is None:
        raise ValueError("Could not find secondary drive")
    return _SecondDrive(
        dev_path=selected["path"],
        root_part=root_part,
        root_uuid=root_uuid,
        boot_part=boot_part,
        boot_uuid=boot_uuid,
    )


@dataclasses.dataclass
class _PartedDiskInfo:
    number: int
    start: Size
    end: Size
    size: Size
    name: str
    flags: str


def _extract_parted(data: bytes) -> list[_PartedDiskInfo]:
    """Parse ``parted`` command machine output into Python objects"""
    pattern = re.compile(
        r"^(?P<number>\d+):(?P<start>\d+B):(?P<end>\d+B):(?P<size>\d+B):(?P<fs>\w*):(?P<name>.*):(?P<flags>.*);"
    )
    ret: list[_PartedDiskInfo] = []
    partition_lines = data.decode().splitlines()[2:]
    for entry in partition_lines:
        regex = pattern.match(entry)
        if regex is None:
            continue  # HACK: This is a silent failure; notify
        g = regex.groupdict()
        ret.append(
            _PartedDiskInfo(
                number=int(g["number"]),
                start=Size(g["number"]),
                end=Size(g["number"]),
                size=Size(g["number"]),
                name=g["name"],
                flags=g["flags"],
            )
        )

    return ret


@dep(requires=BootHelper, before="PrepareHelper")
class ResizeDisk(BuildStep):
    """Build step to resize the existing machine disk.

    Currently has limited support.
    """

    name = "Resizing root filesystem"

    @classmethod
    def accepts(cls, builder: SingleBuilder) -> bool:
        return (
            BootHelper.accepts(builder)
            and builder.image_definition.experimental.expand_root is not None
        )

    def process(self, builder: SingleBuilder):
        new_size = builder.image_definition.experimental.expand_root
        assert new_size is not None
        assert self.builder.helper is not None

        with open_ssh(self.builder.helper) as sh:
            lsblk = sh.execute("lsblk --json --output-all", check=True)
            new_drive = _find_secondary_drive(json.loads(lsblk.stdout))
            parted = sh.execute(
                f"sudo parted --machine --script {new_drive.dev_path} unit B print",
                check=True,
            )
            sh.execute(f"sudo sgdisk --move-second-header {new_drive.dev_path}")
            parts_info = _extract_parted(parted.stdout)
            match_part_number = re.match(r"/dev/.+(\d+)", new_drive.root_part)
            if match_part_number is None:
                raise ValueError("Could not determine the partition number")
            part_number = int(match_part_number[1])
            (part_info,) = [p for p in parts_info if p.number == part_number]
            if part_info.size.bytes > new_size.bytes:
                raise ValueError(f"Cannot shrink from {part_info.size} to {new_size}")
            # HACK: Check if there is something *after* the partition; we may be writing
            # on another partition
            new_end = part_info.end.bytes + (new_size.bytes - part_info.size.bytes)

            sh.execute(
                f"sudo parted {new_drive.dev_path} unit B resizepart {part_info.number} {new_end}",
                check=True,
            )
            sh.execute(f"sudo e2fsck -y -f {new_drive.root_part}", check=True)
            sh.execute(f"sudo resize2fs {new_drive.root_part}", check=True)


@dep(requires=BootHelper)
class PrepareHelper(BuildStep):
    """Prepare the helper to build the guest.

    This includes mounting the guest, mount-binding special folders.
    """

    name = "Configuring helper machine"

    SCRIPT = """
        mount {root_part} /mnt
        mount -t proc /proc /mnt/proc/
        mount -t sysfs /sys /mnt/sys/
        mount --rbind /dev /mnt/dev/
        mount --rbind /run /mnt/run/
        mount --rbind /tmp /mnt/tmp/
        if [ -f /sys/firmware/efi/efivars ]
        then
            mount --rbind /sys/firmware/efi/efivars /mnt/sys/firmware/efi/efivars/
        fi
        # Mount boot partition
        mount {boot_part} /mnt/boot/efi
    """

    @classmethod
    def accepts(cls, builder: SingleBuilder) -> bool:
        return BootHelper.accepts(builder)

    def process(self, builder: SingleBuilder):
        assert builder.helper is not None
        assert builder.helper.folder is not None
        tmp_file = builder.helper.folder / "build-prepare.sh"
        with open_ssh(builder.helper) as sh:
            lsblk = sh.execute("lsblk --json --output-all")
            if lsblk.returncode != 0:
                raise CommandFailed(lsblk)
            mount_to = _find_secondary_drive(json.loads(lsblk.stdout))
            tmp_file.write_text(
                self.SCRIPT.format(
                    root_part=mount_to.root_part, boot_part=mount_to.boot_part
                )
            )
            ok = sh.copy_to(tmp_file, pathlib.PurePath("/tmp/build-prepare.sh"))
            if ok.returncode != 0:
                raise ValueError
            ret = sh.execute("sudo sh /tmp/build-prepare.sh")
            if ret.returncode != 0:
                raise ValueError


@dep(requires=PrepareHelper)
class RunCommands(BuildStep):
    """Run the commands specified in the machine definition"""

    name = "Running build instructions"

    GUEST_SCRIPT_FOLDER = pathlib.PurePath("/tmp/spin-build-scripts/")

    @classmethod
    def accepts(cls, builder: SingleBuilder) -> bool:
        return BootHelper.accepts(builder)

    def process(self, builder: SingleBuilder):
        assert builder.helper is not None
        assert builder.helper.folder is not None
        files: list[pathlib.PurePath] = []
        folder = builder.helper.folder
        with open_ssh(builder.helper, capture_output=False) as sh:
            sh.execute(f"mkdir {self.GUEST_SCRIPT_FOLDER}")
            for command in builder.image_definition.commands:
                tmp_file = folder / f"build-script-{len(files)}.sh"
                tmp_file.write_text(command)
                files.append(self.GUEST_SCRIPT_FOLDER / tmp_file.name)
                result = sh.copy_to(tmp_file, self.GUEST_SCRIPT_FOLDER)
                if result.returncode != 0:
                    raise ValueError
            for file in files:
                ret = sh.execute(f"sudo chroot /mnt sh < {str(file)}")
                if ret.returncode != 0:
                    raise CommandFailed(ret)


@dep(requires=StartImage, provides="IMAGE_FILE")
class LocalImage(BuildStep):
    """Generate a base image from a local file"""

    name = "Retrieving local image file"

    @classmethod
    def accepts(cls, builder: SingleBuilder) -> bool:
        return builder.image_definition.retrieve_from is not None and not is_remote(
            builder.image_definition.retrieve_from
        )

    def process(self, builder: SingleBuilder):
        assert self.builder.image is not None
        assert builder.image_definition.retrieve_from is not None
        self.builder.image.file = pathlib.Path(builder.image_definition.retrieve_from)


@dep(requires=RunCommands, provides="IMAGE_FILE")
class ExtractNewImage(BuildStep):
    """Extract the new disk-image from the helper"""

    name = "Extracting freshly built image"

    @classmethod
    def accepts(cls, builder: SingleBuilder) -> bool:
        return BootHelper.accepts(builder)

    def process(self, builder: SingleBuilder):
        import spin.cli

        assert builder.helper is not None
        assert builder.image is not None

        with ui.instance().section("Shutting down helper"):
            spin.cli.down(builder.helper)

        secondary_disk = [
            *filter(
                lambda d: isinstance(d, Disk) and d.backing_image == builder.base_image,
                builder.helper.diskarray,
            )
        ]

        if len(secondary_disk) == 0:
            raise Bug(
                (
                    "Could not find secondary disk with new image. "
                    "No disk in helper machine has that backing image"
                )
            )
        if len(secondary_disk) > 1:
            raise Bug(
                (
                    "Could not find secondary disk with new image. "
                    "Multiple secondary disks with that backing image"
                )
            )

        disk = secondary_disk[0]

        if disk.location is None:
            raise Bug("Disk is missing location in local filesystem")
        if disk.uuid is None:
            raise Bug("Disk is missing UUID")

        # We copy-out the file to make sure we can do that
        copy_to = spin.utils.config.conf.database_folder / disk.uuid
        result = shutil.copyfile(disk.location, copy_to)
        builder.image.file = pathlib.Path(result)


@dep(requires=ExtractNewImage)
class DestroyHelper(BuildStep):
    """Destroy the helper machine."""

    name = "Destroying helper machine"

    @classmethod
    def accepts(cls, builder: SingleBuilder) -> bool:
        return BootHelper.accepts(builder)

    def process(self, builder: SingleBuilder):
        import spin.cli

        assert builder.helper is not None

        spin.cli.down(builder.helper)

        try:
            ret = spin.cli.destroy(builder.helper, remove_disk=True)
        except ValueError:
            ui.instance().warning("Helper was still running?")
            return


def is_remote(uri: str) -> bool:
    _KNOWN_REMOTES = (
        p + "://"
        for p in (
            "ftp",
            "sftp",
            "http",
            "https",
        )
    )

    return any(uri.startswith(p) for p in _KNOWN_REMOTES)


@dep(requires=ImageMetadata, provides="IMAGE_FILE")
class RemoteImageStep(BuildStep):
    """Retrieve the base image from the network

    This step class accepts a RemoteFile object, for downloading during image
    creation.
    """

    name = "Pulling remote image"

    @classmethod
    def accepts(cls, builder: SingleBuilder) -> bool:
        return builder.image_definition.retrieve_from is not None and is_remote(
            builder.image_definition.retrieve_from
        )

    def process(self, builder: SingleBuilder):
        imgdef = builder.image_definition

        if builder.image is None:
            raise Bug

        url = imgdef.retrieve_from
        if url is None:
            raise Bug

        try:
            with NetworkTransfer(url, None) as transfer:
                if transfer.redirected():
                    ui.instance().warning(f"Redirected to {transfer.url}")
                with ui.instance().progress(
                    transfer.filename or "Unnamed"
                ) as prog_bar, open(f"/tmp/{transfer.filename}", "wb") as f:
                    transfer.destination = f
                    transfer.download(callback=lambda a, t: prog_bar.update(a / t))

            builder.image.file = pathlib.Path(f"/tmp/{transfer.filename}")
            builder.image.filename = builder.image.file.name
            ui.instance().notice(f"Download complete in {str(transfer.time)}.")
            ui.instance().notice(builder.image.hexdigest())

        except urllib.error.URLError as e:
            ui.instance().error(f"Remote: '{url}' retrieval failed. Hint: {e.reason}")
            raise

        return True, None


@dep(requires={"IMAGE_FILE", ImageMetadata})
class SaveImage(BuildStep):
    """Save the image in the local database to avoid re downloads"""

    name = "Saving image in local database"

    @classmethod
    def accepts(cls, builder: SingleBuilder) -> bool:
        return builder.store_in_db

    def process(self, builder: SingleBuilder):
        db = Database()

        if builder.image is None:
            return True

        if db.get(builder.image.hexdigest()) is not None:
            ui.instance().notice("Image already in database. Updating")
            db.update(builder.image)
            return
        ui.instance().notice("Adding to local database")
        db.add(builder.image)
        return True


def generate_steps(builder: SingleBuilder) -> list[BuildStep]:
    """Given an image definition, generate a sequence of steps to build it"""

    steps = [
        *dependencies.fullgraph(
            cond=lambda n: n.accepts(builder), instance_of=BuildStep  # type: ignore[type-abstract]
        )
    ]

    return [s(builder) for s in steps]


class SingleBuilder:
    """Build a single image, with a resolved base image"""

    def __init__(
        self,
        image: ImageDefinition,
        capture_output=True,
        store_in_db: bool = True,
    ):
        self.image_definition = image
        """The definition of the image being built"""

        self.image: None | Image = None
        """Output image, hopefully generated after running :py:func:`build`"""

        self.capture_output = capture_output

        self.store_in_db = store_in_db
        """If ``True`` the image will be saved in the local database"""

        self.target_architecture = spin.utils.info.host_architecture()

        self.base_image: None | Image = None
        """Image on which the current image being built is based on"""

        self.helper: Machine | None = None
        """Helper virtual machine used to build an image"""

        self.steps: None | list[BuildStep] = None
        self.result: BuildResult

    def prepare(self) -> None:
        """Prepare for the build.

        Raises:
            ValueError: If the step graph generation fails.
        """
        self.steps = generate_steps(self)

    def build(self) -> BuildResult:
        """Build the image defined here

        Returns:
            A pair, where the first element is the build result, and the second
            the resulting image. If the build fails image is None.
        """
        if self.steps is None:
            raise ValueError(
                "Builder not ready: call `prepare()` to generate the build procedure"
            )
        self.result = BuildResult()

        for step in ui.instance().iterate(self.steps, fmt=lambda s: s.name):
            try:
                step.process(self)
            except Exception as exce:
                self.result.exception = exce
                traceback.print_exc()
                ui.instance().error(
                    f"Error during build step {step.__class__.__name__}. Attempting rollback"
                )
                rollback_from = self.steps.index(step)
                for step in self.steps[rollback_from::-1]:
                    step.rollback()

        self.result.success = self.result.exception is None
        self.result.image = self.image if self.result.success else None
        if self.result.image is not None:
            ui.instance().notice(f"Built image {self.result.image}")
            ui.instance().notice(f"sha256:{self.result.image.hexdigest()}")
        return self.result


class Builder:
    """Base class providing default building functionality for images

    A builder takes an image, build steps, and produces an image capable
    of being used by a virtual machine.

    Args:
        image: the image definition to build.
        capture_output: capture the output of the image during build. This
            normally means the primitive serial port of the temporary virtual
            machine used to build the image.
        store_in_db: If ``True``, the image will be saved in the local database.
    """

    target_architecture: str
    """The target architecture, defaults to host"""

    def __init__(
        self, image: ImageDefinition, capture_output=True, store_in_db: bool = True
    ):
        self.image_definition = image
        """The definition of the image being built"""

        self.image: None | Image = None
        """Output image, hopefully generated after running :py:func:`build`"""

        self.images: None | list[ImageDefinition] = None
        """*Ordered* sequence of all the images to build"""

        self.capture_output = capture_output

        self.store_in_db = store_in_db
        """If ``True`` the image will be saved in the local database"""

        self.target_architecture = spin.utils.info.host_architecture()

        self.results: list[BuildResult] = []
        """Results of all images built"""

    def prepare(self) -> None:
        """Prepare for the build.

        Raises:
            ValueError: If the step graph generation fails.
        """

        def trace_base(image: ImageDefinition | Image) -> list[ImageDefinition]:
            if isinstance(image, Image):
                return []
            if image.base is None:
                return [image]
            base: list[Image | ImageDefinition] | Image | ImageDefinition | None
            base = Database().get(image.base)
            if base is None or (isinstance(base, list) and len(base) == 0):
                raise ValueError(f"Unknown base image: {image.base} for {image}")
            if isinstance(base, list):
                base = base[0]

            return [*trace_base(base), image]

        self.images = trace_base(self.image_definition)

    def build(self) -> BuildResult:
        """Build the image defined here

        Returns:
            A pair, where the first element is the build result, and the second
            the resulting image. If the build fails image is None.
        """
        if self.images is None:
            raise ValueError(
                "Builder not ready: call `prepare()` to generate the build procedure"
            )

        for image in ui.instance().iterate(self.images):
            builder = SingleBuilder(
                image, capture_output=self.capture_output, store_in_db=self.store_in_db
            )
            builder.prepare()
            result = builder.build()
            self.results.append(result)
            if not result.success:
                # TODO: Provider a better diagnostic of the error
                ui.instance().error(f"Build for {image} failed")
                break

        return self.results[-1]
