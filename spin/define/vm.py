"""Starting point for virtual machine definition
"""
from __future__ import annotations

from typing import Optional

from typing_extensions import Literal

from spin.build.image_definition import ImageDefinition
from spin.define.basehelper import BaseDefinitionHelper, ImageIndicator
from spin.image.image import Image
from spin.machine.machine import Machine
from spin.utils import ui


class vm(BaseDefinitionHelper):
    """Start the definition block of a virtual machine"""

    def __init__(
        self,
        image_or_name: Optional[ImageDefinition | Image | str] = None,
        tag: Optional[str] = None,
    ):
        """
        Args:
            image_name: Name of the image to use
            image_tag: Tag of the image to use
        """
        self.image_name = None
        self.image_tag = None
        self.machine_image: None | ImageIndicator = None

        if isinstance(image_or_name, str):
            self.machine_image = (image_or_name, tag)
        else:
            if tag is not None:
                raise ValueError("For non-string image_name, tag must be None")
            self.machine_image = image_or_name

        self.machine: Machine
        """The machine being defined"""

    def __enter__(self) -> Machine:
        self.machine = Machine()
        self.definition_helper.start(self.machine, self.machine_image)
        return self.machine

    def __exit__(self, type, *_) -> Literal[False] | None:
        if type is not None:
            ui.instance().error("Exception during VM definition")
            # We tell python we are not going to handle this
            return False

        self.definition_helper.end(self.machine)
        return None
