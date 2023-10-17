"""Provides stock machine images
"""

from __future__ import annotations

import datetime
import json
import re
import urllib.request
from typing import Literal

import spin.define
import spin.plugin.api.register
from spin.build.builder import ImageDefinition, RemoteImage
from spin.utils import constants, ui
from spin.utils.constants import OS

UBUNTU_REMOTE = "cloud-images.ubuntu.com/"
UBUNTU_LATEST_JSON = "releases/streams/v1/com.ubuntu.cloud:released:download.json"


class UbuntuGetter:
    def __init__(self, base_url: str, proto: Literal["http", "https"] = "http") -> None:
        self.url = base_url
        self.proto = proto

        if not self.url.endswith("/"):
            self.url += "/"

    def _read_text(self, resource: str) -> dict:
        url = self.proto + "://" + self.url + resource
        with urllib.request.urlopen(url) as remote:
            return json.loads(remote.read().decode())

    def _parse_one_entry(self, data: dict) -> list[ImageDefinition]:
        tag = data["release"]
        arch = data["arch"]
        if arch not in constants.NORMALIZE_ARCHITECTURE_CODE:
            return []
        ret = []
        for datestr in data["versions"]:
            if "disk1.img" not in data["versions"][datestr]["items"]:
                ui.instance().info(
                    f"Ubuntu {data['release_title']} {data['release_codename']} {datestr} has no disk image available."
                )
                continue
            datere = re.compile(r"(\d{8})(\.\d*)?")
            datematch = datere.match(datestr)
            if not datematch:
                raise ValueError(f"Could not parse image date {datestr}")
            date_without_suffix = datematch.group(1)

            date: datetime.date = datetime.datetime.strptime(
                date_without_suffix, "%Y%m%d"
            ).date()
            with spin.define.image("ubuntu", data["release"]) as idef:
                idef.retrieve_from = RemoteImage(
                    self.proto
                    + "://"
                    + self.url
                    + data["versions"][datestr]["items"]["disk1.img"]["path"]
                )
                idef.props.cloud_init = True
                idef.props.requires_install = False
                idef.props.type = "disk-image"
                idef.props.architecture = constants.NORMALIZE_ARCHITECTURE_CODE[arch]
                idef.props.format = "qcow2"
                idef.props.contains_os = True
                idef.props.origin_time = datetime.datetime.combine(
                    date, datetime.datetime.min.time()
                )
                idef.os = OS.Identification("posix", "linux", "ubuntu", tag)
                idef.props.supports_backing = True

            ret.append(idef)
        return ret

    def latest(self) -> list[ImageDefinition]:
        data = self._read_text(UBUNTU_LATEST_JSON)
        images = [self._parse_one_entry(entry) for entry in data["products"].values()]
        return [i for j in images for i in j]


@spin.plugin.api.register.image_provider()
def ubuntu_images() -> list[ImageDefinition]:
    """Generate stock Ubuntu images.

    The images are pulled directly from Ubuntu.
    """
    return UbuntuGetter(UBUNTU_REMOTE).latest()


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
