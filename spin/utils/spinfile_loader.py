"""``spinfile.py`` load module.
"""

from __future__ import annotations

import importlib.util
import pathlib
from typing import List, Union

from typing_extensions import TypeAlias

import spin.define
import spin.machine.network
from spin import errors
from spin.build.image_definition import ImageDefinition
from spin.define.basehelper import DefinitionLoader, ImageIndicator, find_image
from spin.image.image import Image
from spin.machine.machine import Machine
from spin.machine.processor import MachineProcessor
from spin.utils import ui
from spin.utils.load import SpinfileGroup

LoadableDefinitions: TypeAlias = List[Union[Image, ImageDefinition, Machine]]


class SpinfileLoader(DefinitionLoader):
    """Spinfile loading manager"""

    def __init__(self, file: pathlib.Path, complete_definition: bool) -> None:
        """
        Args:
            file: The python acting as a `spinfile`.

        Raises:
            ValueError: If the file is not present.
        """

        if not file.exists():
            raise errors.NotFound(str(file.absolute()))

        self.file: pathlib.Path = file
        self.group = SpinfileGroup(self.file)
        self.items: LoadableDefinitions = []
        self.complete_definition = complete_definition
        self.call_count = 0
        self.depth = 0

    def load(self) -> None:
        """Load the definitions found in `file`.

        After return; the attribute ``items`` contains all the
        definitions found.

        Raises:
            If something fails during the load.
        """
        spec = importlib.util.spec_from_file_location(self.file.name, self.file)
        if spec is None:
            raise ValueError("Could not locate file in the provided folder")
        mod = importlib.util.module_from_spec(spec)
        if spec.loader is None:
            raise ValueError("Could not load file")
        prev = spin.define.BaseDefinitionHelper.definition_helper
        spin.define.BaseDefinitionHelper.definition_helper = self
        spec.loader.exec_module(mod)
        spin.define.BaseDefinitionHelper.definition_helper = prev

    def _set_network(self, machine: Machine) -> None:
        nic = machine.hardware.network
        if nic is None:
            return
        if nic.network is not None:
            return
        if self.group.network is None:
            self.group.network = spin.machine.network.default()
        nic.network = self.group.network

    def _start_machine(self, machine: Machine, image: None | ImageIndicator) -> None:
        machine.spinfile = self.file
        self._set_network(machine)
        if isinstance(image, tuple):
            if self.complete_definition:
                found_image = find_image(image)
                if found_image is None:
                    raise errors.NotFound(image)
                image = found_image
            else:
                image = None
        if image is not None:
            machine.image = image

    def _start_image(self, image: ImageDefinition) -> None:
        pass

    def _end_machine(self, machine: Machine) -> None:
        if not self.complete_definition:
            return
        mp = MachineProcessor(machine)
        mp.group = self.group
        mp.complete_definition()

    def _end_image(self, image: ImageDefinition) -> None:
        pass

    def start(
        self,
        machine_or_image: Machine | ImageDefinition,
        machine_image: None | ImageIndicator = None,
    ) -> None:
        self.depth += 1
        if self.depth > 1:
            # HACK: Check if this is really necessary
            return
        if isinstance(machine_or_image, Machine):
            self._start_machine(machine_or_image, machine_image)
        if isinstance(machine_or_image, ImageDefinition):
            if machine_image is not None:
                raise ValueError(
                    "Parameter machine_image cannot be used when definning an image"
                )
            self._start_image(machine_or_image)

        self.call_count += 1
        self.items.append(machine_or_image)

    def end(self, machine_or_image: Machine | ImageDefinition) -> None:
        self.depth -= 1
        if self.depth >= 1:
            return
        if isinstance(machine_or_image, Machine):
            self._end_machine(machine_or_image)
        if isinstance(machine_or_image, ImageDefinition):
            self._end_image(machine_or_image)


def spinfile(path: pathlib.Path, disable_definition: bool) -> LoadableDefinitions:
    """Load all the definitions found in the given spinfile.

    The function will load, in order, all the definitions found in
    the file provided in `path`.

    The function performs a `smart` loading. If the file is already in
    use, for instance if the guest machine is already running, that
    machine is returned.

    Returns:
        An ordered list of all the definitions found in the file.

    Raises:
        ValueError: If the file does not point to a spinfile.
        Any exception raised during the processing of the machine definition.
    """

    loader = SpinfileLoader(path, not disable_definition)
    loader.load()
    ui.instance().debug(f"Loaded {len(loader.items)} definition(s)")
    if loader.call_count == 0:
        raise Exception("No definition(s) found")

    return loader.items
