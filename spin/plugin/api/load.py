"""Contains register of loaded plugins"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import Sequence

BUILTIN_PLUGINS = [
    "spin.plugin.images",
    "spin.plugin.libvirt",
    "spin.plugin.qcow",
]

modules: list[ModuleType] = []
"""List of loaded plugins"""


def load_plugin(plugin: str) -> None:
    """Load a plugin. The plugin will be stored in the `plugins` list.

    Args:
        plugin: The plugin to load.
    """
    modules.append(importlib.import_module(plugin))


def load_plugins(
    extra: None | Sequence[str] = None, skip_builtin: bool = False
) -> None:
    """Load plugins.

    Extra plugins will be loaded after built-in plugins.

    Args:
        extra: Extra plugins to load, as ``str``.
        skip_builtin: If set to ``True``, builtin plugins (`BUILTIN_PLUGINS`)
            will not be loaded.
    """
    if not skip_builtin:
        for plugin in BUILTIN_PLUGINS:
            load_plugin(plugin)

    extra = extra or []
    for plugin in extra:
        load_plugin(plugin)
