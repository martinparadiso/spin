from __future__ import annotations

import glob
import os
import pathlib
import re
import subprocess as sp
import sys
from typing import Any
from unittest.mock import MagicMock, Mock, patch

import pkg_resources
import pytest
import yaml
from typing_extensions import Literal

import spin.cli
import spin.cli._status
import spin.cli._utils
import spin.machine.tracker
import spin.utils.ui
from spin.backend.base import MachineInterface
from spin.build.image_definition import ImageDefinition
from spin.errors import NoBackend, NotFound
from spin.image.image import Image
from spin.machine.machine import Machine


def cmd(*arr, extra_environ: None | dict = None):
    return sp.run(
        [*arr],
        capture_output=True,
        check=False,
        env=os.environ.update(extra_environ or {}),
    )


@pytest.mark.slow
class TestBasicCLI:
    """Test the CLI commands from the outside"""

    def test_short_version(self) -> None:
        ret = cmd("python", "-m", "spin", "--version")

        assert ret.returncode == 0
        assert len(ret.stderr) == 0
        assert (
            str(ret.stdout, "utf8")
            == f"spin {pkg_resources.get_distribution('spin').version}\n"
        )

    @pytest.mark.parametrize("arg", ["-h", "--help"])
    def test_help(self, arg) -> None:
        ret = cmd("python", "-m", "spin", arg)

        assert ret.returncode == 0
        assert len(ret.stderr) == 0
        assert len(ret.stdout) != 0

    def test_nothing(self) -> None:
        ret = cmd("python", "-m", "spin")

        assert ret.returncode != 0
        assert len(ret.stderr) == 0
        assert len(ret.stdout) != 0

    def test_list(self, configured_home: pathlib.Path) -> None:
        ret = cmd(
            "python",
            "-m",
            "spin",
            "--ui=fancy",
            "list",
            extra_environ={
                "XDG_CONFIG_HOME": str(configured_home / ".config"),
                "XDG_DATA_HOME": str(configured_home / ".local" / "share"),
            },
        )

        stdout = str(ret.stdout, "utf8")
        assert ret.returncode == 0
        # assert len(ret.stderr) == 0
        assert len(stdout.splitlines()) >= 1
        assert (
            re.match("^UUID +IMAGE +CREATED +STATUS +NAME *$", stdout.splitlines()[0])
            is not None
        )

    def test_version(self) -> None:
        ret = cmd("python", "-m", "spin", "version")

        assert len(ret.stdout.decode().splitlines()) >= 3
        assert len(ret.stderr) == 0
        assert yaml.load(ret.stdout.decode().splitlines()[2], Loader=yaml.SafeLoader)


class TestStatus:
    """Test basic status"""

    def test_empty(self, tmp_path: pathlib.Path) -> None:
        spinfile = tmp_path / "spinfile.py"
        spinfile.write_text("\n")

        with pytest.raises(Exception) as exce_info:
            spin.cli.print_status(tmp_path)

        exce_info.match("No definition\(s\) found")

    def test_simple(self, tmp_path: pathlib.Path) -> None:
        spinfile = tmp_path / "spinfile.py"
        spinfile.write_text(
            """
import spin

with spin.define.vm() as vm:
    pass
"""
        )

        spin.cli.print_status(tmp_path)
        rets = spin.cli._status.status(tmp_path)
        assert len(rets) == 1
        ret = rets[0]
        assert ret.ip == None
        assert ret.state == "DEFINED"
        assert ret.machine.image is None


class TestRun:
    """Call the big/wrapper CLI function"""

    def test_basic(self):
        with pytest.raises(SystemExit) as exce_info, patch(
            "spin.cli.print"
        ) as print_mock:
            spin.cli.run(["--version"])
        print_mock.assert_called_once_with(
            f"spin {pkg_resources.get_distribution('spin').version}"
        )
        assert exce_info.value.code == 0

        with pytest.raises(SystemExit) as exce_info:
            spin.cli.run("")
        assert exce_info.value.code == 127

        with pytest.raises(SystemExit) as exce_info:
            spin.cli.run(["non-existing-command"])
        assert exce_info.value.code == 2

    def test_dry_run_regression(self, tmp_path: pathlib.Path) -> None:
        import sys

        og_argv = sys.argv
        sys.argv = [sys.argv[0], "--dry-run", "init-conf"]
        with patch("spin.utils.config.conf.home", new=tmp_path):
            with pytest.raises(SystemExit) as exce_info:
                spin.cli.run(None)
        assert exce_info.value.code == 0
        sys.argv = og_argv
        assert [*tmp_path.iterdir()] == []


