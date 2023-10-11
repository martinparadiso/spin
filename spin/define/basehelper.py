"""Base/common class for definitions"""

from __future__ import annotations

from typing import Optional, Tuple, Union

from typing_extensions import Protocol, TypeAlias

from spin.build.image_definition import ImageDefinition
from spin.image.database import Database
from spin.image.image import Image
from spin.machine.machine import Machine
from spin.machine.processor import MachineProcessor
from spin.utils import ui

ImageIndicator: TypeAlias = Union[Image, ImageDefinition, Tuple[str, Optional[str]]]


class DefinitionLoader(Protocol):
    """Manages the loading of definitions found in a `spinfile`"""

    def start(
        self,
        machine_or_image: Machine | ImageDefinition,
        machine_image: None | ImageIndicator = None,
    ) -> None:
        """Indicate the start of a machine or image definition

        Args:
            machine_or_image: The machine or image being defined.
        """
        ...

    def end(self, machine_or_image: Machine | ImageDefinition) -> None:
        """Indicate the end of a machine or image definition"""
        ...


def find_image(image: tuple[str, None | str]) -> Image | ImageDefinition | None:
    """Search for *image* in the local database.

    Args:
        image: A tuple containing name, tag of the image

    Returns:
        A ready to use Image, an ImageDefinition, or None if nothing was
        found.
    """
    db = Database()
    name, tag = image
    images = db.get((name, tag))
    if len(images) == 0:
        return None
    if len(images) > 1:
        ui.instance().warning(f"Found more than one valid image. Using {images[0]}")
    return images[0]


class DefaultLoader(DefinitionLoader):
    """Default loader that does nothing"""

    def start(
        self,
        machine_or_image: Machine | ImageDefinition,
        machine_image: None | ImageIndicator = None,
    ) -> None:
        if isinstance(machine_or_image, ImageDefinition):
            return
        if isinstance(machine_image, tuple):
            machine_image = find_image(machine_image)
        machine_or_image.image = machine_image

    def end(self, machine_or_image: Machine | ImageDefinition) -> None:
        if isinstance(machine_or_image, Machine):
            mp = MachineProcessor(machine_or_image)
            mp.complete_definition()


class BaseDefinitionHelper:
    definition_helper: DefinitionLoader = DefaultLoader()
    """Container storing all found definitions"""
