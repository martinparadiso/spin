"""Basic unit-test for credentials"""

import pathlib
from unittest.mock import MagicMock, Mock, patch

import pytest

from spin.machine.credentials import PasswordFile


@patch("spin.machine.credentials.open")
class TestPasswordFile:
    def test_basic(self, open_mock: Mock) -> None:
        path_mock = MagicMock(pathlib.Path())
        open_mock.return_value.__enter__.return_value = Mock(
            name="pass_file", **{"read.return_value": "password"}
        )
        demo = PasswordFile("user", path_mock)

        assert demo.user == "user"
        assert demo.password == "password"

        open_mock.assert_called_once_with(path_mock, encoding="utf8")
        open_mock.return_value.__enter__.return_value.read.assert_called_once_with()
