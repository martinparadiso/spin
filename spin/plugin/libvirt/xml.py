"""XML conversion to/from libvirt XML structures"""

from __future__ import annotations

import ipaddress
import pathlib
import secrets
import string
import xml.etree.ElementTree as ET
from typing import Callable, TypeVar

import spin.machine.network
import spin.utils.info
from spin.errors import TODO, BackendError, MissingAttribute
from spin.machine.hardware import CDROM, NIC, Disk, SharedFolder, Storage
from spin.machine.machine import DefinedMachine
from spin.utils import ui

from . import settings

SE = ET.SubElement

_machine_generation: list[Callable[[DefinedMachine, ET.Element], None]] = []

FEATURES = ["acpi"]


def to_str(xml: ET.Element) -> str:
    """Convert an XML object to a unicode encoded string"""
    return ET.tostring(xml, encoding="unicode")


def from_str(xml: str) -> ET.Element:
    """Convert an XML string to a XML object"""
    return ET.fromstring(xml)


def from_machine(machine: DefinedMachine) -> ET.Element:
    """Convert a machine to an *equivalent* libvirt XML domain"""
    xml = ET.Element("domain")
    for gen in _machine_generation:
        gen(machine, xml)
    return xml


def shared_folder(folder: SharedFolder) -> ET.Element:
    """Generate a filesystem passthrough XML element from a shared folder"""
    fs = ET.Element("filesystem", {"type": "mount", "accessmode": "passthrough"})
    SE(fs, "driver", {"type": "path", "wrpolicy": "immediate"})
    SE(fs, "source", {"dir": str(folder.host_path.absolute())})
    SE(fs, "target", {"dir": str(folder.guest_path)})
    return fs


def storage_pool(*, name: str, path: pathlib.Path) -> ET.Element:
    """Generate an storage pool based on the provided parameters.

    Args:
        name: The name of the pool.
        path: The path where the pool is located.
    """
    pool_xml = ET.Element("pool", attrib={"type": "dir"})
    ET.SubElement(pool_xml, "name").text = name
    target = ET.SubElement(pool_xml, "target")
    path_node = ET.SubElement(target, "path")
    path_node.text = str(path.absolute())

    return pool_xml


def volume(
    disk_: Storage, *, image_to_disk: None | Callable[[str], Disk] = None
) -> ET.Element:
    """Convert a disk to a volume XML

    Args:
        disk_: The disk to create the volume from.
        image_to_disk: A callable; mapping the backing image to a disk.
    """

    def insert(parent: ET.Element, sube: str, attrib: dict | None = None):
        if attrib is None:
            attrib = {}
        return ET.SubElement(parent, sube, attrib=attrib)

    assert disk_.uuid is not None
    assert disk_.location is not None
    assert disk_.size is not None
    assert disk_.format is not None

    volume_node = ET.Element("volume")
    target = insert(volume_node, "target")
    perm = insert(target, "permissions")
    size = str(disk_.size.bytes)
    insert(volume_node, "name").text = disk_.uuid
    insert(volume_node, "name").text = disk_.uuid
    insert(volume_node, "allocation").text = "0"
    insert(volume_node, "capacity", {"unit": "B"}).text = size
    insert(target, "format", {"type": disk_.format})
    insert(perm, "owner").text = "1000"
    insert(perm, "group").text = "1000"
    insert(perm, "mode").text = "0700"
    insert(perm, "label").text = "virt_image_t"

    if isinstance(disk_, Disk) and disk_.backing_image is not None:
        if image_to_disk is None:
            raise ValueError("Missing image to disk mapping function")
        as_disk = image_to_disk(disk_.backing_image.hexdigest())
        if as_disk.location is None:
            raise BackendError(f"{as_disk} created from image has no file")
        if as_disk.format is None:
            raise BackendError(f"{as_disk} created from image has unknown format")

        back = insert(volume_node, "backingStore")
        insert(back, "path").text = str(as_disk.location.absolute())
        insert(back, "format", {"type": as_disk.format})

    return volume_node


