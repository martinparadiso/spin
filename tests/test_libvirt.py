"""Test libvirt backend
"""

from __future__ import annotations

import ipaddress
from unittest.mock import MagicMock, Mock, call, patch
from uuid import uuid4
from xml.etree import ElementTree as ET

import pytest

from spin.machine.hardware import CDROM, Disk
from spin.machine.machine import Machine
from spin.plugin.libvirt.steps import DestroyNetwork

libvirt = pytest.importorskip("libvirt", reason="Could not load libvirt module")

import spin.plugin.libvirt
import spin.plugin.libvirt.checks
import spin.plugin.libvirt.xml
from spin.machine.network import LAN
from spin.plugin.libvirt.core import LibvirtBackend
from spin.utils.config import conf


@pytest.mark.requires_backend
def test_default_backend() -> None:
    """Check the backend for a new machine is libvirt"""

    assert LibvirtBackend == conf.default_backend()


class TestUtils:
    @patch("spin.plugin.libvirt.checks.subprocess.run", autospec=True)
    def test_accept_ra(self, run_mock: Mock) -> None:
        run_mock.return_value.stdout = b"0\n"
        assert spin.plugin.libvirt.checks.accept_ra_configured() is False
        run_mock.assert_called_with(
            ["sysctl", "-n", "net.ipv6.conf.all.accept_ra"],
            capture_output=True,
            check=False,
        )
        run_mock.reset_mock()

        run_mock.return_value.stdout = b"1\n"
        assert spin.plugin.libvirt.checks.accept_ra_configured() is False
        run_mock.assert_called_with(
            ["sysctl", "-n", "net.ipv6.conf.all.accept_ra"],
            capture_output=True,
            check=False,
        )
        run_mock.reset_mock()

        run_mock.return_value.stdout = b"2\n"
        assert spin.plugin.libvirt.checks.accept_ra_configured() is True
        run_mock.assert_called_with(
            ["sysctl", "-n", "net.ipv6.conf.all.accept_ra"],
            capture_output=True,
            check=False,
        )
        run_mock.reset_mock()


class TestLibvirtXMLGeneration:
    def test_common(self):
        from pathlib import Path
        from unittest.mock import Mock

        from spin.plugin.libvirt.xml import from_machine

        machine_mock = Mock(
            uuid="2555950a-cb2d-4adb-831d-515196174d8e",
            title=None,
            description=None,
            metadata={},
            shared_folders=[
                Mock(host_path=Path("/tmp/folder-0"), guest_path=Path("/var/folder-0")),
                Mock(host_path=Path("/tmp/folder-1"), guest_path=Path("/var/folder-1")),
            ],
            hardware=Mock(
                cpus=4,
                memory=Mock(bytes=4 * 1024 * 1024 * 1024),
                disk=Mock(
                    size=Mock(bytes=10 * 1024 * 1024 * 1024),
                    location=Path("/tmp/test-disk-image.qcow2"),
                ),
                **{"network.mode": "NAT", "network.network.name": "test-network"},
            ),
            diskarray=[],
        )
        machine_mock.configure_mock(name="machine_mock")

        xml = from_machine(machine_mock)

        assert xml.tag == "domain"
        assert len(xml) == 10

        for k in ["name", "uuid", "metadata", "features", "devices"]:
            assert len(xml.findall(k)) == 1

        assert (name := xml.find("name")) is not None and name.text == machine_mock.name
        assert (uuid := xml.find("uuid")) is not None and uuid.text == machine_mock.uuid
        assert (metadata := xml.find("metadata")) is not None and metadata.text is None
        assert xml.find("title") is None
        assert xml.find("description") is None

        features = xml.find("features")
        assert features is not None

        assert "acpi" in [child.tag for child in features]

        devices_tree = xml.find("devices")
        assert devices_tree is not None

        devs = list(devices_tree)
        assert len(devs) == 9

        assert len(devices_tree.findall("disk")) == 1
        disk = devices_tree.findall("disk")[0]
        assert disk.attrib == {"type": "file", "device": "disk"}
        assert len(disk.findall("source")) == 1
        assert disk.findall("source")[0].attrib == {
            "file": "/tmp/test-disk-image.qcow2"
        }
        assert len(disk.findall("target")) == 1
        assert disk.findall("target")[0].attrib == {"dev": "vda"}

        assert len(devices_tree.findall("interface")) == 1
        iface = devices_tree.findall("interface")[0]
        assert iface.attrib == {"type": "network"}
        assert len(iface.findall("source")) == 1
        assert iface.findall("source")[0].attrib == {"network": "test-network"}

        fss = devices_tree.findall("filesystem")

        sources: list[str] = []
        targets: list[str] = []
        for key, list_ in [("source", sources), ("target", targets)]:
            for fs in fss:
                elem = fs.find(key)
                assert elem is not None
                dir_ = elem.attrib["dir"]
                assert dir_ is not None
                list_.append(dir_)

        assert len(fss) == 2
        assert "/tmp/folder-0" in sources
        assert "/var/folder-0" in targets
        assert "/tmp/folder-1" in sources
        assert "/var/folder-1" in targets
        assert "/other/folder" not in sources
        assert "/other/folder" not in targets


