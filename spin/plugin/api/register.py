"""Main entrypoint for the plugin API"""

from __future__ import annotations

from typing import Any, Callable, Collection, List, Optional, Type, TypeVar, overload

from pydantic import BaseModel

import spin.utils.config
from spin.backend.base import Backend
from spin.build.image_definition import ImageDefinition
from spin.machine.hardware import Disk
from spin.machine.machine import Machine
from spin.machine.steps import BaseTask, CommonStep, CreationStep, ProcessableStep
from spin.utils import dependency
from spin.utils.dependency import Dependencies, dep

IMAGE_PROVIDER_SIGNATURE = Callable[[], List[ImageDefinition]]
DISK_CREATOR_SIGNATURE = Callable[[Disk], None]
S = TypeVar("S", bound=ProcessableStep)
B = TypeVar("B", bound=Backend)


def wrap_step(s: Type[S]) -> Type[S]:
    """Generate a *new* class; 'wrapping' the given step.

    Args:
        A plugin step.

    Returns:
        A step, wrapping the step which performs boiler plate operations.
    """

    s.__original_accepts__ = s.accepts

    def wrap_accept(machine: Machine) -> bool:
        if s.__module__ not in [p.__name__ for p in machine.plugins]:
            return False
        return s.__original_accepts__(machine)

    s.accepts = wrap_accept

    return s


class PluginRegister:
    """Class in charge of registering plugins.

    This class wraps the plugin register API. All plugins must register with
    this class ---through the :py:obj:`register` global variable--- in order
    to be available to the user.
    """

    IMAGE_PROVIDER_SIGNATURE = Callable[[], List[ImageDefinition]]
    DISK_CREATOR_SIGNATURE = Callable[[Disk], None]

    def __init__(self) -> None:
        self.check_signatures: bool = False
        """Validate the registered classes.

        Check the registered classes for the required functions. If the class
        is missing a required function, an exception is raised.
        """

        self.plugins: list = []
        """List of all the registered plugins"""

        self.image_providers: list[PluginRegister.IMAGE_PROVIDER_SIGNATURE] = []
        """Collection of functions --or callables-- providing image definitions"""

        self.disk_creators: dict[str, list[PluginRegister.DISK_CREATOR_SIGNATURE]] = {}
        """Collection of functions capable of creating disks"""

        self.backends: set[Type[Backend]] = set()
        """Collection of all available backends"""

    def _register_plugin(self, val: Any) -> None:
        """Register a module --python file-- as a plugin"""
        qa = val.__module__ + "." + val.__qualname__
        if qa not in self.plugins:
            self.plugins.append(qa)

    def image_provider(self):
        """Register a class as an image provider.

        The class will be instantiated one or more times during the program
        lifetime. The decorated class **must** provide an ``images()`` method,
        which returns a list of :py:class:`ImageDefinition`.

        Examples:

            To register a class::

                import spin.plugin.api
                from spin.image import Image

                @spin.plugin.api.register.image_provider()
                class SomeImageProvider:

                    def images(self) -> List[ImageDefinition]:
                        ...
        """

        def wrap(f: Callable[[], list[ImageDefinition]]):
            self._register_plugin(f)
            self.image_providers.append(f)
            return f

        return wrap

    def disk_creator(self, fmt: set[str]):
        """Register a function as a disk creator.

        Args:
            fmt: A string containing the formats the disk is capable of create
        """

        def wrap(f: DISK_CREATOR_SIGNATURE):
            self._register_plugin(f)
            for format_ in fmt:
                if format_ not in self.disk_creators:
                    self.disk_creators[format_] = []
                self.disk_creators[format_].append(f)
            return f

        return wrap

    @overload
    def definition_step(self, cls: Type[S]) -> Type[S]:
        ...

    @overload
    def definition_step(
        self,
        cls=None,
        *,
        requires: Dependencies = None,
        provides: Dependencies = None,
        before: Dependencies = None,
    ) -> Callable[[Type[S]], Type[S]]:
        ...

    def definition_step(
        self,
        cls: Optional[Type[S]] = None,
        *,
        requires: Dependencies = None,
        provides: Dependencies = None,
        before: Dependencies = None,
    ) -> Type[S] | Callable[[Type[S]], Type[S]]:
        """Register a new definition step.

        The *step* class will be wrapped around another class which
        performs certain checks and validations.

        In particular, the `accept` method put behind another
        check verifies if the plugin has been listed in
        the machine definition (see
        :py:attr:`spin.machine.machine.Machine.plugins`)::

            def wrap_accept(plugin_class, machine):
                if plugin_class not in machine.plugins:
                    return False
                return plugin_class.accept(machine)
        """

        def _inner(inner_cls: Type[S]) -> Type[S]:
            dep(requires=requires, provides=provides, before=before)(
                wrap_step(inner_cls)
            )
            return inner_cls

        if cls is None:
            return _inner
        return _inner(cls)

    def backend(self, back: Type[B]) -> Type[B]:
        """Register a new backend"""
        self.backends.add(back)
        return back

    def settings(self, key: str) -> Callable[[Type[BaseModel]], Type[BaseModel]]:
        """Register a new setting class.

        The library uses pydantic `BaseModel` for setting management; the
        decorated class must be a subclass of `BaseModel`.

        Args:
            key: The key to store the settings under. It will be accessible
                under ``spin.utils.config.conf.settings.plugins.key``
        """

        def inner(setting: Type[BaseModel]) -> Type[BaseModel]:
            if hasattr(spin.utils.config.PluginsSettings, key):
                raise KeyError(f"Plugin key `{key}` already present")
            setattr(spin.utils.config.PluginsSettings, key, setting())
            return setting

        return inner


global_register: PluginRegister = PluginRegister()
"""Singleton object for plugin registration.

To mark a class as a *plugin*, it must be marked with the following decorator,
indicating which functionality it provides::

    import spin.plugin.api

    @spin.plugin.api.register.image_provider()
    class MyPlugin: ...

More than one decorator can be used, for classes providing multiple
functionality.

The class :py:class:`PluginRegister` contains all the possible functionality
a plugin can provide.
"""

definition_step = global_register.definition_step
backend = global_register.backend
image_provider = global_register.image_provider
disk_creator = global_register.disk_creator
plugins = global_register.plugins
image_providers = global_register.image_providers
disk_creators = global_register.disk_creators
backends = global_register.backends
settings = global_register.settings


solves = dependency.solves


def creation_step(
    requires: None | Collection[Type[BaseTask] | Type[CreationStep]] = None,
    after: None | Collection[Type[BaseTask] | Type[CreationStep]] = None,
    before: None | Collection[Type[BaseTask] | Type[CreationStep]] = None,
):
    requires = requires or []
    after = after or []
    before = before or []
    _T = TypeVar("_T", bound=CreationStep)

    def _register_inner(step: Type[_T]) -> Type[_T]:
        """Register a creation step"""
        return dependency.register(requires=requires, after=after, before=before)(step)

    return _register_inner
