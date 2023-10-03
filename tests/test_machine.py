from __future__ import annotations

import pathlib
import sys
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pytest
from typing_extensions import get_args

import spin.cli
import spin.define
import spin.machine.core as core
from spin.errors import NotFound
from spin.image.image import Image
from spin.machine.machine import Machine, ShellInput, is_under_creation
from spin.machine.tracker import Tracker
from spin.utils.constants import MACHINE_STATE_LITERAL
from spin.utils.load import SpinfileGroup
from spin.utils.sizes import Size


class TestCoreMachine:
    @patch("spin.machine.core._uuid.uuid4", autospec=True)
    def test_UUID(self, uuid4_mock: MagicMock) -> None:
        uuid4_mock.return_value = "96f7462f-4407-46a6-a699-150e47314d29"
        assert isinstance(core.UUID(), str)

        assert core.UUID() == "96f7462f-4407-46a6-a699-150e47314d29"
        assert (
            core.UUID("96f7462f-4407-46a6-a699-150e47314d30")
            == "96f7462f-4407-46a6-a699-150e47314d30"
        )

        with pytest.raises(ValueError):
            core.UUID("invalid-uuid")

        assert issubclass(Machine, core.CoreMachine)


class TestShellInput:
    """Tests for the shell"""

    def test_shell_input(self):
        shell = ShellInput(None)
        shell.add_command("whoami")

        assert len(shell.commands) == 1

        shell <<= "uname -a"

        assert len(shell.commands) == 2
        assert all(c.ignore_errors is False for c in shell.commands)

        shell.add_command("ip addr", ignore_errors=False)

        assert len(shell.commands) == 3
        assert shell.commands[-1].content == "ip addr"
        assert shell.commands[-1].ignore_errors is False

        assert [c.content for c in shell.commands] == [
            "whoami",
            "uname -a",
            "ip addr",
        ]

    def test_multiline(self):
        shell = ShellInput()

        shell <<= r"""
            another

            multiline
            command string
        """

        assert len(shell.commands) == 1
        assert shell.commands[0].content == "another\n\nmultiline\ncommand string\n"


def get_tracker_list_states() -> list[str]:
    return [*get_args(MACHINE_STATE_LITERAL)]


@pytest.mark.slow
@patch("spin.machine.tracker.conf")
class TestTrackerList:
    """Test the tracker, isolated/mocked"""

    @pytest.mark.parametrize("arg", get_tracker_list_states())
    def test_empty(self, config: Mock, arg, tmpdir: str) -> None:
        config.tracker_file = pathlib.Path(tmpdir) / "empty"
        with open(config.tracker_file, "w") as empty:
            empty.write("{}\n")
        ret = Tracker().list_machines(arg)
        assert len(ret) == 0

    @patch("spin.machine.tracker.json.load")
    @patch("spin.cli._utils.load")
    @pytest.mark.parametrize("state", get_tracker_list_states() + [None])
    def test_with_machines(
        self,
        machine_load: Mock,
        json_load: Mock,
        config: Mock,
        state,
        tmpdir: str,
    ) -> None:
        nmachines = 10 * len(get_tracker_list_states())
        json_load.return_value = dict(
            zip(
                range(nmachines),
                10 * [f"/machine/state/{s}/.spin" for s in get_tracker_list_states()],
            )
        )

        failed = {k: False for k in get_tracker_list_states()}

        def load_override(arg, disable_definition):
            assert disable_definition is True
            # One in ten machines must fail, this means at lest one of
            # each state will fail to load.
            state = str(arg).rsplit("/", maxsplit=1)[-1]
            if not failed[state]:
                failed[state] = True
                raise NotFound()
            loaded_machine = Mock(spec=Machine)
            loaded_machine.state = state
            return [loaded_machine]

        machine_load.configure_mock(side_effect=load_override)

        config.tracker_file = pathlib.Path(tmpdir) / "empty"
        with open(config.tracker_file, "w", encoding="utf8") as empty:
            empty.write("{}\n")
        ret = Tracker().list_machines(state)
        json_load.assert_called_once()
        # EXPECT = (10 * len(get_tracker_list_states())) if state is None else 9
        EXPECT = 9
        if state is None:
            EXPECT = 10 * len(get_tracker_list_states())
        elif state == "UNKNOWN":
            EXPECT = 16
        assert len(ret) == EXPECT
        assert machine_load.call_count == nmachines
        if state is not None:
            for vm in ret:
                assert vm.state == state


@patch("spin.machine.tracker.conf")
class TestTrackerRemove:
    """Test the tracker, isolated/mocked"""

    @patch("spin.machine.tracker.open")
    @patch("spin.machine.tracker.json.load")
    def test_removal(self, jsonload: Mock, open_: Mock, conf: Mock) -> None:
        machine = Machine()
        machine.uuid = core.UUID("41993c52-9c01-4d5e-ae9f-88b4a60c9128")
        jsonload.return_value = {}

        Tracker().remove(machine)

        assert jsonload.call_count == 1
        open_.assert_called_with(conf.tracker_file, "r")

        jsonload.return_value = {
            "machine-a": "",
            "41993c52-9c01-4d5e-ae9f-88b4a60c9128": "",
        }

        Tracker().remove(machine)

        open_.assert_called_with(conf.tracker_file, "w")


@patch("spin.machine.tracker.conf")
class TestTrackerAdd:
    """Test the tracker, isolated/mocked"""

    def test_missing_attrs(self, config_mock: Mock) -> None:
        machine = Mock(folder=None)
        with pytest.raises(ValueError) as exce_info:
            Tracker().add(machine)
        assert "no folder" in str(exce_info)

    def test_missing_file(self, config: Mock, tmpdir) -> None:
        machine = Mock(uuid="", folder="")
        config.tracker_file = pathlib.Path(tmpdir) / "nofile"

        with pytest.raises(FileNotFoundError) as exce_info:
            Tracker().add(machine)
        assert exce_info is not None

    def test_empty_file(self, config: Mock, tmpdir) -> None:
        attrs = {"uuid": "some_uuid", "folder.absolute.return_value": "/some/path"}
        machine = Mock(**attrs)
        config.tracker_file = pathlib.Path(tmpdir) / "empty"
        with open(config.tracker_file, "w") as empty:
            empty.write("{}\n")

        Tracker().add(machine)

        with open(config.tracker_file, "r") as non_empty:
            content = non_empty.read()
        assert "some_uuid" in content
        assert "/some/path" in content


class TestGroup:
    """Test basic machine group functionality"""

    def test_basic(self) -> None:
        assert hasattr(Machine(), "group")
        assert "group" in Machine.Serialized.__annotations__
        assert "group" in Machine().dict().keys()

    def test_spinfile_group(self) -> None:
        obj_a = SpinfileGroup(MagicMock(pathlib.Path()))
        data = obj_a.dict()
        kwargs: dict[str, Any] = {
            k: v for k, v in data.items() if k not in ("mod", "cls")
        }
        obj_b = SpinfileGroup(**kwargs)

        assert vars(obj_a) == vars(obj_b)


class TestTypeChecks:
    @patch("spin.machine.machine.is_defined", new=lambda _: True)
    def test_under_creation(self) -> None:
        machine_mock = MagicMock(Machine())
        machine_mock.image = MagicMock(Image())
        machine_mock.folder = None
        assert is_under_creation(machine_mock) is True

        machine_mock.folder = pathlib.Path()
        assert is_under_creation(machine_mock) is True

        machine_mock.image = MagicMock(str())
        assert is_under_creation(machine_mock) is False

        delattr(machine_mock, "folder")
        assert is_under_creation(machine_mock) is False