# From: https://libvirt.org/formatnetwork.html#nat-based-network
NETWORK_XML_SAMPLE = """
<network>
  <name>default6</name>
  <bridge name="virbr0" />
  <forward mode="nat" />
  <ip address="192.168.122.1" netmask="255.255.255.0">
    <dhcp>
      <range start="192.168.122.2" end="192.168.122.254" />
    </dhcp>
  </ip>
  <ip family="ipv6" address="2001:db8:ca2:2::1" prefix="64">
    <dhcp>
      <range start="2001:db8:ca2:2:1::10" end="2001:db8:ca2:2:1::ff" />
    </dhcp>
  </ip>
</network>
"""


NETWORK_XML_SAMPLE_ALT = """
<network>
  <name>default6</name>
  <bridge name="virbr0" />
  <forward mode="nat" />
  <ip address="192.168.122.1" netmask="255.255.255.0">
    <dhcp>
      <range end="192.168.122.254" start="192.168.122.2" />
    </dhcp>
  </ip>
  <ip address="2001:db8:ca2:2::1" family="ipv6" prefix="64">
    <dhcp>
      <range end="2001:db8:ca2:2:1::ff" start="2001:db8:ca2:2:1::10" />
    </dhcp>
  </ip>
</network>
"""


class TestNetwork:
    @patch("spin.machine.network.LAN.uuid", new=lambda s: s.name)
    @patch("spin.plugin.libvirt.xml.spin.machine.network", autospec=True)
    @patch("spin.plugin.libvirt.core.libvirt", create=True)
    def test_network_from_XML(self, libvirt_mock: Mock, network_mock: Mock) -> None:
        """Test the conversion XML/libvirt-struct -> spin object"""
        uri = Mock(str())
        conn_mock = libvirt_mock.open.return_value.__enter__.return_value
        conn_mock.networkLookupByName.return_value.XMLDesc.return_value = (
            NETWORK_XML_SAMPLE
        )

        network_mock.LAN = Mock(
            LAN(uuid4().hex),
            **{"return_value.uuid": "default6", "return_value.name": "default6"},
        )

        under_testing = spin.plugin.libvirt.LibvirtNetworkInterface(uri)
        ret = under_testing.get("default6")

        assert ret is not None
        network_mock.LAN.assert_called_once_with(
            uuid="default6",
            nat=True,
            ipv4=network_mock.IPv4Network(
                network=ipaddress.IPv4Network("192.168.122.0/24", strict=False),
                gateway=ipaddress.IPv4Address("192.168.122.1"),
                dhcp=(
                    ipaddress.IPv4Address("192.168.122.2"),
                    ipaddress.IPv4Address("192.168.122.254"),
                ),
            ),
            ipv6=network_mock.IPv6Network(
                network=ipaddress.IPv6Network("2001:db8:ca2:2::/64", strict=False),
                gateway=ipaddress.IPv6Address("2001:db8:ca2:2::1"),
                dhcp=(
                    ipaddress.IPv6Address("2001:db8:ca2:2:1::10"),
                    ipaddress.IPv6Address("2001:db8:ca2:2:1::ff"),
                ),
            ),
        )

    @patch("spin.machine.network.secrets.token_hex", new=lambda _: "0")
    @patch("spin.plugin.libvirt.xml.secrets.token_hex", new=lambda _: "0")
    @patch("spin.plugin.libvirt.xml.spin.machine.network", autospec=True)
    @patch("spin.plugin.libvirt.core.libvirt", create=True)
    def test_XML_from_network(self, libvirt_mock: Mock, network_mock: Mock) -> None:
        expect_a = "".join(s.strip() for s in NETWORK_XML_SAMPLE.splitlines())
        expect_b = "".join(s.strip() for s in NETWORK_XML_SAMPLE_ALT.splitlines())
        mock_structure = {
            "name": "default6",
            "nat": True,
            "ipv4.network.gateway": "129.168.0.1",
            "ipv4.network.netmask": "255.255.255.0",
            "ipv4.gateway": "192.168.122.1",
            "ipv4.dhcp": ("192.168.122.2", "192.168.122.254"),
            "ipv6.network.prefixlen": "64",
            "ipv6.gateway": "2001:db8:ca2:2::1",
            "ipv6.dhcp": ("2001:db8:ca2:2:1::10", "2001:db8:ca2:2:1::ff"),
        }
        lan_mock = MagicMock(name="LanMock")
        lan_mock.configure_mock(**mock_structure)

        under_testing = spin.plugin.libvirt.LibvirtNetworkInterface(
            Mock(str(), name="uri")
        )
        under_testing.create(lan_mock)

        conn_mock = libvirt_mock.open.return_value.__enter__.return_value
        assert (
            call(expect_a) == conn_mock.networkDefineXML.mock_calls[0]
            or call(expect_b) == conn_mock.networkDefineXML.mock_calls[0]
        )


import spin.plugin.libvirt.xml as libvirt_xml


