"""Test the examples by calling them with a functional backend"""

from __future__ import annotations

import os
import pathlib
import shutil
from unittest.mock import Mock, patch

import pytest
from conftest import python_examples
from typing_extensions import TypeAlias

import spin.cli
import spin.cli._down
import spin.image.database
import spin.machine.start_steps
import spin.utils.ui
from spin.build.image_definition import ImageDefinition
from spin.machine.machine import has_backend


@pytest.fixture(autouse=False)
def cwd_to_tmp(tmp_path: pathlib.Path):
    path = tmp_path
    restore_path = pathlib.Path().absolute()
    os.chdir(path)
    yield path
    os.chdir(restore_path)


@pytest.mark.parametrize("file", python_examples(spinfile_only=True))
@pytest.mark.requires_backend
def test_example(
    file: pathlib.Path,
    cwd_to_tmp: pathlib.Path,
    configured_home: pathlib.Path,
    image_definition_ubuntu_focal: ImageDefinition,
    test_proxy: None | str,
) -> None:
    spin.utils.ui.instance().verbose = True
    assert file.exists()
    shutil.copy(file, cwd_to_tmp / "spinfile.py")
    assert file.parent.parent.parent.name == "tests"
    shutil.copytree(file.parent.parent.parent, cwd_to_tmp / "tests")
    spin.image.database.Database().remotes.add(image_definition_ubuntu_focal)
    machines = []
    machines = spin.cli.up(".", return_machines=True)
    assert len(machines) >= 1
    down_ret = spin.cli.down(".")
    assert down_ret == 0
    destroy_ret = spin.cli.destroy(".", remove_disk=True)
    assert destroy_ret == 0

    # Make sure the networks are destroyed
    for vm in machines:
        assert vm.hardware.network is not None
        assert vm.hardware.network.network is not None
        assert vm.hardware.network.network.deleted is True

        assert has_backend(vm)
        assert vm.hardware.network.network.name is not None
        assert vm.backend.main.network.get(vm.hardware.network.network.name) is None

    spin.utils.ui.instance().verbose = False


@patch("spin.cli._utils.Tracker", autospec=True)
@pytest.mark.parametrize("file", python_examples(spinfile_only=True))
def test_print_status(tracker_mock: Mock, file: pathlib.Path):
    # TODO: Is the tracker mock needed here?
    spin.cli.print_status(str(file))