def to_network(netxml: str) -> spin.machine.network.LAN:
    """Convert a network XML into a LAN object"""
    xml = ET.fromstring(netxml)
    name = xml.findtext("name")
    if name is None:
        raise ValueError("Network missing name. This should not happen")

    forward = xml.find("forward")
    nat = forward is not None and forward.attrib["mode"] == "nat"

    ipv4: None | spin.machine.network.IPv4Network = None
    ipv4_nodes = xml.findall("ip")
    ipv4_nodes = [*filter(lambda n: n.attrib.get("ip", None) != "ipv6", ipv4_nodes)]
    if len(ipv4_nodes) >= 1:
        first_net = ipv4_nodes[0]
        if len(ipv4_nodes) > 1:
            ui.instance().warning(
                "More than one address found for IPv4. Currently not supported"
            )
        dhcp: None | tuple[ipaddress.IPv4Address, ipaddress.IPv4Address] = None

        dhcp_xml = first_net.find("dhcp")
        if dhcp_xml is not None:
            range_ = dhcp_xml.find("range")
            if range_ is not None:
                start = ipaddress.IPv4Address(range_.attrib["start"])
                end = ipaddress.IPv4Address(range_.attrib["end"])
                dhcp = (start, end)

        ipv4 = spin.machine.network.IPv4Network(
            network=ipaddress.IPv4Network(
                first_net.attrib["address"] + "/" + first_net.attrib["netmask"],
                strict=False,
            ),
            gateway=first_net.attrib["address"],
            dhcp=dhcp,
        )

    ipv6: None | spin.machine.network.IPv6Network = None
    ipv6_nodes = xml.findall("ip[@family='ipv6']")
    if len(ipv6_nodes) >= 1:
        first_net = ipv6_nodes[0]
        if len(ipv6_nodes) > 1:
            ui.instance().warning(
                "More than one address found for IPv6. Currently not supported"
            )
        dhcp_: None | tuple[ipaddress.IPv6Address, ipaddress.IPv6Address] = None

        dhcp_xml = first_net.find("dhcp")
        if dhcp_xml is not None:
            range_ = dhcp_xml.find("range")
            if range_ is not None:
                start_ = ipaddress.IPv6Address(range_.attrib["start"])
                end_ = ipaddress.IPv6Address(range_.attrib["end"])
                dhcp_ = (start_, end_)

        ipv6 = spin.machine.network.IPv6Network(
            network=ipaddress.IPv6Network(
                first_net.attrib["address"] + "/" + first_net.attrib["prefix"],
                strict=False,
            ),
            gateway=ipaddress.IPv6Address(first_net.attrib["address"]),
            dhcp=dhcp_,
        )
    return spin.machine.network.LAN(uuid=name, nat=nat, ipv4=ipv4, ipv6=ipv6)


def from_network(net: spin.machine.network.LAN) -> ET.Element:
    """Generate a network XML from a network object"""
    if net.name is None:
        raise ValueError("Missing network name")

    if net.ipv4 == "auto":
        raise ValueError("Network IPv4 cannot be auto")

    if net.ipv6 == "auto":
        raise ValueError("Network IPv6 cannot be auto")

    xml = ET.Element("network")
    SE(xml, "name").text = net.name
    SE(
        xml,
        "bridge",
        name=settings.get().network_bridge_name + secrets.token_hex(4),
    )

    if net.nat:
        SE(xml, "forward", mode="nat")

    if net.ipv4:
        assert net.ipv4 != "auto"
        ip = SE(
            xml,
            "ip",
            address=str(net.ipv4.gateway),
            netmask=str(net.ipv4.network.netmask),
        )
        if net.ipv4.dhcp:
            dhcp = SE(ip, "dhcp")
            SE(
                dhcp,
                "range",
                start=str(net.ipv4.dhcp[0]),
                end=str(net.ipv4.dhcp[1]),
            )

    if net.ipv6:
        assert net.ipv6 != "auto"
        ip = SE(
            xml,
            "ip",
            family="ipv6",
            address=str(net.ipv6.gateway),
            prefix=str(net.ipv6.network.prefixlen),
        )
        if net.ipv6.dhcp:
            dhcp = SE(ip, "dhcp")
            SE(
                dhcp,
                "range",
                start=str(net.ipv6.dhcp[0]),
                end=str(net.ipv6.dhcp[1]),
            )
    return xml