@patch("spin.cli._up.load", autospec=True)
class TestUp:
    """Test ``spin up`` functionality"""

    def test_none(self, load_mock: Mock) -> None:
        load_mock.return_value = None
        with pytest.raises(ValueError) as exce_info:
            spin.cli.up("", track=False)
        exce_info.match("not found machine")

    @patch("spin.cli._up.Database", autospec=True)
    @patch("spin.cli._up.Builder", autospec=True)
    @patch("spin.cli._up.MachineProcessor", autospec=True)
    @patch("spin.cli._up.has_backend", new=lambda *args: True)
    @pytest.mark.parametrize("in_backend_switch", [True, False])
    @pytest.mark.parametrize("track_switch", [True, False])
    @pytest.mark.slow
    def test_buildable_image(
        self,
        machine_processor: Mock,
        builder: Mock,
        local_database: Mock,
        load: Mock,
        in_backend_switch: bool,
        track_switch: bool,
    ) -> None:
        local_database.return_value.get.return_value = []
        image_def = Mock(ImageDefinition())
        machine = MagicMock(Machine(), image=image_def)
        machine.backend.exists.return_value = False
        machine.backend.is_running.return_value = False
        load.return_value = [machine]
        builder.return_value.build.return_value = Mock(image=Mock(Image()))
        machine_processor.configure_mock(**{"return_value.machine": machine})

        spin.cli.up("", track=track_switch)

        builder.assert_called_once_with(image_def)
        builder.return_value.build.assert_called_once()
        machine_processor.assert_called_once_with(machine, track=track_switch)

        if in_backend_switch:
            machine_processor.return_value.create.assert_called_once()

        machine_processor.return_value.start.assert_called_once()

    # TODO: Test passing multiple machines to up


class TestList:
    """Unit test the CLI functions by pathing other components"""

    @pytest.mark.parametrize("list_all", [True, False])
    @patch("spin.machine.tracker.Tracker")
    def test_list(self, MockTracker: Mock, list_all: bool) -> None:
        """Test listing the machine"""
        MockTracker.return_value.list_machines.return_value = [
            Mock(Machine(), name=str(i), state="RUNNING") for i in range(5)
        ]
        if list_all:
            MockTracker.return_value.list_machines.return_value.extend(
                [Mock(Machine(), name=str(i), state="SHUTOFF") for i in range(2)]
            )
        EXPECT = 8 if list_all else 6
        assert len(spin.cli.list_machines(list_all=list_all)) == EXPECT
        if list_all:
            MockTracker.return_value.list_machines.assert_called_once_with(status=None)
        else:
            MockTracker.return_value.list_machines.assert_called_once_with(
                status="RUNNING"
            )


@patch("spin.cli._utils.Tracker", autospec=True)
class TestLoad:
    """Test machine search and load"""

    @pytest.mark.parametrize("arg", ["/var/lib/machine/", "/machine", "/"])
    def test_search_by_path(self, tracker_mock: Mock, arg: str) -> None:
        with pytest.raises(NotFound) as exce_info:
            spin.cli._utils.load(arg, disable_definition=False)
        assert arg in str(exce_info)
        tracker_mock.assert_not_called()

    def test_search_by_uuid(self, tracker_mock: Mock) -> None:
        SOME_UUID = "82eec126-3680-47e9-8298-350a88fd6e1f"
        machine = Mock(name="Machine")
        tracker_mock.return_value.find.return_value = machine
        ret = spin.cli._utils.load(SOME_UUID, True)
        assert ret == [machine]
        tracker_mock.assert_called_once()
        tracker_mock.return_value.find.assert_called_once_with(uuid=SOME_UUID)


class TestDown:
    @patch("spin.cli._down.load", autospec=True)
    def test_no_vm_found(self, load_mock: Mock) -> None:
        load_mock.return_value = []
        spin.cli.down("")


