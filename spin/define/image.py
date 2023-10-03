"""Starting point for image definition
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from typing_extensions import Literal

from spin.define.basehelper import BaseDefinitionHelper

if TYPE_CHECKING:
    from spin.machine.connection import UserInputSimulator

from spin.build.builder import ImageDefinition


class ManualInstall:
    """Helper function to define the install procedure for an image.

    Some images require manual intervation, this class aids in the definition
    of the installation process.

    Args:
        image: The image currently being defined

    Examples:
        The class is designed to be used as::

            with spin.define.image('some', 'image') as img:
                with ManualInstall(img) as mi:
                    install.runs = 'on_creation'
                    mi.login = ('root', 'password')
                    install.connection = 'serial'
                    with install.simulate_input() as si:
                        si.type('root')
                        si.type('useradd ubuntu')
    TODO:
        - Extend the documentation
    """

    runs: Literal["on_definition", "on_creation"]
    """Indicates when the installation should be performed

    If the installation produces a generic image, capable of being used by
    other images or machines, the value should be 'on_definition'. If the
    generated output contains unique data, such as MACs, UUIDs, keys, or
    anything similar, the installation should be performed ``on_creation``
    (of the final machine).
    """

    connection: Literal["ssh", "serial"]
    """Type of connection to use when sending commands for the setup."""

    def __init__(self, image: ImageDefinition):
        self.image = image
        self.uis: None | UserInputSimulator = None

        self.has_autologin: None | bool = None
        """If set to ``True``, the image logins automatically.

        If set to ``False`` the terminal/console port must be activated, and logged in
        manually, like a normal OS.

        Most installation images login automatically.
        """

    def __enter__(self) -> "ManualInstall":
        return self

    def __exit__(self, type, *_):
        if type is not None:
            return False

        img = self.image
        img.props.requires_install = (
            img.props.requires_install or getattr(self, "shell", None) is not None
        )
        img.props.requires_install = self.runs == "on_creation"

        if self.uis is not None:
            img.on_install.extend(self.uis.sequence)

    def simulate_input(self) -> "UserInputSimulator":
        """Simulate user input

        See :py:class:`UserInputSimulator` for the capabilities of said object

        Returns:
            An 'UserInputSimulator' object, which will store the instructions
            to send to the machine during installation.
        """
        from spin.machine.connection import UserInputSimulator

        self.uis = UserInputSimulator()
        self.image.props.requires_install = True
        return self.uis


class ImageHelper(BaseDefinitionHelper):
    """Helps defining a new image"""

    def __init__(self, name: None | str, tag: None | str) -> None:
        """

        Args:
            name: Name of the image
            tag: Tag of the image
        """
        self.name = name
        self.tag = tag
        self.image_definition: None | ImageDefinition = None

    def __enter__(self) -> ImageDefinition:
        self.image_definition = ImageDefinition()
        self.image_definition.name = self.name
        self.image_definition.tag = self.tag
        self.definition_helper.start(self.image_definition)
        return self.image_definition

    def __exit__(self, type, *_):
        if type is not None:
            return False
        if self.image_definition is None:
            raise ValueError("Missing image definition")
        self.definition_helper.end(self.image_definition)
