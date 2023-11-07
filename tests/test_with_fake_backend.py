"""Perform integration and end-to-end tests with fake backend"""

from __future__ import annotations

import ipaddress
import os
import pathlib
import subprocess
from unittest.mock import patch

import pytest
import utils

import spin.cli._status
import spin.image.database
from spin.build.image_definition import ImageDefinition
from spin.machine.tracker import Tracker
from spin.utils import ui


@pytest.mark.super_slow
def test_minimal(
    tmp_path: pathlib.Path,
    configured_home: pathlib.Path,
    image_definition_ubuntu_focal: ImageDefinition,
    test_proxy: None | str,
) -> None:
    utils.FakeBackend.reset_backend()
    spin.image.database.Database().remotes.add(image_definition_ubuntu_focal)
    folder = tmp_path
    spinfile = folder / "spinfile.py"

    with open("tests/examples/machine/minimal.py", encoding="utf8") as minimal:
        data = minimal.read()
    spinfile.write_text(data)

    status = spin.cli._status.status(folder)
    assert len(status) == 1
    assert status[0].ip is None
    assert status[0].state == "DEFINED"

    with patch("spin.utils.config.conf.default_backend", new=lambda: utils.FakeBackend):
        up_ret = spin.cli.up(folder)

    assert up_ret == 0

    status = spin.cli._status.status(folder)
    assert len(status) == 1
    assert status[0].ip == ipaddress.IPv4Address("192.168.0.100")
    assert status[0].state == "RUNNING"

    spin.cli.print_status(folder)

    machine = status[0].machine

    assert len(machine.ssh) == 1

    tracker = Tracker()
    assert len(tracker.list_machines()) == 1
    found = tracker.find(uuid=machine.uuid)
    assert found is not None
    assert found == machine


@pytest.mark.super_slow
def test_minimal_with_exception_in_step(
    tmp_path: pathlib.Path,
    configured_home: pathlib.Path,
    image_definition_ubuntu_focal: ImageDefinition,
    test_proxy: None | str,
) -> None:
    spin.image.database.Database().remotes.add(image_definition_ubuntu_focal)

    class CustomException(Exception):
        ...

    def raise_(*args, **kwargs):
        raise CustomException

    utils.FakeBackend.reset_backend()
    folder = tmp_path
    spinfile = folder / "spinfile.py"

    with open("tests/examples/machine/minimal.py", encoding="utf8") as minimal:
        data = minimal.read()
    spinfile.write_text(data)

    status = spin.cli._status.status(folder)
    assert len(status) == 1
    assert status[0].ip is None
    assert status[0].state == "DEFINED"

    with patch(
        "spin.utils.config.conf.default_backend", new=lambda: utils.FakeBackend
    ), patch("spin.machine.creation_steps.ExtraStorageAnywhere.solve", new=raise_):
        with pytest.raises(CustomException):
            up_ret = spin.cli.up(folder)

    # Check the disk has been removed
    status = spin.cli._status.status(folder)
    assert len(status) == 1
    assert status[0].ip is None
    assert status[0].state == "DEFINED"
    if (folder / ".spin" / status[0].machine.uuid).exists():
        assert len(list((folder / ".spin" / status[0].machine.uuid).iterdir())) == 0

    # TODO: Check if machines.json file is empty
    spin.cli.print_status(folder)

    machine = status[0].machine

    assert len(machine.ssh) == 1

    tracker = Tracker()
    assert len(tracker.list_machines()) == 0
    found = tracker.find(uuid=machine.uuid)
    assert found is None


@pytest.mark.super_slow
def test_two_machines(
    tmp_path: pathlib.Path,
    configured_home: pathlib.Path,
    image_definition_ubuntu_focal: ImageDefinition,
    test_proxy: None | str,
) -> None:
    spin.image.database.Database().remotes.add(image_definition_ubuntu_focal)
    utils.FakeBackend.reset_backend()
    folder = tmp_path
    spinfile = folder / "spinfile.py"

    with open("tests/examples/machine/multiple_vms.py", encoding="utf8") as minimal:
        data = minimal.read()
    spinfile.write_text(data)

    statuses = spin.cli._status.status(folder)
    assert len(statuses) == 2
    for status in statuses:
        assert status.ip is None
        assert status.state == "DEFINED"
    assert statuses[0].machine.group == statuses[1].machine.group

    with patch("spin.utils.config.conf.default_backend", new=lambda: utils.FakeBackend):
        up_ret = spin.cli.up(folder)

    assert len(utils.FakeBackend.machines) == 2
    assert up_ret == 0

    statuses = spin.cli._status.status(folder)
    spin.cli.print_status(folder)

    assert len(statuses) == 2
    for status in statuses:
        assert status.ip == ipaddress.IPv4Address("192.168.0.100")
        assert status.state == "RUNNING"

    first = statuses[0].machine
    second = statuses[1].machine

    assert first.name == "first"
    assert second.name == "second"

    assert first.hardware.network is not None
    assert second.hardware.network is not None
    assert first.hardware.network.network is not None
    assert second.hardware.network.network is not None
    assert first.hardware.network.network.uuid == second.hardware.network.network.uuid
    assert first.group == second.group

    with patch("spin.utils.config.conf.default_backend", new=lambda: utils.FakeBackend):
        down_ret = spin.cli.down(folder)
    assert down_ret == 0
    statuses = spin.cli._status.status(folder)
    assert len(statuses) == 2
    for status in statuses:
        assert status.state == "SHUTOFF"

    with patch("spin.utils.config.conf.default_backend", new=lambda: utils.FakeBackend):
        destroy_ret = spin.cli.destroy(folder, remove_disk=True)
    assert destroy_ret == 0
    statuses = spin.cli._status.status(folder)
    assert len(statuses) == 2
    for status in statuses:
        assert status.state == "DEFINED"

    assert not (folder / ".spin").exists()


@pytest.mark.parametrize(
    "script", list(pathlib.Path().glob("tests/examples/shell/*.sh"))
)
@pytest.mark.requires_backend
@pytest.mark.slow
def test_script(
    script: pathlib.Path,
    configured_home: pathlib.Path,
    image_definition_ubuntu_focal: ImageDefinition,
    tmp_path: pathlib.Path,
    test_proxy: None | str,
):
    spin.image.database.Database().remotes.add(image_definition_ubuntu_focal)
    folder = tmp_path
    spenv = os.environ.copy()
    spenv.update(
        {
            "XDG_CONFIG_HOME": str(configured_home / ".config"),
            "XDG_DATA_HOME": str(configured_home / ".local" / "share"),
        }
    )
    subprocess.run(
        ["sh", script.absolute()],
        env=spenv,
        cwd=folder,
        check=True,
    )
