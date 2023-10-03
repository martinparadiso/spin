"""Check the serialization is working properly.
"""
from __future__ import annotations

import pathlib

import pytest

from spin.image.image import Image
from spin.machine.hardware import CDROM, Disk, SharedFolder, Storage
from spin.machine.machine import Machine


class TestRoundtrip:
    """Test the roundtrip of all the serializable classes"""

    def test_storage(self) -> None:
        disk = Disk()
        cdrom = CDROM("/tmp/cdrom.iso")

        serial_disk = disk.dict()
        serial_cdrom = cdrom.dict()

        new_disk = Disk(**serial_disk)
        new_cdrom = CDROM(**serial_cdrom)

        assert new_disk == disk
        assert new_cdrom == cdrom

        deserialized_disk = Storage.init_subclass(**serial_disk)
        deserialized_cdrom = Storage.init_subclass(**serial_cdrom)
        assert isinstance(deserialized_disk, Disk)
        assert isinstance(deserialized_cdrom, CDROM)

    def test_machine(self) -> None:
        old_machine = Machine()
        data = old_machine.dict()
        new_machine = Machine(**data)

        assert old_machine.dict() == new_machine.dict()
        assert new_machine == old_machine

    def test_disk(self) -> None:
        empty = Disk()
        serialized = empty.dict()
        assert Disk(**serialized) == empty


def test_machine(tmp_path: pathlib.Path):
    fake_file = tmp_path / "fake_image_file.img"
    fake_file.touch()
    vm = Machine()
    vm.name = "test-json"
    vm.shared_folders = [
        SharedFolder("/tmp/folder-1", "/tmp/folder-1"),
        SharedFolder("/tmp/folder-2", "/tmp/folder-2", read_only=True),
    ]
    vm.add_disk(CDROM("/tmp/some-cdrom.iso", uuid=None))
    vm.add_disk(Disk("10GiB", "/tmp/temp-disk", uuid=None))
    vm.image = Image("test", "image", file=fake_file)

    as_dict = vm.dict()
    EXPECT: dict = {
        "name": "test-json",
        "folder": None,
        "uuid": vm.uuid,
        "cloud_init": None,
        "ignition": None,
        "autodestroy": False,
        "hostname": None,
        "metadata": {},
        "info": {"boots": 0, "creation": None},
        "group": None,
        "options": {"wait_for_network": True, "wait_for_ssh": True},
        "description": None,
        "title": None,
        "hardware_virtualization": "prefer",
        "spinfile": None,
        "image": {
            "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        },
        "hardware": {
            "cpus": 2,
            "disk": {
                "backing_image": None,
                "location": None,
                "pool": None,
                "shared": False,
                "size": 10 * pow(2, 30),
                "uuid": None,
                "fmt": "qcow2",
                "label": None,
            },
            "memory": 2 * pow(2, 30),
            "network": {
                "shared": False,
                "mode": "NAT",
                "network": None,
                "forwarding": [],
            },
        },
        "shared_folders": [
            {
                "host_path": "/tmp/folder-1",
                "guest_path": "/tmp/folder-1",
                "read_only": False,
            },
            {
                "host_path": "/tmp/folder-2",
                "guest_path": "/tmp/folder-2",
                "read_only": True,
            },
        ],
        "diskarray": [
            {
                "location": "/tmp/some-cdrom.iso",
                "pool": None,
                "shared": False,
                "fmt": "iso",
                "label": None,
                "size": None,
                "uuid": None,
            },
            {
                "size": 10 * pow(2, 30),
                "location": "/tmp/temp-disk",
                "pool": None,
                "shared": False,
                "backing_image": None,
                "uuid": None,
                "fmt": "qcow2",
                "label": None,
            },
        ],
        "boot_order": [
            {
                "backing_image": None,
                "location": None,
                "pool": None,
                "shared": False,
                "size": 10 * pow(2, 30),
                "uuid": None,
                "fmt": "qcow2",
                "label": None,
            },
            {
                "location": "/tmp/some-cdrom.iso",
                "pool": None,
                "shared": False,
                "fmt": "iso",
                "label": None,
                "size": None,
                "uuid": None,
            },
            {
                "size": 10 * pow(2, 30),
                "location": "/tmp/temp-disk",
                "pool": None,
                "shared": False,
                "backing_image": None,
                "uuid": None,
                "fmt": "qcow2",
                "label": None,
            },
        ],
        "ssh": [],
        "on_creation": {"commands": []},
        "on_boot": {"commands": []},
        "plugins": [],
        "backend": None,
    }
    assert as_dict == EXPECT
