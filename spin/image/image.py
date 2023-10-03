"""Basic machine image manipulation
"""

from __future__ import annotations

import dataclasses
import hashlib
import pathlib
import shutil
from typing import Dict, Optional, Union

from typing_extensions import Literal, TypeAlias, TypedDict

from spin.build.image_definition import Properties
from spin.machine.action import Action
from spin.machine.credentials import RawUser
from spin.machine.hardware import Disk
from spin.utils.constants import (
    NORMALIZE_ARCHITECTURE_CODE,
    OS,
    SPIN_ARCHITECTURE_CODES_LITERAL,
)

SerialPool: TypeAlias = Dict[str, Dict[str, Disk.Serialized]]


def _sanitize_arch(serial: None | str) -> None | SPIN_ARCHITECTURE_CODES_LITERAL:
    if serial in NORMALIZE_ARCHITECTURE_CODE:
        return NORMALIZE_ARCHITECTURE_CODE[serial]  # type: ignore[index]
    return None


def _sanitize_format(serial: None | str) -> None | Literal["qcow2", "iso"]:
    if serial in ("qcow2", "iso"):
        return serial  # type: ignore
    return None


@dataclasses.dataclass
class ImageReference:
    """Reference to an image."""

    class Serialized(TypedDict):
        sha256: str

    sha256: str

    def dict(self) -> Serialized:
        return {"sha256": self.sha256}