def disk(disk_: Storage, index: int, boot_order: None | int = None) -> ET.Element:
    """Generate a volume XML from the given disk and data"""
    if isinstance(disk_, Disk):
        if disk_.location is None or disk_.format is None:
            missing = [e for e in ("location", "format") if getattr(disk_, e) is None]
            raise MissingAttribute(disk_, *missing)
        xml = ET.Element("disk", {"type": "file", "device": "disk"})
        SE(xml, "source", {"file": str(disk_.location.absolute())})
        SE(xml, "target", {"dev": "vd" + string.ascii_lowercase[index]})
        SE(xml, "driver", {"name": "qemu", "type": disk_.format})
        if boot_order is not None:
            SE(xml, "boot", {"order": str(boot_order + 1)})
    elif isinstance(disk_, CDROM):
        xml = ET.Element("disk", {"type": "file", "device": "cdrom"})
        if disk_.location is None:
            raise ValueError(f"CDROM {disk_} has no location")
        SE(xml, "source", {"file": str(disk_.location.absolute())})
        SE(
            xml,
            "target",
            {
                "dev": "sd" + string.ascii_lowercase[index],
                "bus": "sata",
                "tray": "open",
            },
        )
        SE(xml, "readonly")
        if boot_order is not None:
            SE(xml, "boot", {"order": str(boot_order + 1)})
    else:
        raise ValueError(f"Unknown storage type: {type(disk_)}")

    return xml


def nic(interface: NIC) -> ET.Element:
    """Generate a interface device XML from the given NIC"""
    if interface.network is None:
        raise ValueError("Missing network in NIC")

    if isinstance(interface.network, str):
        raise ValueError("Network not loaded")

    if interface.network.name is None:
        raise ValueError("Network is missing name")

    if interface.mode == "NAT":
        iface = ET.Element("interface", {"type": "network"})
        SE(iface, "source", {"network": interface.network.name})
        SE(iface, "model", {"type": "virtio"})
        return iface

    if interface.mode == "user":
        iface = ET.Element("interface", {"type": "user"})
        SE(iface, "model", {"type": "virtio"})
        return iface

    raise ValueError(f"Unsupported interface mode: {interface.mode}")


F = TypeVar("F", bound=Callable[[DefinedMachine, ET.Element], None])


def _for_machine(f: F) -> F:
    _machine_generation.append(f)
    return f


@_for_machine
def _machine_base(_: DefinedMachine, xml: ET.Element):
    xml.tag = "domain"
    xml.extend(ET.Element(s) for s in ("devices", "features"))


@_for_machine
def _machine_info(machine: DefinedMachine, xml: ET.Element):
    ET.SubElement(xml, "name").text = machine.name
    ET.SubElement(xml, "uuid").text = machine.uuid
    if machine.title is not None:
        ET.SubElement(xml, "title").text = machine.title
    if machine.description is not None:
        ET.SubElement(xml, "description").text = machine.description

    metadata = ET.SubElement(xml, "metadata")
    for k, v in machine.metadata.items():
        raise TODO


@_for_machine
def _machine_virt_mode(machine: DefinedMachine, xml: ET.Element):
    if machine.hardware_virtualization == "no":
        xml.attrib["type"] = "qemu"
    else:
        xml.attrib["type"] = "kvm"
    os = SE(xml, "os")
    if machine.image is None:
        arch = spin.utils.info.host_architecture()
    else:
        arch = machine.image.props.architecture or spin.utils.info.host_architecture()

    if spin.utils.info.host_architecture() == arch:
        cpu_mode = settings.get().cpu_mode
    else:
        cpu_mode = "maximum"

    SE(xml, "cpu", {"mode": cpu_mode})
    os_type = SE(os, "type", {"arch": arch})
    os_type.text = "hvm"
    # "hvm" means full virtualization; the guest is designed to run on
    # bare-metal so libvirt/qemu performs a full virtualization.