@pytest.mark.slow
class TestDestroy:
    """Test machine destruction."""

    def test_running(self) -> None:
        """Try to destroy a running machine"""
        machine = MagicMock(spec=Machine, folder="")
        machine.backend = Mock(spec=MachineInterface)
        machine.backend.exists = MagicMock(return_value=True)
        machine.backend.is_running = MagicMock(return_value=True)

        with pytest.raises(ValueError) as exce_info:
            spin.cli.destroy(machine)
        assert "running machine" in str(exce_info)

    @patch("spin.machine.processor.Spinfolder", autospec=True)
    @patch("spin.machine.destruction_steps.Spinfolder", autospec=True)
    @patch("spin.machine.processor.is_created", new=lambda x: True)
    @patch("spin.machine.tracker.Tracker", autospec=spin.machine.tracker.Tracker)
    @patch("spin.cli._destroy.load", autospec=True)
    @pytest.mark.parametrize("machine_type", ["mock", "str"])
    @pytest.mark.parametrize("in_backend", [True, False])
    @pytest.mark.parametrize("machinefile_present", [True, False])
    def test_complete(
        self,
        load: Mock,
        tracker: MagicMock,
        SpinfolderMockProcessor: MagicMock,
        SpinfolderDestructionStepMock: MagicMock,
        machine_type: Literal["mock", "str"],
        in_backend: bool,
        machinefile_present: bool,
    ) -> None:
        attrs: dict[str, Any] = {
            "uuid": "some_uuid",
            "backend.exists.return_value": in_backend,
            "backend.is_running.return_value": False,
            "backend.delete.return_value": None,
        }
        if not machinefile_present:
            SpinfolderMockProcessor().delete_machine.side_effect = ValueError(
                "Missing machinefile / folder not initialized"
            )

        machine = MagicMock(Machine(), **attrs)

        def exists_fn(*args, **kwargs) -> bool:
            return in_backend

        machine.backend.exists.side_effect = exists_fn

        if machine_type == "mock":
            load.side_effect = Exception
            machine_arg: str | Mock = machine
        else:
            load.return_value = [machine]
            machine_arg = "."

        if machinefile_present:
            spin.cli.destroy(machine_arg, remove_disk=False)
        else:
            with pytest.raises(ValueError) as exce_info:
                spin.cli.destroy(machine_arg, remove_disk=False)
            assert exce_info.match("Missing machinefile")
            return

        assert machine.backend.exists.call_count >= 1
        if in_backend:
            machine.backend.delete.assert_called_once()
        else:
            machine.backend.delete.assert_not_called()

        if machinefile_present:
            SpinfolderMockProcessor().delete_machine.assert_called_once_with(
                machine, associated_files=True
            )

        tracker.assert_called()
        tracker.return_value.find.assert_called_once_with(uuid="some_uuid")


@pytest.mark.slow
class TestSSH:
    """Test ssh invocation from the CLI"""

    @patch("spin.cli._connect.SSHHelper", autospec=True)
    @patch("spin.cli._connect.load", autospec=True)
    def test_simple_ssh(self, load_patch: Mock, SSHHelperMock: Mock) -> None:
        machine = MagicMock(Machine())
        load_patch.return_value = [machine]

        with pytest.raises(SystemExit) as sys_exce_info:
            spin.cli.run(["ssh"])

        assert (
            sys_exce_info.value.args[0]
            == SSHHelperMock.return_value.run.return_value.returncode
        )
        SSHHelperMock.assert_called_once_with(
            machine,
            capture_output=False,
            flags=None,
            login=None,
            identity_file=None,
        )

        SSHHelperMock.return_value.run.assert_called_once_with(sys.stdin)

    @patch("spin.cli._connect.load", autospec=True)
    def test_not_found(self, load_patch: Mock, tmp_path: pathlib.Path) -> None:
        (tmp_path / "spinfile.py").touch()
        load_patch.return_value = []
        with pytest.raises(NotFound) as exce_info:
            spin.cli.run(["ssh", "i-dont-exist"])
        exce_info.match("i-dont-exist")


@pytest.mark.slow
class TestImageBuild:
    """Test the CLI interface for building images"""

    def test_empty(self) -> None:
        with pytest.raises(SystemExit) as exce_info:
            spin.cli.run(["build"])

        assert exce_info.match("2")

        with pytest.raises(SystemExit) as exce_info:
            spin.cli.run(["build", "--help"])

        assert exce_info.match("0")

    def test_non_existing_file(self, tmp_path: pathlib.Path) -> None:
        fake_file = tmp_path / "fake_file"
        with pytest.raises(FileNotFoundError) as exce_info:
            spin.cli.run(["build", str(fake_file)])

        assert exce_info.match(str(fake_file))

        fake_file.mkdir()

        with pytest.raises(ValueError) as exce_info2:
            spin.cli.run(["build", str(fake_file)])

        assert exce_info2.match(str(fake_file))
