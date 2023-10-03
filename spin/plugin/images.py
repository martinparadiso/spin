"""Provides stock machine images
"""

from __future__ import annotations

import spin.define
import spin.plugin.api.register
from spin.build.builder import ImageDefinition, RemoteImage
from spin.utils import constants
from spin.utils.constants import OS


@spin.plugin.api.register.image_provider()
def ubuntu_images() -> list[ImageDefinition]:
    """Generate stock Ubuntu images.

    The images are pulled directly from Ubuntu.
    """
    from itertools import product

    tags = ("bionic", "focal", "jammy")
    archs: tuple[constants.ARCHITECTURE_CODES_LITERAL] = ("amd64",)
    ret = []
    for tag, arch in product(tags, archs):
        with spin.define.image("ubuntu", tag) as idef:
            idef.retrieve_from = RemoteImage(
                f"http://cloud-images.ubuntu.com/{tag}/current/{tag}-server-cloudimg-{arch}.img"
            )
            idef.props.cloud_init = True
            idef.props.requires_install = False
            idef.props.type = "disk-image"
            idef.props.architecture = constants.NORMALIZE_ARCHITECTURE_CODE[arch]
            idef.props.format = "qcow2"
            idef.props.contains_os = True
            idef.os = OS.Identification("posix", "linux", "ubuntu", tag)
            idef.props.supports_backing = True

        ret.append(idef)
    return ret


@spin.plugin.api.register.image_provider()
def opensuse() -> list[ImageDefinition]:
    """Generate stock MicroOS images for QEMU KVM

    The images are pulled directly from OpenSUSE.
    """

    def set_common(img: ImageDefinition, variant: str):
        microos.props.cloud_init = False
        microos.props.contains_os = True
        microos.props.type = "disk-image"
        microos.props.format = "qcow2"
        microos.os = OS.Identification("posix", "linux", "opensuse", variant)
        microos.props.requires_install = False
        microos.props.supports_backing = False

    with spin.define.image("opensuse", "microos") as microos:
        microos.retrieve_from = RemoteImage(
            "http://download.opensuse.org/tumbleweed/appliances/openSUSE-MicroOS.x86_64-kvm-and-xen.qcow2"
        )
        set_common(microos, "microos")

    return [microos]