@_for_machine
def _machine_features(machine: DefinedMachine, xml: ET.Element):
    featxml = xml.find("features")
    if featxml is None:
        raise ValueError("Missing features tag. Please report this as a bug.")
    for feat in FEATURES:
        SE(featxml, feat)


@_for_machine
def _machine_hardware(machine: DefinedMachine, xml: ET.Element):
    SE(xml, "memory", {"unit": "bytes"}).text = str(machine.hardware.memory.bytes)
    SE(xml, "vcpu", {"current": str(machine.hardware.cpus)}).text = str(
        machine.hardware.cpus
    )

    clock_offset = "utc"
    if (
        machine.image is not None
        and machine.image.os is not None
        and machine.image.os.family == "windows"
    ):
        clock_offset = "localtime"
    SE(xml, "clock", {"offset": clock_offset})


@_for_machine
def _machine_devices(machine: DefinedMachine, xml: ET.Element):
    devices = xml.find("devices")
    if devices is None:
        raise ValueError("Missing devices tag. Please report this as a bug")
    console = SE(devices, "console", {"type": "pty"})
    SE(console, "target", {"type": "serial", "port": "0"})

    video = SE(devices, "video")
    SE(video, "model", {"type": "qxl"})

    channel = SE(devices, "graphics", {"type": "spice"})
    # Per https://www.spice-space.org/spice-user-manual.html#agent
    channel = SE(devices, "channel", {"type": "spicevmc"})
    SE(channel, "target", {"type": "virtio", "name": "com.redhat.spice.0"})
    SE(devices, "controller", {"type": "virtio-serial", "index": "0"})


@_for_machine
def _machine_storage(machine: DefinedMachine, xml: ET.Element):
    disks = 1
    cdroms = 0

    disk_ = machine.hardware.disk
    devs = xml.find("devices")
    if devs is None:
        raise ValueError("Missing devices tag. Please report this as a bug.")

    if disk_ is not None:
        if disk_.location is None or disk_.format is None:
            missing = [e for e in ("location", "format") if getattr(disk_, e) is None]
            raise MissingAttribute(disk_, *missing)
        diskxml = SE(devs, "disk", {"type": "file", "device": "disk"})
        SE(diskxml, "source", {"file": str(disk_.location.absolute())})
        SE(diskxml, "target", {"dev": "vda"})
        SE(diskxml, "driver", {"name": "qemu", "type": disk_.format})

    for disk_ in [disk_ for disk_ in machine.diskarray if isinstance(disk_, Disk)]:
        if disk in machine.boot_order:
            devs.append(disk(disk_, disks, machine.boot_order.index(disk_)))
        else:
            devs.append(disk(disk_, disks))
        disks += 1

    for cdrom_ in [cdrom for cdrom in machine.diskarray if isinstance(cdrom, CDROM)]:
        if cdrom_ in machine.boot_order:
            devs.append(disk(cdrom_, cdroms, machine.boot_order.index(cdrom_)))
        else:
            devs.append(disk(cdrom_, cdroms))
        cdroms += 1


@_for_machine
def _machine_network(machine: DefinedMachine, xml: ET.Element):
    net = machine.hardware.network

    if net is None:
        return

    devs = xml.find("devices")
    if devs is None:
        raise ValueError("Missing devices tag. Please report this as a bug.")

    devs.append(nic(net))


@_for_machine
def _machine_sharedfolders(machine: DefinedMachine, xml: ET.Element):
    devs = xml.find("devices")
    if devs is None:
        raise ValueError("Missing devices tag. Please report this as a bug.")

    devs.extend(shared_folder(folder) for folder in machine.shared_folders)
