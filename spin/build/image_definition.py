"""Module containing ImageDefinition"""
from __future__ import annotations
import dataclasses
import datetime

import pathlib
import string

from typing_extensions import Literal
from spin.machine.action import Action
from spin.machine.credentials import RawLogin
from spin.utils import constants

from spin.utils.constants import OS
from spin.utils.sizes import Size


class ImageDigest(str):
    """Specialization of str that only accepts valid sha256 checksums"""

    HASH_LENGTH = 64
    VALID_CHARS = string.hexdigits

    def __init__(self, value: str | None = None) -> None:
        """
        Raises:
            ValueError: If value is not a valid hash
        """
        super().__init__()
        if value is None:
            return
        if len(value) != self.HASH_LENGTH:
            raise ValueError
        if not all((c in self.VALID_CHARS) for c in value):
            raise ValueError


class BuildTools:
    """Collection of utilities for defining the build procedure of an image"""

    def __init__(self) -> None:
        self.base: tuple[str, str] | ImageDigest | None = None
        self.commands: list[str] = []

    def run(self, command: str) -> None:
        """Execute `command` on the machine"""
        self.commands.append(command)


@dataclasses.dataclass
class ExperimentalFeatures:
    """Collection of features not fully tested, requiring explicit activation."""

    expand_root: None | Size = None


@dataclasses.dataclass
class Properties:
    """Simple data/properties for images"""

    architecture: None | constants.SPIN_ARCHITECTURE_CODES_LITERAL = None
    """The CPU architecture supported by the image."""

    supports_backing: bool = False
    """`True` if the image supports backing; defaults to `False` for safety."""

    contains_os: None | bool = None
    """`True` if the disk contains an operating system."""

    usernames: list[str] = dataclasses.field(default_factory=list)
    """Collection of *possible* default usernames for this image."""

    cloud_init: None | bool = None
    """`True` if the image supports cloud-init."""

    ignition: None | bool = None
    """`True` if the image supports cloud-init."""

    requires_install: None | bool = None
    """`True` if the image requires an installation procedure.

    If `False` the image is ready to be used by a machine.
    """

    format: None | Literal["qcow2", "iso"] = None
    """Format of the disk."""

    type: None | Literal["disk-image", "installation-media"] = None
    """Type of the retrieved file: machine disk or .iso install media."""

    origin_time: None | datetime.datetime = None
    """Build reported by the original author"""


class ImageDefinition(BuildTools):
    """Build instructions for an image.

    When passed to a :py:class:`Builder` class, it produces a
    :py:class:`Image`.
    """

    def __init__(self) -> None:
        super().__init__()
        self.name: None | str = None
        """Name of the output Image"""

        self.tag: None | str = None
        """Tag of the output Image"""

        self.props = Properties()
        """Collections of simple properties."""

        self.os: None | OS.Identification = None
        """OS identification, same as :py:attr:`Image.os`"""

        self.credentials: None | RawLogin = None
        """Defaults credentials of this image.

        Cloud-ready images normally have no credentials; while .iso install images
        normally default to ``root:None``.
        """

        self.retrieve_from: None | str = None
        """URL to retrieve the image from. If no protocol is specified, it is
        assumed as a local file."""

        self.on_install: list[Action] = []
        """Actions to execute, in order, during installation.
        """

        self.usable: Literal[False] = False
        """Same behaviour as :py:attr:`Image.usable`.
        
        Since this is an image *definition* it always returns False.
        """

        self.experimental = ExperimentalFeatures()

    def __repr__(self) -> str:
        return f"ImageDefinition(name={self.name},tag={self.tag})"
