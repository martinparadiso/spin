from __future__ import annotations

import json
import pathlib
from unittest.mock import Mock, patch

import pytest

import spin.machine.network as network


class TestPorts:
    def test_simple(self) -> None:
        mapping = network.PortMapping(22, 22, "tcp")

        assert mapping.host == 22
        assert mapping.guest == 22
        assert mapping.protocol == "tcp"

        assert str(mapping) == "22:22/tcp"
        assert repr(mapping) == "PortMapping(host=22, guest=22, protocol=tcp)"

    @pytest.mark.parametrize("port", [-1, 0, 65556, 100000])
    def test_invalid_ports(self, port: int) -> None:
        with pytest.raises(ValueError) as exce_info:
            network.PortMapping(22, port, "tcp")
        exce_info.match("out of range")

        with pytest.raises(ValueError) as exce_info:
            network.PortMapping(port, 22, "tcp")
        exce_info.match("out of range")

        with pytest.raises(ValueError) as exce_info:
            network.PortMapping(port, port, "tcp")
        exce_info.match("out of range")

    def test_compare(self) -> None:
        mapping_a = network.PortMapping(22, 22, "tcp")
        mapping_b = network.PortMapping(22, 22, "tcp")

        assert mapping_a == mapping_b
        assert mapping_a != (22, 22, "tcp")

    def test_serial(self) -> None:
        mapping = network.PortMapping(22, 22, "tcp")

        serial = mapping.dict()
        assert serial == (22, 22, "tcp")

        loaded = network.PortMapping(*serial)

        assert loaded.host == 22
        assert loaded.guest == 22
        assert loaded.protocol == "tcp"

        assert loaded == mapping


class TestNetwork:
    def test_one_instance_per_uuid(self) -> None:
        FAKE_NAME0 = "f22543ac-5059-465e-8a77-b3091dbd3382"
        FAKE_NAME1 = "f2ceffb9-623c-448f-8002-511e19ff93d6"
        lan0 = network.LAN(FAKE_NAME0)
        lan00 = network.LAN(FAKE_NAME0)
        lan1 = network.LAN(FAKE_NAME1)

        assert lan0 is not lan1
        assert lan0 is lan00
        assert lan00 is network.LAN(FAKE_NAME0)
        assert lan00 is network.LAN(FAKE_NAME0)

        user = Mock()
        # Prevent saving
        with patch("spin.machine.network.LAN.save"):
            lan0.add(user)
        assert user in lan0.users()
        assert user in lan00.users()
        assert user not in lan1.users()

        # Create a new object; to make sure the object is
        # not being re-initialized
        lan000 = network.LAN(FAKE_NAME0)
        assert user in lan0.users()
        assert user in lan00.users()
        assert user in lan000.users()

        network.LAN._instances = {}

    def test_serialization(self) -> None:
        FAKE_NAME0 = "f22543ac-5059-465e-8a77-b3091dbd3382"
        lan = network.LAN(FAKE_NAME0)
        lan.dict()
        network.LAN._instances = {}

    @patch("spin.machine.network.conf", autospec=True)
    def test_save_and_load(self, mock_config: Mock, tmp_path: pathlib.Path) -> None:
        FAKE_NAME0 = "f22543ac-5059-465e-8a77-b3091dbd3382"
        FAKE_NAME1 = "f2ceffb9-623c-448f-8002-511e19ff93d6"
        FAKE_NAME2 = "d65a0c5b-7bcc-4b82-a00c-a1d9ecf15964"
        fake_networks = tmp_path / "networks.json"
        fake_networks.write_text("{}")
        mock_config.networks_file = fake_networks

        lan0 = network.LAN(uuid=FAKE_NAME0)
        assert network.find(FAKE_NAME0) is None
        lan0.save()
        assert vars(network.find(FAKE_NAME0)) == vars(lan0)

        lan1 = network.LAN(uuid=FAKE_NAME1)
        lan1.save()

        assert network.find("jkhdfkjgh") is None
        assert vars(network.find(FAKE_NAME0)) == vars(lan0)
        assert vars(network.find(FAKE_NAME1)) == vars(lan1)
        assert vars(network.find(FAKE_NAME0)) != vars(lan1)
        assert vars(network.find(FAKE_NAME1)) != vars(lan0)

        lan2 = network.LAN(
            FAKE_NAME2, ipv4=network.IPv4Network("10.0.0.0/24", "10.0.0.1")
        )
        lan2.save()
        restored = network.find(FAKE_NAME2)
        assert restored is not None
        assert restored.ipv4 is not None
        assert lan2.ipv4 is not None
        assert restored.nat == lan2.nat
        assert restored.name == lan2.name
        assert restored.ipv4 != "auto"
        assert lan2.ipv4 != "auto"
        assert restored.ipv4.network == lan2.ipv4.network
        assert restored.ipv4.gateway == lan2.ipv4.gateway
        assert restored.ipv4.dhcp == lan2.ipv4.dhcp
        assert restored.ipv6 == "auto" == lan2.ipv6

        assert len(json.loads(fake_networks.read_text())) == 3
        network.LAN._instances = {}

    @pytest.mark.parametrize(
        "broadcast_and_max",
        [
            (3232235775, 3232235774),  # 192.168.0.0/24
            (168787967, 168787966),  # 10.15.0.0/17
        ],
    )
    @patch("spin.machine.network.ipaddress.IPv4Address", autospec=True)
    def test_dhcpv4_range(
        self, ipaddr: Mock, broadcast_and_max: tuple[int, int]
    ) -> None:
        broadcast, last_addr = broadcast_and_max
        network_mock = Mock(version=4)
        first_host, second_host = Mock(), Mock()
        network_mock.hosts.return_value = [first_host, second_host]
        network_mock.broadcast_address.packed = int(broadcast).to_bytes(4, "big")
        ret = network.dhcp(network_mock)

        ipaddr.assert_called_with(last_addr)
        assert ret[0] == second_host
        assert ret[1] == ipaddr(last_addr)