class Image:
    """Represents a machine image

    An image is ready to be used by a guest.

    Args:
        name: The name of the image, for instance the OS or main service
        tag: A tag, indicating the variant or flavour of the image
        path: Path to the image
    """

    class Serialized(TypedDict):
        name: Optional[str]
        tag: Optional[str]
        file: Optional[str]
        supports_backing: Optional[bool]
        cloud_init: Optional[bool]
        ignition: Optional[bool]
        architecture: Optional[str]
        format: Optional[str]
        on_install: list[Action.Serialized]
        sha256: Optional[str]
        type: Optional[Literal["disk-image", "installation-media"]]
        base_image: Optional[Image.Serialized]
        contains_os: Optional[bool]
        os: Optional[OS.Identification]
        credentials: Optional[RawUser.Serialized]
        usernames: list[str]
        pools: SerialPool
        filename: Optional[str]

    def __init__(
        self,
        name: None | str = None,
        tag: None | str = None,
        file: None | str | pathlib.Path = None,
        base_image: None | Image | Image.Serialized = None,
        supports_backing: None | bool = None,
        cloud_init: None | bool = None,
        ignition: None | bool = None,
        architecture: None | str = None,
        sha256: None | str = None,
        format: None | str = None,
        on_install: None | list[Action.Serialized] | list[Action] = None,
        type: None | Literal["disk-image", "installation-media"] = None,
        contains_os: None | bool = None,
        os: None | OS.Identification | list = None,
        requires_install: None | bool = None,
        credentials: None | RawUser | RawUser.Serialized = None,
        pools: None | SerialPool | dict[str, dict[str, Disk]] = None,
        usernames: None | list[str] = None,
        filename: None | str = None,
    ):
        self.name: None | str = name
        """Image name"""
        self.tag: None | str = tag
        """Image tag"""

        self.file: pathlib.Path
        """Path to the image file in the local filesystem.
        """

        if file is not None:
            self.file = pathlib.Path(file)

        self.base_image: None | Image = None
        """Other Image this one relies on.

        A base_image is essentially a backing_image for the disk file. Can be
        chained.
        """
        if isinstance(base_image, dict):
            self.base_image = Image(**base_image)
        else:
            self.base_image = base_image

        self.hashes: dict[str, str] = {}
        """Hashes of the file image. Normally just ``sha256``.
        """
        if sha256 is not None:
            self.hashes["sha256"] = sha256

        self.on_install: list[Action] = []
        """Actions to execute, in order, during installation.
        """

        if on_install is not None:
            for action in on_install:
                if isinstance(action, dict):
                    action = Action.deserialize(action)
                self.on_install.append(action)

        self.os: None | OS.Identification = None
        """Information of the OS contained in the image."""

        if isinstance(os, list):
            os = OS.Identification(*os)
        self.os = os

        self.pools: dict[str, dict[str, Disk]] = {}
        """Pools where this image has been imported.

        The first `key` is the backend, and the second key (or the key
        of the inner dictionary) is the pool.
        """

        if pools is not None:
            for backend in pools:
                self.pools[backend] = {}
                for b_pool, disk in pools[backend].items():
                    if isinstance(disk, dict):
                        disk = Disk(**disk)
                    self.pools[backend][b_pool] = disk

        self.credentials: None | RawUser
        """Login credentials for this image.
        
        Note: the credentials are only valid for the image in it's `pure` state.
        Once a machine is launched, those credentials may change.
        """

        self.filename: Optional[str] = filename
        """Original filename of the image.

        Typically stores the original filename used when the image was uploaded
        to the distribution network/download page.
        """

        self.props = Properties(
            architecture=_sanitize_arch(architecture),
            supports_backing=supports_backing or False,
            contains_os=contains_os,
            usernames=usernames or [],
            cloud_init=cloud_init,
            ignition=ignition,
            requires_install=requires_install,
            format=_sanitize_format(format),
            type=type,
        )
        """Collections of simple properties."""

        if isinstance(credentials, dict):
            self.credentials = RawUser(**credentials)
        else:
            self.credentials = credentials

    def __str__(self) -> str:
        return f"{self.name}:{self.tag}:{self.hexdigest()[:8]}"

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name}, tag={self.tag}, file={self.file})"

    def exists(self) -> bool:
        """Check if the image exists, or is a mock"""
        return self.file is not None and self.file.exists()

    def set_file(self, filepath: Union[str, pathlib.Path]):
        """Add the file path to the image

        Args:
            filepath: The path to the .qcow2, .img, etc of the image

        Raises:
            Exception: if the path provided is not a regular file
        """
        plp = pathlib.Path(filepath)
        if not plp.exists() or not plp.is_file():
            raise Exception("File image is not regular")
        self.file = plp
        self.hashes = dict()

    def hexdigest(self, type: str = "sha256") -> str:
        """Compute the hash of the image

        The hash is cached, to avoid recomputing

        Args:
            name: The algorithm to compute, defaults to sha256

        Returns:
            A string with the hash in hexform (like hexdigest())

        Raises:
            Exception: If the image has no file.
        """
        if type in self.hashes.keys():
            return self.hashes[type]
        h = hashlib.new(type)
        with open(self.file, "rb") as buffer:
            h.update(buffer.read())
        self.hashes[type] = h.hexdigest()
        return h.hexdigest()

    def move(self, destination: Union[str, pathlib.Path]) -> None:
        """Move the image to a new location

        Args:
            destination: The new location of the image.

        Raises:
            Exception: If the image has no file, or the file is not present in
                the defined path.
        """
        if isinstance(destination, str):
            destination = pathlib.Path(destination)
        shutil.move(str(self.file), destination)
        self.file = destination

    @property
    def usable(self) -> bool:
        """Check if the image is in a usable state by a virtual machine

        Returns:
            bool: True if it is usable, false otherwise
        """
        return self.file.is_file()

    def reference(self) -> ImageReference:
        """Return a serializable reference to this image

        Returns: A reference to this image.

        Raises:
            ValueError: If the image has no file associated with it.
        """
        return ImageReference(sha256=self.hexdigest("sha256"))

    def __eq__(self, __value: object) -> bool:
        if not isinstance(__value, self.__class__):
            return False
        return vars(self) == vars(__value)

    def dict(self) -> Serialized:
        """Serialize the image into a json-friendly dictionary"""
        return {
            "name": self.name,
            "tag": self.tag,
            "file": None if not hasattr(self, "file") else str(self.file.absolute()),
            "supports_backing": self.props.supports_backing,
            "cloud_init": self.props.cloud_init,
            "ignition": self.props.ignition,
            "architecture": self.props.architecture,
            "format": self.props.format,
            "on_install": [action.to_dict() for action in self.on_install],
            "sha256": self.hexdigest("sha256") if self.file else None,
            "type": self.props.type,
            "base_image": None if self.base_image is None else self.base_image.dict(),
            "contains_os": self.props.contains_os,
            "os": self.os,
            "usernames": self.props.usernames,
            "credentials": None
            if self.credentials is None
            else self.credentials.dict(),
            "pools": {
                k: {ki: v[ki].dict() for ki in v.keys()} for k, v in self.pools.items()
            },
            "filename": self.filename,
        }