class TestXMLMachineStorage:
    @pytest.mark.parametrize("ndisks", [0, 1, 4])
    @pytest.mark.parametrize("ncdroms", [0, 1, 4])
    @pytest.mark.parametrize("main_disk", [Mock(Disk()), None])
    @pytest.mark.slow
    def test_basic(self, ndisks: int, ncdroms: int, main_disk) -> None:
        VDS = ndisks + (1 if main_disk is not None else 0)
        machine = MagicMock(Machine())
        machine.hardware.disk = main_disk
        xml = ET.Element("domain")
        devs = ET.SubElement(xml, "devices")
        machine.diskarray = [Mock(Disk()) for _ in range(ndisks)] + [
            Mock(CDROM("/dev/null")) for _ in range(ncdroms)
        ]
        libvirt_xml._machine_storage(machine, xml)

        assert len(devs.findall("disk")) == VDS + ncdroms

        disk_names = []
        for d in devs.findall("disk"):
            target = d.find("target")
            assert target is not None
            dev = target.attrib["dev"]
            assert dev is not None
            disk_names.append(dev)
        assert len(set(disk_names)) == len(disk_names)

        assert len([d for d in disk_names if d.startswith("sd")]) == ncdroms
        assert len([d for d in disk_names if d.startswith("vd")]) == VDS


@pytest.mark.slow
@patch("spin.plugin.libvirt.steps.libvirt", autospec=True)
class TestNetworkDestructionStep:
    @patch("spin.plugin.libvirt.steps.isinstance")
    def test_acceptance(self, isinstance_mock: Mock, libvirt_mock: Mock) -> None:
        isinstance_mock.return_value = True
        machine = Mock()
        machine.hardware.network = None

        under_test = DestroyNetwork.accepts
        assert under_test(machine) is False
        isinstance_mock.assert_not_called()

        machine.hardware.network = Mock(network=None)
        assert under_test(machine) is False
        isinstance_mock.assert_not_called()

        machine.hardware.network.network = Mock(deleted=True)
        assert under_test(machine) is True
        isinstance_mock.assert_called_once()

    @pytest.mark.parametrize("is_active", [True, False])
    @patch("spin.plugin.libvirt.steps.isinstance")
    def test_removal(
        self, isinstance_mock: Mock, libvirt_mock: Mock, is_active: bool
    ) -> None:
        isinstance_mock.return_value = True
        conn_mock = libvirt_mock.open.return_value.__enter__.return_value
        net = conn_mock.networkLookupByName.return_value
        net.isActive.return_value = is_active
        machine = Mock(spec=["hardware", "backend"])
        machine.hardware.network.mode = "user"

        under_test = DestroyNetwork(machine).process
        under_test()

        libvirt_mock.open.assert_not_called()

        machine.hardware.network.mode = Mock()
        machine.hardware.network.network = Mock(spec=["uuid", "deleted"])
        under_test()
        libvirt_mock.open.assert_called_once_with(machine.backend.uri)
        conn_mock.networkLookupByName.assert_called_once_with(
            machine.hardware.network.network.uuid
        )

        net.isActive.assert_called_once()
        if is_active is True:
            net.destroy.assert_called_once()
        net.undefine.assert_called_once()


@patch("spin.utils.info.kvm_present")
@patch("spin.utils.info.host_architecture")
class TestVirtualizationCapabilities:
    """Test the correct detection of virtualization mode depending on host capabilities"""

    def test_no_kvm(self, host_architecture: MagicMock, kvm_present: MagicMock) -> None:
        machine = MagicMock(Machine())
        xml = ET.Element("domain")

        machine.hardware_virtualization = "prefer"
        machine.image.props.architecture = "x86_64"
        kvm_present.return_value = False
        host_architecture.return_value = "x86_64"

        spin.plugin.libvirt.xml._machine_virt_mode(machine, xml)

        assert xml.attrib["type"] == "qemu"
        cpu_node = xml.find("cpu")
        assert cpu_node is not None
        assert cpu_node.attrib["mode"] == "maximum"

    def test_kvm(self, host_architecture: MagicMock, kvm_present: MagicMock) -> None:
        machine = MagicMock(Machine())
        xml = ET.Element("domain")

        machine.hardware_virtualization = "prefer"
        machine.image.props.architecture = "x86_64"
        kvm_present.return_value = True
        host_architecture.return_value = "x86_64"

        spin.plugin.libvirt.xml._machine_virt_mode(machine, xml)

        assert xml.attrib["type"] == "kvm"
        cpu_node = xml.find("cpu")
        assert cpu_node is not None
        assert cpu_node.attrib["mode"] == "host-passthrough"

    def test_diff_arch(
        self, host_architecture: MagicMock, kvm_present: MagicMock
    ) -> None:
        machine = MagicMock(Machine())
        xml = ET.Element("domain")

        machine.hardware_virtualization = "prefer"
        machine.image.props.architecture = "x86_64"
        kvm_present.return_value = True
        host_architecture.return_value = "arm64"

        spin.plugin.libvirt.xml._machine_virt_mode(machine, xml)

        assert xml.attrib["type"] == "qemu"
        cpu_node = xml.find("cpu")
        assert cpu_node is not None
        assert cpu_node.attrib["mode"] == "maximum"
