"""Test definition helpers and utilities"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest

import spin.define.basehelper
from spin.machine.machine import Machine


@patch("spin.define.basehelper.find_image", autospec=True)
@patch("spin.define.basehelper.MachineProcessor", autospec=True)
class TestDefaultDefinitionLoader:
    def test_machine_only(self, mp: Mock, find_image: Mock) -> None:
        find_image.return_value = Mock()
        machine = Mock(Machine())
        machine.image = None

        loader = spin.define.basehelper.DefaultLoader()
        loader.start(machine, None)
        loader.end(machine)

        assert machine.image is None
        find_image.assert_not_called()
        mp.assert_called_once_with(machine)
        mp.return_value.complete_definition.assert_called_once_with()

    def test_machine_with_image(self, mp: Mock, find_image: Mock) -> None:
        find_image.return_value = Mock()
        machine = Mock(Machine())

        loader = spin.define.basehelper.DefaultLoader()
        second_arg = (Mock(), Mock())
        loader.start(machine, second_arg)
        loader.end(machine)

        assert machine.image == find_image.return_value
        find_image.assert_called_once_with(second_arg)
        mp.assert_called_once_with(machine)
        mp.return_value.complete_definition.assert_called_once_with()
