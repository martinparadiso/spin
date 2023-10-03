"""libvirt settings"""
from __future__ import annotations

import spin.plugin.api.register
import spin.utils.config


@spin.plugin.api.register.settings("libvirt")
class LibvirtConfig(spin.utils.config.BackendCommonSettings):
    """Configuration for the libvirt plugin/backend"""

    uri: str = "qemu:///system"
    pool: str = "default"
    cpu_mode: str = "host-passthrough"
    network_bridge_name: str = "virbr"


def get() -> LibvirtConfig:
    """Retrieve the settings object.

    Returns: A settings object, already processed by the library. If
        the object is not found,
    """

    return getattr(spin.utils.config.conf.settings.plugins, "libvirt", LibvirtConfig())
